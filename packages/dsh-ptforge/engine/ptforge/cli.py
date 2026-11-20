"""Command line front end: build, inspect and open Packet Tracer topologies."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from . import catalog, edit
from .build import TopologyBuilder
from .ptcrypto import ptfile
from .spec import SpecError, build_from_spec, load_spec


def _emit(payload: dict, *, as_json: bool) -> None:
    if as_json:
        clean = {key: value for key, value in payload.items() if key != "_text"}
        print(json.dumps(clean, ensure_ascii=False, indent=2))
        return
    for line in payload.get("_text", []):
        print(line)


def _model_info() -> list[dict]:
    out: list[dict] = []
    for model in catalog.models():
        element = catalog.template(model)
        out.append(
            {
                "model": model,
                "kind": catalog.engine(element).findtext("TYPE"),
                "ports": [n for n in catalog.port_names(element) if n],
            }
        )
    return out


def cmd_models(args: argparse.Namespace) -> int:
    info = _model_info()
    query = (getattr(args, "query", None) or "").strip().lower()
    if query:
        info = [item for item in info if query in item["model"].lower()]
    limit = getattr(args, "limit", 0) or 0
    if limit > 0:
        info = info[:limit]
    if not info:
        print("no models matched")
        return 0
    if args.json:
        _emit({"models": info}, as_json=True)
        return 0
    for item in info:
        ports = ", ".join(item["ports"][:8])
        if len(item["ports"]) > 8:
            ports += f", … ({len(item['ports'])} total)"
        print(f"{item['model']:<22} {item['kind'] or '?':<10} {ports}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    try:
        data = load_spec(args.spec)
    except (OSError, json.JSONDecodeError, SpecError) as exc:
        print(f"spec error: {exc}", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else Path(args.spec).with_suffix(".pkt")
    path = build_from_spec(data, out)
    root = ptfile.decode(str(path))
    summary = _topology(root)
    summary["path"] = str(path)
    summary["bytes"] = path.stat().st_size
    if args.json:
        _emit(summary, as_json=True)
    else:
        print(path)
        for line in _render_topology(summary):
            print(line)
    return 0


def _topology(root: ET.Element) -> dict:
    devices = root.findall("NETWORK/DEVICES/DEVICE")
    links = root.findall("NETWORK/LINKS/LINK")
    ref_to_name: dict[str, str] = {}
    device_items: list[dict] = []
    for dev in devices:
        eng = dev.find("ENGINE")
        if eng is None:
            continue
        name = eng.findtext("NAME") or "?"
        type_el = eng.find("TYPE")
        kind = type_el.text if type_el is not None else "?"
        model = (type_el.get("model") if type_el is not None else "") or ""
        ref = eng.findtext("SAVE_REF_ID") or ""
        if ref:
            ref_to_name[ref] = name
        ws = dev.find("WORKSPACE/LOGICAL")
        coords = dev.find("ENGINE/COORD_SETTINGS")
        x = coords.findtext("X_COORD") if coords is not None else None
        y = coords.findtext("Y_COORD") if coords is not None else None
        ports = [n for n in catalog.port_names(dev) if n]
        names = catalog.port_names(dev)
        addresses: list[dict] = []
        for index, port_el in enumerate(catalog.ports(dev)):
            ip = port_el.findtext("IP")
            if not ip:
                continue
            address = {
                "port": names[index] if index < len(names) else None,
                "ip": ip,
                "mask": port_el.findtext("SUBNET"),
            }
            gateway = port_el.findtext("PORT_GATEWAY")
            if gateway:
                address["gateway"] = gateway
            addresses.append(address)
        device_items.append(
            {
                "name": name,
                "kind": kind,
                "model": model or None,
                "x": _num(x),
                "y": _num(y),
                "logical": (
                    {"x": _num(ws.findtext("X")), "y": _num(ws.findtext("Y"))}
                    if ws is not None
                    else None
                ),
                "ports": ports,
                "addresses": addresses,
                "config": edit.config_lines(dev),
            }
        )
    link_items: list[dict] = []
    for link in links:
        cable = link.find("CABLE")
        if cable is None:
            continue
        endpoints = cable.findall("PORT")
        frm = cable.findtext("FROM") or ""
        to = cable.findtext("TO") or ""
        link_items.append(
            {
                "from": ref_to_name.get(frm, frm),
                "from_port": endpoints[0].text if len(endpoints) > 0 else None,
                "to": ref_to_name.get(to, to),
                "to_port": endpoints[1].text if len(endpoints) > 1 else None,
                "cable": cable.findtext("TYPE"),
            }
        )
    return {"version": root.findtext("VERSION"), "devices": device_items, "links": link_items}


def _num(value: str | None):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except ValueError:
        return value
    return int(number) if number.is_integer() else number


def _render_topology(summary: dict) -> list[str]:
    lines = [
        f"version  {summary['version']}",
        f"devices  {len(summary['devices'])}",
    ]
    for dev in summary["devices"]:
        pos = dev["logical"] or {}
        where = f"({pos.get('x')},{pos.get('y')})" if pos else ""
        lines.append(
            f"  {dev['name']:<14} {dev['kind'] or '?':<10} {where:<12} ports={len(dev['ports'])}"
        )
        if dev["config"]:
            lines.append(f"      config: {len(dev['config'])} lines")
    lines.append(f"links    {len(summary['links'])}")
    for link in summary["links"]:
        lines.append(
            f"  {link['from']} {link['from_port']} -> {link['to']} {link['to_port']}"
            f" [{link['cable']}]"
        )
    return lines


def cmd_inspect(args: argparse.Namespace) -> int:
    root = ptfile.decode(args.pkt)
    summary = _topology(root)
    summary["path"] = str(args.pkt)
    if args.json:
        _emit(summary, as_json=True)
        return 0
    for line in _render_topology(summary):
        print(line)
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    root = edit.load(args.pkt)
    dev = edit.device(root, args.device)
    if args.lines:
        lines = args.lines
        if len(lines) == 1 and Path(lines[0]).is_file():
            lines = Path(lines[0]).read_text(encoding="utf-8").splitlines()
    elif args.file:
        lines = Path(args.file).read_text(encoding="utf-8").splitlines()
    else:
        print("apply needs --file or --lines", file=sys.stderr)
        return 2
    merged = edit.set_config(dev, lines, replace=args.replace)
    if args.ip:
        if not args.port:
            print("--ip needs --port", file=sys.stderr)
            return 2
        edit.set_ipv4(dev, args.port, args.ip, args.mask, args.gateway)
    out = Path(args.out) if args.out else Path(args.pkt)
    edit.save(root, out)
    summary = {
        "path": str(out),
        "device": args.device,
        "config_lines": len(merged),
    }
    _emit(summary, as_json=args.json)
    return 0


def cmd_state(args: argparse.Namespace) -> int:
    from . import state

    root = state.load(args.pkt)
    payload = state.describe(root)
    if args.device:
        payload = state.device_state(root, args.device)
    if args.json:
        _emit(payload, as_json=True)
        return 0
    devices = payload["devices"] if "devices" in payload else [payload]
    for dev in devices:
        print(f"{dev['name']}  {dev['kind']}  {dev['model'] or ''}")
        for iface in dev["interfaces"]:
            if iface["ip"]:
                mask = f"/{iface['prefix']}" if iface["prefix"] is not None else ""
                print(
                    f"  {iface['name']:<22} {iface['ip']}{mask}"
                    + (f"  gw {iface['gateway']}" if iface["gateway"] else "")
                )
        for route in dev["static_routes"]:
            print(f"  route {route['cidr']} via {route['next_hop']}")
        for line in dev["nat"]:
            print(f"  {line}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    from . import state

    root = state.load(args.pkt)
    expectations = json.loads(Path(args.expect).read_text(encoding="utf-8"))
    if isinstance(expectations, dict):
        expectations = expectations.get("expect", [])
    report = state.check(root, expectations)
    _emit(report, as_json=args.json)
    if not args.json:
        for item in report["results"]:
            mark = "PASS" if item["ok"] else "FAIL"
            print(f"{mark} {item['device']}: {item['expect']}")
            for problem in item["problems"]:
                print(f"     - {problem}")
    return 0 if report["ok"] else 1


def cmd_patch(args: argparse.Namespace) -> int:
    from . import patch

    ops = json.loads(Path(args.ops).read_text(encoding="utf-8"))
    if isinstance(ops, dict):
        ops = ops.get("ops", [])
    summary = patch.patch_file(args.pkt, ops, out=args.out)
    _emit(summary, as_json=args.json)
    if not args.json:
        print(summary["path"])
        for change in summary["ops"]:
            print(f"  {change['op']} {change.get('device')}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from . import doctor

    payload = {"environment": doctor.environment()}
    if args.pkt:
        payload["file"] = doctor.verify_file(args.pkt)
        # A file check answers "will Packet Tracer 8.1 load this?" — a missing
        # local install is reported above but must not fail the check, otherwise
        # the command is useless in CI and inside the Linux container.
        payload["ok"] = payload["file"]["ok"]
    else:
        payload["ok"] = payload["environment"]["ok"]
    _emit(payload, as_json=args.json)
    if not args.json:
        env = payload["environment"]
        print(f"packet tracer: {env['packet_tracer'] or 'missing'}")
        for issue in env["issues"]:
            print(f"  ! {issue}")
        if "file" in payload:
            file_info = payload["file"]
            print(
                f"file: {file_info['path']} version={file_info['version']} "
                f"devices={file_info['devices']} links={file_info['links']}"
            )
            for issue in file_info["issues"]:
                print(f"  ! {issue}")
    return 0 if payload["ok"] else 1


def cmd_report(args: argparse.Namespace) -> int:
    from . import report

    figures = []
    if args.figure:
        figures = json.loads(Path(args.figure).read_text(encoding="utf-8"))
    summary = report.build_report(args.pkt, args.out, figures=figures, title=args.title)
    _emit(summary, as_json=args.json)
    if not args.json:
        print(summary["dir"])
        print(f"  {summary['addresses']} addresses, {summary['links']} links")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    b = TopologyBuilder()
    b.add_device(
        "PC-PT", "PC0", 260, 180, ipv4=("192.168.10.10", "255.255.255.0", "192.168.10.1")
    )
    b.add_device(
        "2960-24TT", "SW1", 520, 300, config=["enable", "configure terminal", "hostname SW1"]
    )
    b.connect("PC0", "SW1", a_port="FastEthernet0", b_port="FastEthernet0/1")
    out = b.save(args.out)
    print(out)
    return 0



def cmd_web(args: argparse.Namespace) -> int:
    from . import web as webmod

    if args.action == "list":
        payload = webmod.list_pages(args.pkt)
        payload["_text"] = [f'{payload["device"]}: ' + ", ".join(payload["pages"])]
    elif args.action == "get":
        payload = webmod.read_page(args.pkt, args.device, args.name)
        payload["_text"] = [payload["html"]]
    else:
        html = args.html or ""
        if args.html_file:
            html = Path(args.html_file).read_text(encoding="utf-8")
        if not html:
            raise SystemExit("web set needs --html or --html-file")
        payload = webmod.set_page(
            args.pkt, html, device=args.device, name=args.name, out=args.out
        )
        payload["_text"] = [f'{payload["device"]}:{payload["page"]} <- {payload["bytes"]} chars']
    _emit(payload, as_json=args.json)
    return 0
def cmd_note(args: argparse.Namespace) -> int:
    from . import notes as note_mod

    root = edit.load(args.pkt)
    if args.list:
        payload = {"notes": note_mod.notes(root)}
    elif args.remove is not None:
        payload = note_mod.remove_note(root, args.remove)
        edit.save(root, args.out or args.pkt)
        payload["path"] = args.out or args.pkt
    elif args.set_index is not None:
        payload = note_mod.set_note_text(root, args.set_index, args.text or "")
        edit.save(root, args.out or args.pkt)
        payload["path"] = args.out or args.pkt
    else:
        if not args.text:
            raise SystemExit("note needs --text when adding")
        payload = note_mod.add_note(
            root,
            args.text,
            x=args.x if args.x is not None else 200.0,
            y=args.y if args.y is not None else 200.0,
            anchor_device=args.device,
            dx=args.dx,
            dy=args.dy,
        )
        edit.save(root, args.out or args.pkt)
        payload["path"] = args.out or args.pkt
    _emit(payload, as_json=not args.human)
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    from .launch import maximize, open_in_pt, wait_until_open

    pid = open_in_pt(args.pkt)
    ok, title = wait_until_open(pid, args.pkt, timeout=args.timeout)
    if ok:
        maximize(pid)
    if args.json:
        print(json.dumps({"pid": pid, "ok": ok, "title": title}, ensure_ascii=False))
    else:
        print(f"pid={pid} ok={ok} title={title}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ptforge", description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine readable output")
    sub = parser.add_subparsers(dest="command", required=True)

    p_models = sub.add_parser("models", help="list device models with their interfaces")
    p_models.add_argument("-q", "--query", help="only models whose name contains this text (case-insensitive)")
    p_models.add_argument("-n", "--limit", type=int, default=0, help="cap the number of rows (0 = all)")
    p_models.set_defaults(func=cmd_models)

    p_build = sub.add_parser("build", help="build a .pkt from a JSON spec")
    p_build.add_argument("spec")
    p_build.add_argument("-o", "--out")
    p_build.set_defaults(func=cmd_build)

    p_inspect = sub.add_parser("inspect", help="show devices, ports and links of a .pkt")
    p_inspect.add_argument("pkt")
    p_inspect.set_defaults(func=cmd_inspect)

    p_apply = sub.add_parser("apply", help="write CLI config onto an existing device")
    p_apply.add_argument("pkt")
    p_apply.add_argument("--device", required=True)
    p_apply.add_argument("--file", help="text file with one CLI line per row")
    p_apply.add_argument("--lines", nargs="+", help="CLI lines (or one text file path)")
    p_apply.add_argument(
        "--replace",
        action="store_true",
        help="replace the whole running-config instead of merging sections",
    )
    p_apply.add_argument("--ip", help="static IPv4 address for an end device")
    p_apply.add_argument("--mask", default="255.255.255.0")
    p_apply.add_argument("--gateway")
    p_apply.add_argument("--port", help="interface receiving --ip")
    p_apply.add_argument("-o", "--out")
    p_apply.set_defaults(func=cmd_apply)

    p_demo = sub.add_parser("demo", help="write a minimal demo topology")
    p_demo.add_argument("-o", "--out", default="demo.pkt")
    p_demo.set_defaults(func=cmd_demo)

    p_state = sub.add_parser("state", help="read structured device state from a .pkt")
    p_state.add_argument("pkt")
    p_state.add_argument("--device", help="only report this device")
    p_state.set_defaults(func=cmd_state)

    p_check = sub.add_parser("check", help="assert expectations against a .pkt")
    p_check.add_argument("pkt")
    p_check.add_argument("--expect", required=True, help="JSON file with expectation objects")
    p_check.set_defaults(func=cmd_check)

    p_patch = sub.add_parser("patch", help="apply incremental edits to a .pkt")
    p_patch.add_argument("pkt")
    p_patch.add_argument("--ops", required=True, help="JSON file with operation objects")
    p_patch.add_argument("-o", "--out")
    p_patch.set_defaults(func=cmd_patch)

    p_doctor = sub.add_parser("doctor", help="check Packet Tracer install and file version")
    p_doctor.add_argument("pkt", nargs="?")
    p_doctor.set_defaults(func=cmd_doctor)

    p_report = sub.add_parser("report", help="write figures/captions/report tables")
    p_report.add_argument("pkt")
    p_report.add_argument("-o", "--out", default="report")
    p_report.add_argument("--figure", help="JSON list of figure entries")
    p_report.add_argument("--title")
    p_report.set_defaults(func=cmd_report)

    p_web = sub.add_parser("web", help="read or replace a Server-PT HTTP page")
    p_web.add_argument("action", choices=["list", "get", "set"])
    p_web.add_argument("pkt")
    p_web.add_argument("--device")
    p_web.add_argument("--name", default="index.html")
    p_web.add_argument("--html")
    p_web.add_argument("--html-file")
    p_web.add_argument("-o", "--out")
    p_web.set_defaults(func=cmd_web)
    p_note = sub.add_parser("note", help="list or add canvas annotations")
    p_note.add_argument("pkt")
    p_note.add_argument("--list", action="store_true")
    p_note.add_argument("--text", default="")
    p_note.add_argument("--device", default=None)
    p_note.add_argument("--x", type=float, default=None)
    p_note.add_argument("--y", type=float, default=None)
    p_note.add_argument("--dx", type=float, default=0.0)
    p_note.add_argument("--dy", type=float, default=-60.0)
    p_note.add_argument("--set-index", type=int, default=None)
    p_note.add_argument("--remove", type=int, default=None)
    p_note.add_argument("-o", "--out", default=None)
    p_note.add_argument("--human", action="store_true")
    p_note.set_defaults(func=cmd_note)

    p_open = sub.add_parser("open", help="open a .pkt in Packet Tracer and verify")
    p_open.add_argument("pkt")
    p_open.add_argument("--timeout", type=float, default=25.0)
    p_open.set_defaults(func=cmd_open)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())






"""Tiny input driver used by the runtime tools (also handy from a shell).

Packet Tracer exposes no automation API, so the runtime half of the engine
opens device windows and runs CLI commands by injecting input into the Qt
window. This module is the primitive layer: activate, click, type, read back.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import gui


def _activate_by_title(needle: str) -> tuple[int, str] | None:
    matches = gui.list_windows(needle)
    if not matches:
        return None
    hwnd, title = matches[0]
    gui.activate(hwnd)
    time.sleep(0.4)
    return hwnd, title


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ptforge.guitool")
    sub = parser.add_subparsers(dest="action", required=True)

    click = sub.add_parser("click")
    click.add_argument("x", type=int)
    click.add_argument("y", type=int)
    click.add_argument("--double", action="store_true")
    click.add_argument("--title", default="")

    type_cmd = sub.add_parser("type")
    type_cmd.add_argument("text")
    type_cmd.add_argument("--title", default="")

    key = sub.add_parser("key")
    key.add_argument("keys", nargs="+")
    key.add_argument("--title", default="")

    shot = sub.add_parser("shot")
    shot.add_argument("path")
    shot.add_argument("--region", default="")

    focus = sub.add_parser("focus")
    focus.add_argument("title")

    paste = sub.add_parser("paste")
    paste.add_argument("text")
    paste.add_argument("--title", default="")
    paste.add_argument("--enter", action="store_true")

    copy = sub.add_parser("copy")
    copy.add_argument("--title", default="")

    clip = sub.add_parser("clipboard")
    clip.add_argument("--set", dest="set_text", default=None)

    exec_cmd = sub.add_parser("exec")
    exec_cmd.add_argument("device")
    exec_cmd.add_argument("commands", nargs="+")
    exec_cmd.add_argument("--out", default="")
    exec_cmd.add_argument("--wait", type=float, default=1.2)
    exec_cmd.add_argument("--no-read", action="store_true")

    assert_cmd = sub.add_parser("assert")
    assert_cmd.add_argument("device")
    assert_cmd.add_argument("--checks", required=True)
    assert_cmd.add_argument("--wait", type=float, default=2.0)

    ping_cmd = sub.add_parser("ping")
    ping_cmd.add_argument("device")
    ping_cmd.add_argument("target")
    ping_cmd.add_argument("--count", type=int, default=4)
    ping_cmd.add_argument("--wait", type=float, default=8.0)

    http_cmd = sub.add_parser("http")
    http_cmd.add_argument("device")
    http_cmd.add_argument("url")
    http_cmd.add_argument("--out", default="")
    http_cmd.add_argument("--wait", type=float, default=3.0)

    ftp_cmd = sub.add_parser("ftp")
    ftp_cmd.add_argument("device")
    ftp_cmd.add_argument("server")
    ftp_cmd.add_argument("--user", default="cisco")
    ftp_cmd.add_argument("--password", default="cisco")
    ftp_cmd.add_argument("--cmd", action="append", dest="cmds")
    ftp_cmd.add_argument("--out", default="")
    ftp_cmd.add_argument("--wait", type=float, default=3.0)

    args = parser.parse_args(argv)
    result: dict[str, object] = {"action": args.action}

    if args.action == "focus":
        found = _activate_by_title(args.title)
        result.update(found=bool(found), window=found)
    elif args.action in {"click", "type", "key", "paste"}:
        title = getattr(args, "title", "")
        if title:
            found = _activate_by_title(title)
            if not found:
                print(json.dumps({"error": f"no window matching {title!r}"}))
                return 1
            result["window"] = found
        if args.action == "click":
            if args.double:
                gui.double_click(args.x, args.y)
            else:
                gui.click(args.x, args.y)
            result["point"] = [args.x, args.y]
        elif args.action == "type":
            gui.type_text(args.text)
            result["chars"] = len(args.text)
        elif args.action == "paste":
            result["pasted"] = gui.paste_text(args.text)
            if args.enter:
                gui.press("enter")
        else:
            for item in args.keys:
                if "+" in item:
                    gui.hotkey(*item.split("+"))
                else:
                    gui.press(item)
            result["keys"] = args.keys
    elif args.action == "copy":
        title = args.title
        if title:
            found = _activate_by_title(title)
            if not found:
                print(json.dumps({"error": f"no window matching {title!r}"}))
                return 1
            result["window"] = found
        gui.set_clipboard("")
        gui.hotkey("ctrl", "a")
        time.sleep(0.15)
        gui.hotkey("ctrl", "c")
        time.sleep(0.3)
        text = gui.get_clipboard()
        result["text"] = text
        result["chars"] = len(text)
    elif args.action == "clipboard":
        if args.set_text is None:
            result["text"] = gui.get_clipboard()
        else:
            result["ok"] = gui.set_clipboard(args.set_text)
    elif args.action == "exec":
        from . import runtime

        result.update(
            runtime.exec_commands(
                args.device,
                args.commands,
                out=args.out or None,
                wait=args.wait,
                read=not args.no_read,
            )
        )
    elif args.action == "assert":
        import json as _json

        from . import runtime as _runtime

        checks = _json.loads(args.checks)
        result.update(
            _runtime.check_output(args.device, checks, wait=args.wait)
        )
    elif args.action == "ping":
        from . import runtime as _runtime

        result.update(_runtime.ping(args.device, args.target, count=args.count, wait=args.wait))
    elif args.action == "http":
        from . import runtime as _runtime

        result.update(_runtime.http_get(args.device, args.url, wait=args.wait, out=args.out or None))
    elif args.action == "ftp":
        from . import runtime as _runtime

        result.update(
            _runtime.ftp_session(
                args.device,
                args.server,
                username=args.user,
                password=args.password,
                commands=args.cmds,
                wait=args.wait,
                out=args.out or None,
            )
        )
    elif args.action == "shot":
        region = None
        if args.region:
            parts = [int(value) for value in args.region.split(",")]
            region = (parts[0], parts[1], parts[2], parts[3])
        path = gui.screenshot(args.path, region=region)
        result["path"] = str(path)
        result["bytes"] = Path(path).stat().st_size

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())





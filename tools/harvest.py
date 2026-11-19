"""Harvest device templates and learn port-naming rules from real .pkt saves.

Outputs (under fixtures/harvest/):
  templates/<model>.xml   - first clean device of each model (ElementTree XML)
  summary.json            - per-file device/link/version statistics
  port_names.json         - learned (model, family) -> numbering scheme
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ptforge.ptcrypto import ptfile  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "harvest"
TEMPLATES = OUT / "templates"
SAVE_DIRS = [
    Path(r"D:\Cisco Packet Tracer 8.1.1\saves"),
    Path(r"C:\Users\李响\Cisco Packet Tracer 8.1.1\saves"),
]

# map XML port type -> IOS interface family name
FAMILY = {
    "eCopperFastEthernet": "FastEthernet",
    "eCopperGigabitEthernet": "GigabitEthernet",
    "eCopperTenGigabitEthernet": "TenGigabitEthernet",
    "eCopperEthernet": "Ethernet",
    "eSerial": "Serial",
    "eFiberFastEthernet": "FastEthernet",
    "eFiberGigabitEthernet": "GigabitEthernet",
    "eDot11abg": "Wireless",
    "eWireless": "Wireless",
}


def port_family(port_type: str) -> str | None:
    return FAMILY.get(port_type)


def iter_ports(device: ET.Element):
    """Yield PORT elements in document order (DFS)."""
    yield from device.iter("PORT")


def device_ref_id(device: ET.Element) -> str | None:
    return device.findtext("SAVE_REF_ID")


def parse_file(path: Path) -> dict | None:
    try:
        xml = ptfile.decode_container(path.read_bytes())
    except Exception as exc:  # noqa: BLE001 - harvest is best effort
        return {"file": str(path), "error": f"{type(exc).__name__}: {exc}"}
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        return {"file": str(path), "error": f"xml: {exc}"}

    info = {
        "file": str(path),
        "version": root.findtext("VERSION"),
        "devices": [],
        "links": [],
    }
    for dev in root.findall(".//DEVICES/DEVICE"):
        eng = dev.find("ENGINE")
        if eng is None:
            continue
        typ = eng.find("TYPE")
        model = typ.get("model") if typ is not None else None
        ports = []
        for port in iter_ports(dev):
            ptype = port.findtext("TYPE")
            ports.append({"type": ptype, "family": port_family(ptype or "")})
        info["devices"].append({
            "ref": device_ref_id(eng),
            "name": eng.findtext("NAME"),
            "model": model,
            "custom_model": typ.get("customModel") if typ is not None else None,
            "ports": ports,
            "power": eng.findtext("POWER"),
        })

    for link in root.findall(".//LINKS/LINK"):
        cable = link.find("CABLE")
        if cable is None:
            continue
        info["links"].append({
            "from": cable.findtext("FROM"),
            "from_port": cable.findtext("PORT"),
            "to": cable.findtext("TO"),
            "to_port": cable.findtext("PORT"),
            "cable": cable.findtext("TYPE"),
            "link_type": link.findtext("TYPE"),
        })
    return info


def learn_port_names(infos: list[dict]) -> dict:
    """Learn (model, family) -> start index by matching link port names."""
    observed: dict[tuple[str, str], set[int]] = {}
    for info in infos:
        if "error" in info:
            continue
        by_ref: dict[str, dict] = {}
        counters: dict[str, dict[str, int]] = {}
        for dev in info["devices"]:
            ref = dev["ref"]
            if ref:
                by_ref[ref] = dev
            # per-device family counters in DFS order
            counts: dict[str, int] = {}
            dev["port_index"] = []
            for port in dev["ports"]:
                fam = port["family"]
                if not fam:
                    dev["port_index"].append(None)
                    continue
                idx = counts.get(fam, 0)
                counts[fam] = idx + 1
                dev["port_index"].append(idx)
            counters[ref or ""] = counts

        for link in info["links"]:
            for side, port_key in (("from", "from_port"), ("to", "to_port")):
                ref = link[side]
                name = link[port_key] or ""
                dev = by_ref.get(ref or "")
                if dev is None:
                    continue
                m = re.match(r"^([A-Za-z\-]+)((?:[\d/]+))$", name)
                if not m:
                    continue
                fam = m.group(1)
                tail = m.group(2)
                model = dev["model"] or "?"
                # ordinal in name; for Serial0/0/0 we only use the last component
                parts = [p for p in tail.split("/") if p]
                if not parts:
                    continue
                ordinal = int(parts[-1])
                observed.setdefault((model, fam), set()).add(ordinal)

    # derive start index: min observed ordinal if names end with 0 for routers
    rules: dict[str, dict] = {}
    for (model, fam), ordinals in sorted(observed.items()):
        start = 0 if 0 in ordinals else min(ordinals)
        rules.setdefault(model, {})[fam] = {"start": start, "observed": sorted(ordinals)[:6]}
    return rules


def main() -> int:
    TEMPLATES.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for d in SAVE_DIRS:
        if d.exists():
            files.extend(sorted(d.rglob("*.pkt")))
    print(f"scanning {len(files)} files")
    infos = []
    for i, path in enumerate(files, 1):
        info = parse_file(path)
        if info:
            infos.append(info)
        if i % 25 == 0:
            print(f"  {i}/{len(files)}")
    (OUT / "summary.json").write_text(json.dumps(infos, indent=1), encoding="utf-8")

    rules = learn_port_names(infos)
    (OUT / "port_names.json").write_text(json.dumps(rules, indent=1, sort_keys=True), encoding="utf-8")
    print(f"learned naming rules for {len(rules)} models")

    # templates: one per model, first device without extra modules
    seen: set[str] = set()
    for info in infos:
        if "error" in info:
            continue
        pass
    # re-walk raw XML to keep device elements
    for path in files:
        try:
            xml = ptfile.decode_container(path.read_bytes())
            root = ET.fromstring(xml)
        except Exception:  # noqa: BLE001
            continue
        for dev in root.findall(".//DEVICES/DEVICE"):
            eng = dev.find("ENGINE")
            if eng is None:
                continue
            typ = eng.find("TYPE")
            model = (typ.get("model") if typ is not None else None) or "unknown"
            if model in seen:
                continue
            if (eng.findtext("POWER") or "true") != "true":
                continue
            seen.add(model)
            ET.ElementTree(dev).write(TEMPLATES / f"{model}.xml", encoding="utf-8", xml_declaration=False)
        if len(seen) >= 80:
            break
    print(f"templates: {len(seen)} -> {TEMPLATES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

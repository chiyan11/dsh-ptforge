"""Experiments to isolate why injected devices corrupt the file."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ptforge.ptcrypto import ptfile  # noqa: E402

FIX = ROOT / "fixtures"
OUT = FIX / "exp"
OUT.mkdir(exist_ok=True)


def load(name: str) -> ET.Element:
    path = FIX / name
    if path.suffix == ".xml":
        return ET.fromstring(path.read_bytes())
    return ET.fromstring(ptfile.decode_container(path.read_bytes()))


def wire(root: ET.Element, out: Path) -> None:
    xml = ET.tostring(root, encoding="utf-8")
    out.write_bytes(ptfile.encode_container(xml))
    print(f"{out.name}: {out.stat().st_size} B")


def main() -> int:
    base = load("decoded/8.3.xml")
    devices = base.find("NETWORK/DEVICES")
    links = base.find("NETWORK/LINKS")
    print("8.3 devices:", len(devices), "links:", len(links))

    # E1: keep only the first device, drop links
    e1 = ET.fromstring(ET.tostring(base))
    d1 = e1.find("NETWORK/DEVICES")
    keep = list(d1)[0]
    keep_name = keep.find("ENGINE/NAME").text
    for child in list(d1):
        if child is not keep:
            d1.remove(child)
    e1.find("NETWORK/LINKS").clear()
    wire(e1, OUT / "e1_one_device_from_8_3.pkt")
    print("  kept device:", keep_name)

    # E2: skeleton + verbatim device element from 8.3
    skel = load("decoded/empty81.xml")
    e2 = ET.fromstring(ET.tostring(skel))
    reg = e2.find("NETWORK/DEVICES")
    for child in reg:
        reg.remove(child)
    clone = ET.fromstring(ET.tostring(keep))
    clone.find("ENGINE/SAVE_REF_ID").text = "save-ref-id:123456789012345678"
    clone.find("ENGINE/COORD_SETTINGS/X_COORD").text = "300.00"
    clone.find("ENGINE/COORD_SETTINGS/Y_COORD").text = "300.00"
    reg.append(clone)
    wire(e2, OUT / "e2_skeleton_plus_verbatim_device.pkt")

    # E3: skeleton + device with name/ref patched by same code path as builder
    from ptforge.catalog import template

    tpl = template("PC-PT")
    print("template children:", [c.tag for c in tpl])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

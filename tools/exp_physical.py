"""Probe which WORKSPACE/PHYSICAL encoding PT 8.1.1 accepts."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ptforge.catalog import skeleton_tree, template  # noqa: E402
from ptforge.ptcrypto import ptfile  # noqa: E402

OUT = ROOT / "fixtures" / "exp"
OUT.mkdir(parents=True, exist_ok=True)

PHYSICAL_VARIANTS = {
    "f0_no_workspace": None,
    "f1_empty": "",
    "f2_guids_from_8_3": (
        "{3f6ac7c0-3adb-4b56-899a-98bc4c443e5d},{940cf66a-f66e-4b27-b348-eb13468c00a1},"
        "{3a5fb8e3-253c-4e29-be88-d4f9f66bbd3c},{a2d5ef1a-8602-4cea-ac17-c942f3e2c8da}"
    ),
    "f3_closet_names": "Intercity,Home City,Corporate Office,Main Wiring Closet",
}


def set_text(parent: ET.Element, tag: str, text: str) -> None:
    el = parent.find(tag)
    if el is None:
        el = ET.SubElement(parent, tag)
    el.text = text


def build(kind: str, physical: str | None) -> None:
    root = ET.fromstring(ET.tostring(skeleton_tree().getroot()))
    reg = root.find("NETWORK/DEVICES")
    for child in list(reg):
        reg.remove(child)

    dev = template("PC-PT")
    eng = dev.find("ENGINE")
    set_text(eng, "NAME", "PC0")
    set_text(eng, "SAVE_REF_ID", "save-ref-id:424242424242424242")
    set_text(eng.find("COORD_SETTINGS"), "X_COORD", "300.00")
    set_text(eng.find("COORD_SETTINGS"), "Y_COORD", "300.00")

    ws = dev.find("WORKSPACE")
    if ws is not None:
        ph = ws.find("PHYSICAL")
        if physical is None:
            ws.remove(ph)
        elif physical == "":
            ph.text = ""
        else:
            ph.text = physical
    reg.append(dev)

    out = OUT / f"{kind}.pkt"
    out.write_bytes(ptfile.encode_container(ET.tostring(root, encoding="utf-8")))
    print(f"{out.name}: {out.stat().st_size} B")


if __name__ == "__main__":
    for kind, phys in PHYSICAL_VARIANTS.items():
        build(kind, phys)

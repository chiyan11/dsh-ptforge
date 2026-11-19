"""Inspect the XML structure of a decoded .pkt file."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lxml import etree  # noqa: E402

from ptforge.ptcrypto import ptfile  # noqa: E402


def dump(element, *, max_bytes: int = 1200) -> str:
    raw = etree.tostring(element, pretty_print=True, encoding="unicode")
    if len(raw) > max_bytes:
        raw = raw[:max_bytes] + "\n... [truncated]\n"
    return raw


def main(path: Path) -> int:
    xml = ptfile.decode_container(path.read_bytes())
    print(f"{path.name}: {len(xml)} B xml")
    root = etree.fromstring(xml)
    print("root:", root.tag)
    for child in root:
        n = len(child)
        print(f"  <{child.tag}> children={n}")
    version = root.findtext("VERSION")
    print("VERSION:", version)

    devices = root.findall(".//DEVICES/DEVICE")
    print(f"\ndevices: {len(devices)}")
    for dev in devices[:3]:
        print(dump(dev, max_bytes=900))

    # print a compact table of engine/type + name + position for all devices
    print("name | model | x,y | power")
    for dev in devices:
        name = dev.findtext("ENGINE/NAME")
        model = dev.find("ENGINE/TYPE")
        attrs = dict(model.attrib) if model is not None else {}
        x = dev.findtext("ENGINE/X")
        y = dev.findtext("ENGINE/Y")
        print(f"  {name!r} | {attrs.get('model')!r} | {x},{y}")

    links = root.findall(".//LINKS/LINK")
    print(f"\nlinks: {len(links)}")
    for link in links[:2]:
        print(dump(link, max_bytes=1500))
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"D:\Cisco Packet Tracer 8.1.1\saves\8.3.pkt"
    )
    raise SystemExit(main(target))

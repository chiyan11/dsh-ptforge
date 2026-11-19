"""Dump decoded PT topology data into fixtures/ for offline study."""

from __future__ import annotations

import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lxml import etree  # noqa: E402

from ptforge.ptcrypto import ptfile  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "decoded"


def main(path: Path) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    xml = ptfile.decode_container(path.read_bytes())
    (OUT / f"{path.stem}.xml").write_bytes(xml)
    root = etree.fromstring(xml)

    # tag frequency map
    counts: collections.Counter[str] = collections.Counter()
    for el in root.iter():
        if isinstance(el.tag, str):
            counts[el.tag] += 1
    with (OUT / "tags.txt").open("w", encoding="utf-8") as fh:
        for tag, n in sorted(counts.items()):
            fh.write(f"{n:6d}  {tag}\n")

    network = root.find("NETWORK")
    lines = [f"NETWORK children: {[c.tag for c in network]}"]
    for child in network:
        lines.append(f"  <{child.tag}> children={len(child)}")
    links = root.findall(".//LINK")
    lines.append(f"total LINK elements: {len(links)}")
    if links:
        (OUT / "link_sample.xml").write_bytes(
            etree.tostring(links[0], pretty_print=True, encoding="utf-8")
        )
    (OUT / "network_index.txt").write_text("\n".join(lines), encoding="utf-8")

    # per-device child layout + coords
    rows = []
    for dev in root.findall(".//DEVICES/DEVICE"):
        eng = dev.find("ENGINE")
        name = eng.findtext("NAME")
        typ = eng.find("TYPE")
        model = typ.get("model") if typ is not None else None
        coord = eng.find("COORD_SETTINGS")
        xy = (coord.findtext("X_COORD"), coord.findtext("Y_COORD")) if coord is not None else (None, None)
        children = [c.tag for c in eng]
        rows.append(f"{name}\t{model}\t{xy[0]},{xy[1]}\t{dev.tag}:{children}")
    (OUT / "devices.txt").write_text("\n".join(rows), encoding="utf-8")

    # full XML of the first switch and first pc for schema study
    for dev in root.findall(".//DEVICES/DEVICE"):
        eng = dev.find("ENGINE")
        model = eng.find("TYPE").get("model")
        if model == "2960-24TT":
            (OUT / "device_switch.xml").write_bytes(
                etree.tostring(dev, pretty_print=True, encoding="utf-8"))
            break
    for dev in root.findall(".//DEVICES/DEVICE"):
        eng = dev.find("ENGINE")
        model = eng.find("TYPE").get("model")
        if model in ("PC-PT", "PC"):
            (OUT / "device_pc.xml").write_bytes(
                etree.tostring(dev, pretty_print=True, encoding="utf-8"))
            break

    print(f"wrote analysis to {OUT}")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"D:\Cisco Packet Tracer 8.1.1\saves\8.3.pkt"
    )
    raise SystemExit(main(target))

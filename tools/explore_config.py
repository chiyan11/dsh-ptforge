"""Explore where IP addressing and CLI config live inside the XML."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
DEC = ROOT / "fixtures" / "decoded"


def path_of(root: ET.Element, target: ET.Element) -> str:
    parent = {child: p for p in root.iter() for child in p}
    parts = []
    node = target
    while node is not None:
        parts.append(node.tag)
        node = parent.get(node)
    return "/".join(reversed(parts))


def main() -> int:
    empty = ET.parse(DEC / "empty81.xml").getroot()
    print("empty81 root children:")
    for child in empty:
        print(f"  {child.tag}: children={len(child)}")

    full = ET.parse(DEC / "8.3.xml").getroot()

    # where do IPv4 addresses live?
    hits = []
    for el in full.iter():
        text = (el.text or "").strip()
        if text.startswith("192.168.") and len(hits) < 12:
            hits.append(f"{path_of(full, el)} = {text}")
    print("\nIPv4 strings:")
    print("\n".join("  " + h for h in hits))

    # how is a PC's config stored?
    for dev in full.findall(".//DEVICES/DEVICE"):
        eng = dev.find("ENGINE")
        if eng is None:
            continue
        name = eng.findtext("NAME") or ""
        if name in ("PC0", "Switch0", "Router0"):
            print(f"\n{name} ({eng.find('TYPE').get('model')}) relevant subtrees:")
            for tag in ("GATEWAY", "DHCP_CLIENT", "RUNNINGCONFIG", "STARTUPCONFIG", "VLANS", "SYS_NAME"):
                el = eng.find(tag)
                if el is None:
                    continue
                txt = ET.tostring(el, encoding="unicode")
                print(f"  <{tag}> len={len(txt)} head={txt[:220]!r}")

    # command log format (useful for replaying CLI)
    logs = full.findall("COMMAND_LOGS/*")
    print(f"\nCOMMAND_LOGS children={len(logs)}")
    for el in logs[:3]:
        print("  ", ET.tostring(el, encoding="unicode")[:300])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

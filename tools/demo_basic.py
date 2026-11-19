"""Build a minimal 2-PC + 1-switch lab to validate the generator."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ptforge.build import TopologyBuilder  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "demo_basic.pkt"


def main() -> int:
    b = TopologyBuilder()
    b.add_device("PC-PT", "PC0", 260, 180, ipv4=("192.168.10.10", "255.255.255.0", "192.168.10.1"))
    b.add_device("PC-PT", "PC1", 260, 420, ipv4=("192.168.10.11", "255.255.255.0", "192.168.10.1"))
    b.add_device("2960-24TT", "SW1", 520, 300, config=[
        "enable", "configure terminal", "hostname SW1", "exit", "exit",
    ])
    b.connect("PC0", "SW1", a_port="FastEthernet0", b_port="FastEthernet0/1")
    b.connect("PC1", "SW1", a_port="FastEthernet0", b_port="FastEthernet0/2")
    path = b.save(OUT)
    print(f"wrote {path} ({path.stat().st_size} B)")
    for dev in b.devices.values():
        print(f"  {dev.name} {dev.model} -> {dev.ref}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

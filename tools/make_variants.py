"""Generate incremental build variants for PT open-validation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ptforge.build import TopologyBuilder  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "variants"


def variant_a() -> None:
    b = TopologyBuilder()
    b.add_device("PC-PT", "PC0", 260, 180)
    b.save(OUT / "a_one_pc.pkt")


def variant_b() -> None:
    b = TopologyBuilder()
    b.add_device("PC-PT", "PC0", 260, 180)
    b.add_device("2960-24TT", "SW1", 520, 300)
    b.save(OUT / "b_pc_switch.pkt")


def variant_c() -> None:
    b = TopologyBuilder()
    b.add_device("PC-PT", "PC0", 260, 180)
    b.add_device("2960-24TT", "SW1", 520, 300)
    b.connect("PC0", "SW1", a_port="FastEthernet0", b_port="FastEthernet0/1")
    b.save(OUT / "c_one_link.pkt")


def variant_d() -> None:
    b = TopologyBuilder()
    b.add_device("PC-PT", "PC0", 260, 180)
    b.add_device("PC-PT", "PC1", 260, 420)
    b.add_device("2960-24TT", "SW1", 520, 300)
    b.connect("PC0", "SW1", a_port="FastEthernet0", b_port="FastEthernet0/1")
    b.connect("PC1", "SW1", a_port="FastEthernet0", b_port="FastEthernet0/2")
    b.save(OUT / "d_full.pkt")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    variant_a()
    variant_b()
    variant_c()
    variant_d()
    print("\n".join(str(p) for p in sorted(OUT.glob("*.pkt"))))

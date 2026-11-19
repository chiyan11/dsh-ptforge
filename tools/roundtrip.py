"""Round-trip a .pkt through decode -> encode and write the result."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ptforge.ptcrypto import ptfile  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main(src: Path) -> int:
    data = src.read_bytes()
    xml = ptfile.decode_container(data)
    out = ptfile.encode_container(xml)
    dst = ROOT / "fixtures" / f"reencoded_{src.name}"
    dst.write_bytes(out)
    print(f"{src} -> {dst}")
    print(f"source {len(data)} B -> reencoded {len(out)} B")
    # sanity: decode our own output again
    assert ptfile.decode_container(out) == xml, "round-trip mismatch after re-decode"
    print("re-decode matches original XML")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"D:\Cisco Packet Tracer 8.1.1\saves\8.3.pkt"
    )
    raise SystemExit(main(target))

"""Ad-hoc probe: try to decode every .pkt sample found in the PT install."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ptforge.ptcrypto import ptfile  # noqa: E402

SAVES = Path(r"D:\Cisco Packet Tracer 8.1.1\saves")


def main() -> int:
    samples = sorted(SAVES.rglob("*.pkt"))[:6]
    if not samples:
        print("no samples found")
        return 1
    ok = 0
    for path in samples:
        data = path.read_bytes()
        try:
            xml = ptfile.decode_container(data)
        except ptfile.PacketTracerFormatError as exc:
            print(f"FAIL {path.name} ({len(data)} B): {exc}")
            continue
        ok += 1
        print(f"OK   {path.name} ({len(data)} B) -> {len(xml)} B XML")
        print("     head:", xml[:200].decode("utf-8", "replace").replace("\n", " "))
        # round trip
        rebuilt = ptfile.encode_container(xml)
        print(f"     roundtrip identical: {rebuilt == data} ({len(rebuilt)} B)")
    print(f"\n{ok}/{len(samples)} decoded")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

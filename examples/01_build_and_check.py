"""Build a topology from JSON, then read it back and assert on it.

Run:  python examples/01_build_and_check.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ptforge import spec, state

HERE = Path(__file__).with_name("lab.json")
OUT_DIR = Path(__file__).with_name("out")


def main() -> int:
    data = json.loads(HERE.read_text(encoding="utf-8"))
    pkt = spec.build_from_spec(data, OUT_DIR / "branch.pkt")
    print(f"built {pkt} ({pkt.stat().st_size} bytes)")

    root = state.load(pkt)
    summary = state.describe(root)
    print(f"version {summary['version']}, {len(summary['devices'])} devices")
    for device in summary["devices"]:
        addresses = [
            f"{i['name']} {i['ip']}/{i['prefix']}" if i["ip"] else i["name"]
            for i in device["interfaces"]
        ]
        print(f"  {device['name']:<5} {device['kind']:<7} {', '.join(addresses)}")

    result = state.check(
        root,
        [
            {"device": "R1", "interface": "GigabitEthernet0/0", "ip": "10.10.0.254"},
            {"device": "PC1", "interface": "FastEthernet0", "ip": "10.10.0.11"},
            {"device": "PC2", "interface": "FastEthernet0", "ip": "10.10.0.12"},
        ],
    )
    for item in result["results"]:
        mark = "PASS" if item["ok"] else "FAIL"
        extra = "" if item["ok"] else f" -- {'; '.join(item['problems'])}"
        print(f"{mark} {item['device']} {item['expect']}{extra}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

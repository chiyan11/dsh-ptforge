"""Patch an existing topology instead of rebuilding it.

Run:  python examples/02_patch_and_state.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ptforge import patch, state

HERE = Path(__file__).with_name("out")


def main() -> int:
    source = HERE / "branch.pkt"
    if not source.exists():
        raise SystemExit("run examples/01_build_and_check.py first")

    target = HERE / "branch_patched.pkt"
    result = patch.patch_file(
        source,
        [
            {"op": "set_ipv4", "device": "PC1", "port": "FastEthernet0",
             "address": "10.10.0.21", "gateway": "10.10.0.254"},
            {"op": "rename", "device": "SW1", "name": "ACCESS-SW"},
            {"op": "set_config", "device": "R1", "append": True,
             "lines": ["interface GigabitEthernet0/1", "description unused"]},
        ],
        out=target,
    )
    print(f"patched -> {result['path']} ({result['bytes']} bytes)")
    for change in result["ops"]:
        print(f"  {change}")

    root = state.load(target)
    pc1 = state.device_state(root, "PC1")
    print("PC1 interfaces:", [(i["name"], i["ip"]) for i in pc1["interfaces"]])
    sw = state.device_state(root, "ACCESS-SW")
    print("switch hostname:", sw["hostname"])

    r1 = state.device_state(root, "R1")
    tail = r1["config_lines"][-4:]
    print("R1 config tail:", tail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build a lab, add canvas annotations, and produce report material.

Run:  python examples/03_report.py
"""

from __future__ import annotations

from pathlib import Path

from ptforge import edit, notes, report, spec

HERE = Path(__file__).with_name("out")


def main() -> int:
    data = {
        "name": "web_lab",
        "devices": [
            {"model": "2960-24TT", "name": "SW1", "config": ["hostname SW1"]},
            {"model": "Server-PT", "name": "WEB", "ipv4": "10.20.0.10/24"},
            {"model": "PC-PT", "name": "PC1", "ipv4": "10.20.0.20/24,10.20.0.10"},
        ],
        "links": [
            {"from": "PC1", "to": "SW1"},
            {"from": "WEB", "to": "SW1"},
        ],
    }
    pkt = spec.build_from_spec(data, HERE / "web_lab.pkt")

    root = edit.load(pkt)
    notes.add_note(root, "PC1 10.20.0.20 / Fa0", x=0, y=0, anchor_device="PC1", dy=-50)
    notes.add_note(root, "WEB 10.20.0.10 / Fa0", x=0, y=0, anchor_device="WEB", dy=-50)
    annotated = HERE / "web_lab_annotated.pkt"
    edit.save(root, annotated)
    print(f"annotated -> {annotated}")

    summary = report.build_report(
        annotated,
        HERE / "report",
        title="在线实验：静态页面访问",
        figures=[{"path": "figures/topology.png", "caption": "逻辑拓扑（标注了 IP 与端口）"}],
    )
    print(f"report   -> {summary['report']}")
    print(f"captions -> {summary['captions']}")
    print(
        f"{summary['devices']} devices, {summary['addresses']} addresses, "
        f"{summary['links']} links, {summary['figures']} figures"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

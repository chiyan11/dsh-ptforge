"""Turn a verified topology into report material.

Produces a ``figures/`` layout plus ``captions.json`` so a report generator
can drop the images and tables in without manual retyping.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from . import state
from .ptcrypto import ptfile

__all__ = ["build_report"]


def _address_table(devices: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for dev in devices:
        for iface in dev["interfaces"]:
            if not iface["ip"]:
                continue
            rows.append(
                {
                    "device": dev["name"],
                    "interface": iface["name"],
                    "address": f"{iface['ip']}/{iface['prefix']}"
                    if iface["prefix"] is not None
                    else iface["ip"],
                    "gateway": iface["gateway"] or "",
                }
            )
    return rows


def _link_table(root: ET.Element) -> list[dict]:
    ref_to_name: dict[str, str] = {}
    for dev in root.findall("NETWORK/DEVICES/DEVICE"):
        engine = dev.find("ENGINE")
        if engine is None:
            continue
        ref_to_name[engine.findtext("SAVE_REF_ID") or ""] = engine.findtext("NAME") or "?"
    rows: list[dict] = []
    for link in root.findall("NETWORK/LINKS/LINK"):
        cable = link.find("CABLE")
        if cable is None:
            continue
        ports = cable.findall("PORT")
        rows.append(
            {
                "from": ref_to_name.get(cable.findtext("FROM") or "", "?"),
                "from_port": ports[0].text if len(ports) > 0 else "",
                "to": ref_to_name.get(cable.findtext("TO") or "", "?"),
                "to_port": ports[1].text if len(ports) > 1 else "",
                "cable": cable.findtext("TYPE") or "",
            }
        )
    return rows


def build_report(
    pkt: str | Path,
    out_dir: str | Path,
    *,
    figures: list[dict] | None = None,
    title: str | None = None,
) -> dict:
    """Write ``captions.json`` and ``report.md`` next to the figures."""
    path = Path(pkt)
    root = ptfile.decode(str(path))
    described = state.describe(root)
    addresses = _address_table(described["devices"])
    links = _link_table(root)
    target = Path(out_dir)
    (target / "figures").mkdir(parents=True, exist_ok=True)
    figures = figures or []
    captions = {
        "title": title or path.stem,
        "source": str(path),
        "version": described["version"],
        "figures": figures,
        "tables": {
            "devices": [
                {
                    "device": dev["name"],
                    "kind": dev["kind"],
                    "model": dev["model"],
                    "interfaces": len(dev["interfaces"]),
                }
                for dev in described["devices"]
            ],
            "addresses": addresses,
            "links": links,
        },
    }
    (target / "captions.json").write_text(
        json.dumps(captions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (target / "report.md").write_text(_markdown(captions), encoding="utf-8")
    return {
        "dir": str(target),
        "captions": str(target / "captions.json"),
        "report": str(target / "report.md"),
        "devices": len(described["devices"]),
        "figures": len(figures),
        "addresses": len(addresses),
        "links": len(links),
    }


def _markdown(captions: dict) -> str:
    lines = [f"# {captions['title']}", "", f"来源文件：`{captions['source']}`", ""]
    lines += ["## 设备", "", "| 设备 | 类型 | 型号 | 接口数 |", "| --- | --- | --- | --- |"]
    for row in captions["tables"]["devices"]:
        lines.append(
            f"| {row['device']} | {row['kind'] or ''} | {row['model'] or ''} | {row['interfaces']} |"
        )
    lines += ["", "## 地址表", "", "| 设备 | 接口 | 地址 | 网关 |", "| --- | --- | --- | --- |"]
    for row in captions["tables"]["addresses"]:
        lines.append(
            f"| {row['device']} | {row['interface']} | {row['address']} | {row['gateway']} |"
        )
    lines += ["", "## 链路", "", "| 起点 | 端口 | 终点 | 端口 | 线型 |", "| --- | --- | --- | --- | --- |"]
    for row in captions["tables"]["links"]:
        lines.append(
            f"| {row['from']} | {row['from_port']} | {row['to']} | {row['to_port']} | {row['cable']} |"
        )
    if captions["figures"]:
        lines += ["", "## 图", ""]
        for figure in captions["figures"]:
            lines.append(f"![{figure.get('caption', '')}]({figure['path']})")
            lines.append("")
            lines.append(f"*{figure.get('caption', '')}*")
    lines.append("")
    return "\n".join(lines)

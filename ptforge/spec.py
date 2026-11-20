"""Declarative topology specifications: load, lay out, build."""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .build import TopologyBuilder
from . import catalog

GATEWAY_DEFAULTS: dict[str, str] = {
    "router": "GigabitEthernet0/0",
    "switch": "FastEthernet0/1",
}


class SpecError(ValueError):
    """Raised when a topology specification is malformed."""


def _prefix_to_mask(prefix: int) -> str:
    if not 0 <= prefix <= 32:
        raise SpecError(f"ipv4 prefix /{prefix} is out of range")
    return str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask)


def _parse_ipv4(value: Any, device: str) -> tuple[str, str, str] | None:
    """Accept the shapes an author is likely to write.

    ``"192.168.10.10/24,192.168.10.1"``, ``"192.168.10.10 255.255.255.0 192.168.10.1"``,
    ``["192.168.10.10", "255.255.255.0", "192.168.10.1"]`` and
    ``{"address": ..., "mask": ..., "gateway": ...}`` all normalise to
    ``(address, mask, gateway)``.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        address = value.get("address") or value.get("ip")
        mask = value.get("mask") or value.get("netmask")
        gateway = value.get("gateway") or ""
        if not address:
            raise SpecError(f"{device}: ipv4 object needs 'address'")
        if mask is None and "/" in str(address):
            address, _, tail = str(address).partition("/")
            mask = _prefix_to_mask(int(tail))
        if mask is None:
            raise SpecError(f"{device}: ipv4 object needs 'mask' (or address with /prefix)")
        return str(address), str(mask), str(gateway)
    if isinstance(value, str):
        text = value.replace(",", " ").replace(";", " ")
        if "/" in text.split()[0]:
            head, _, tail = text.partition(" ")
            address, _, prefix_text = head.partition("/")
            prefix = int(prefix_text)
            gateway = tail.strip()
            return address, _prefix_to_mask(prefix), gateway
        parts = text.split()
        if len(parts) == 2:
            return parts[0], parts[1], ""
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]
        raise SpecError(
            f"{device}: ipv4 string {value!r} must be 'address mask [gateway]' "
            "or 'address/prefix [gateway]'"
        )
    if isinstance(value, (list, tuple)):
        if len(value) == 1:
            # Allow ["192.168.10.1/24"] and ["192.168.10.1 255.255.255.0 gw"]:
            # a one-item list is just the string form spelled inside brackets.
            return _parse_ipv4(value[0], device)
        if len(value) == 2:
            head = str(value[0])
            if "/" in head:
                # ["10.0.0.1/24", "10.0.0.254"] means address + gateway.
                return _parse_ipv4(f"{head} {value[1]}", device)
            return head, str(value[1]), ""
        if len(value) == 3:
            return str(value[0]), str(value[1]), str(value[2])
        raise SpecError(f"{device}: ipv4 list needs 1, 2 or 3 items, got {len(value)}")
    raise SpecError(f"{device}: unsupported ipv4 value {value!r}")


@dataclass
class DeviceSpec:
    name: str
    model: str
    x: float | None = None
    y: float | None = None
    config: list[str] = field(default_factory=list)
    start_config: list[str] = field(default_factory=list)
    ipv4: tuple[str, str, str] | None = None
    port: str | None = None
    physical: str | None = None


@dataclass
class LinkSpec:
    source: str
    target: str
    source_port: str | None = None
    target_port: str | None = None
    cable: str = "straight"


def load_spec(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    raise SpecError(f"unsupported spec format {path.suffix!r}; use .json")


def parse_spec(data: dict[str, Any]) -> tuple[list[DeviceSpec], list[LinkSpec]]:
    devices_raw = data.get("devices")
    if not isinstance(devices_raw, list) or not devices_raw:
        raise SpecError("spec needs a non-empty 'devices' list")
    devices: list[DeviceSpec] = []
    for entry in devices_raw:
        if not isinstance(entry, dict):
            raise SpecError(f"device entry must be an object: {entry!r}")
        model = entry.get("model")
        if not model:
            raise SpecError(f"device entry needs 'model': {entry!r}")
        try:
            catalog.template(model)
        except catalog.CatalogError as exc:
            raise SpecError(f"unknown model {model!r}") from exc
        ipv4 = _parse_ipv4(entry.get("ipv4"), entry.get("name") or model)
        devices.append(
            DeviceSpec(
                name=str(entry.get("name") or model),
                model=str(model),
                x=float(entry["x"]) if entry.get("x") is not None else None,
                y=float(entry["y"]) if entry.get("y") is not None else None,
                config=[str(line) for line in entry.get("config", [])],
                start_config=[str(line) for line in entry.get("startConfig", [])],
                ipv4=ipv4,  # type: ignore[arg-type]
                port=entry.get("port"),
                physical=entry.get("physical"),
            )
        )
    links: list[LinkSpec] = []
    for entry in data.get("links", []):
        if not isinstance(entry, dict):
            raise SpecError(f"link entry must be an object: {entry!r}")
        source = entry.get("from") or entry.get("source")
        target = entry.get("to") or entry.get("target")
        if not source or not target:
            raise SpecError(f"link needs 'from' and 'to': {entry!r}")
        links.append(
            LinkSpec(
                source=str(source),
                target=str(target),
                source_port=entry.get("fromPort") or entry.get("sourcePort"),
                target_port=entry.get("toPort") or entry.get("targetPort"),
                cable=str(entry.get("cable", "straight")),
            )
        )
    seen: set[str] = set()
    for dev in devices:
        if dev.name in seen:
            raise SpecError(f"duplicate device name {dev.name!r}")
        seen.add(dev.name)
    for link in links:
        for endpoint in (link.source, link.target):
            if endpoint not in seen:
                raise SpecError(f"link references unknown device {endpoint!r}")
    return devices, links


def auto_layout(devices: list[DeviceSpec], *, spacing: float = 190.0) -> None:
    """Assign canvas positions for devices that did not specify one.

    Routers go on the first row, switches on the second, everything else on the
    following rows, centred per row.  Explicit coordinates are preserved.
    """
    pending = [d for d in devices if d.x is None or d.y is None]
    if not pending:
        return
    rows: list[list[DeviceSpec]] = [[], [], []]
    for dev in pending:
        model = dev.model.upper()
        if model.startswith(("28", "19", "18", "ISR", "819", "829", "ROUTER")):
            rows[0].append(dev)
        elif model.startswith(("29", "35", "36", "SWITCH")):
            rows[1].append(dev)
        else:
            rows[2].append(dev)
    top = 160.0
    for row_index, row in enumerate(rows):
        if not row:
            continue
        width = (len(row) - 1) * spacing
        start_x = 320.0 - width / 2
        for i, dev in enumerate(row):
            dev.x = start_x + i * spacing if dev.x is None else dev.x
            dev.y = top + row_index * spacing if dev.y is None else dev.y


def build_from_spec(data: dict[str, Any], out_path: str | Path) -> Path:
    devices, links = parse_spec(data)
    auto_layout(devices)
    builder = TopologyBuilder()
    for dev in devices:
        kwargs: dict[str, Any] = {}
        if dev.config:
            kwargs["config"] = dev.config
        if dev.start_config:
            kwargs["start_config"] = dev.start_config
        if dev.ipv4:
            kwargs["ipv4"] = dev.ipv4
        if dev.port:
            kwargs["port"] = dev.port
        if dev.physical is not None:
            kwargs["physical"] = dev.physical
        builder.add_device(
            dev.model,
            dev.name,
            dev.x or 0.0,
            dev.y or 0.0,
            **kwargs,
        )
    for link in links:
        builder.connect(
            link.source,
            link.target,
            a_port=link.source_port,
            b_port=link.target_port,
            cable=link.cable,
        )
    return builder.save(out_path)

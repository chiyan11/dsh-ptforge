"""Structured, assertable state read back from a ``.pkt`` file.

Packet Tracer only stores configuration, not live counters, so this module
reports what the file can prove: interface addressing, static routes, NAT
statements, ACLs and switch-port settings.  Everything is derived from the
device's ``RUNNINGCONFIG`` plus the ``PORT`` elements, which Packet Tracer
itself rewrites after it boots a device.
"""

from __future__ import annotations

import ipaddress
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from . import catalog, edit
from .ptcrypto import ptfile

__all__ = [
    "StateError",
    "load",
    "describe",
    "device_state",
    "check",
]

_INTERFACE = re.compile(r"^interface\s+(\S+)")
_STATIC_ROUTE = re.compile(r"^ip route\s+(\S+)\s+(\S+)\s+(\S+)")
_ACCESS_VLAN = re.compile(r"^switchport access vlan\s+(\d+)")
_TRUNK_VLAN = re.compile(r"^switchport trunk allowed vlan\s+(.+)$")


class StateError(RuntimeError):
    """Raised when a requested device or interface cannot be found."""


def load(path: str | Path) -> ET.Element:
    return ptfile.decode(str(path))


def _sections(lines: list[str]) -> dict[str, list[str]]:
    """Split an IOS config into ``name -> body`` blocks."""
    sections: dict[str, list[str]] = {}
    current = "GLOBAL"
    sections[current] = []
    for raw in lines:
        line = raw.rstrip()
        match = _INTERFACE.match(line)
        if match:
            current = match.group(1)
            sections.setdefault(current, [])
            continue
        if line and not line[0].isspace() and not line.startswith("!"):
            current = "GLOBAL"
        sections.setdefault(current, []).append(line.strip())
    return sections


def _mask_prefix(mask: str | None) -> int | None:
    if not mask:
        return None
    try:
        return ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
    except ValueError:
        return None


def _interface_state(name: str, body: list[str], port_el: ET.Element | None) -> dict:
    state = {
        "name": name,
        "ip": None,
        "mask": None,
        "prefix": None,
        "gateway": None,
        "shutdown": False,
        "description": None,
        "switchport_mode": None,
        "access_vlan": None,
        "trunk_vlans": None,
    }
    for line in body:
        if line.startswith("ip address "):
            parts = line.split()
            if len(parts) >= 4:
                state["ip"], state["mask"] = parts[2], parts[3]
                state["prefix"] = _mask_prefix(state["mask"])
        elif line == "shutdown":
            state["shutdown"] = True
        elif line.startswith("description "):
            state["description"] = line[len("description ") :]
        elif line.startswith("switchport mode "):
            state["switchport_mode"] = line.split()[-1]
        else:
            match = _ACCESS_VLAN.match(line)
            if match:
                state["access_vlan"] = int(match.group(1))
            match = _TRUNK_VLAN.match(line)
            if match:
                state["trunk_vlans"] = match.group(1)
    if port_el is not None:
        ip = port_el.findtext("IP")
        if ip:
            state["ip"] = ip
            state["mask"] = port_el.findtext("SUBNET")
            state["prefix"] = _mask_prefix(state["mask"])
        gateway = port_el.findtext("PORT_GATEWAY")
        if gateway:
            state["gateway"] = gateway
    return state


def _find_engine(dev: ET.Element) -> ET.Element | None:
    return dev.find("ENGINE")


def _iter_devices(root: ET.Element):
    for dev in root.findall("NETWORK/DEVICES/DEVICE"):
        engine = _find_engine(dev)
        if engine is not None:
            yield dev, engine


def device_state(root: ET.Element, name: str) -> dict:
    """Return the configured state of one device."""
    lowered = name.lower()
    for dev, engine in _iter_devices(root):
        if (engine.findtext("NAME") or "").lower() != lowered:
            continue
        lines = edit.config_lines(dev)
        sections = _sections(lines)
        names = catalog.port_names(dev)
        ports = catalog.ports(dev)
        interfaces = []
        for index, port_el in enumerate(ports):
            port_name = names[index] if index < len(names) else None
            if not port_name:
                continue
            interfaces.append(
                _interface_state(port_name, sections.get(port_name, []), port_el)
            )
        # Interfaces configured but absent from the port tree (e.g. Vlan1,
        # loopbacks) still deserve a row.
        seen = {item["name"] for item in interfaces}
        for section, body in sections.items():
            if section in seen or section == "GLOBAL":
                continue
            if any(_INTERFACE.match(line) for line in [f"interface {section}"]):
                interfaces.append(_interface_state(section, body, None))
        routes = []
        nat = []
        acls: dict[str, list[str]] = {}
        for line in lines:
            match = _STATIC_ROUTE.match(line)
            if match:
                routes.append(
                    {
                        "network": match.group(1),
                        "mask": match.group(2),
                        "cidr": _cidr(match.group(1), match.group(2)),
                        "next_hop": match.group(3),
                    }
                )
            if line.startswith("ip nat "):
                nat.append(line)
            if line.startswith("access-list "):
                acls.setdefault(line.split()[1], []).append(line)
        type_el = engine.find("TYPE")
        return {
            "name": engine.findtext("NAME"),
            "kind": type_el.text if type_el is not None else None,
            "model": (type_el.get("model") if type_el is not None else None),
            "hostname": _hostname(lines),
            "interfaces": interfaces,
            "static_routes": routes,
            "nat": nat,
            "acls": acls,
            "config_lines": lines,
        }
    available = ", ".join(e.findtext("NAME") or "?" for _, e in _iter_devices(root))
    raise StateError(f"device {name!r} not found (have: {available})")


def _hostname(lines: list[str]) -> str | None:
    for line in reversed(lines):
        if line.startswith("hostname "):
            return line.split(None, 1)[1]
    return None


def _cidr(network: str, mask: str) -> str | None:
    try:
        return str(ipaddress.IPv4Network(f"{network}/{mask}", strict=False))
    except ValueError:
        return None


def describe(root: ET.Element) -> dict:
    return {
        "version": root.findtext("VERSION"),
        "devices": [
            device_state(root, engine.findtext("NAME") or "")
            for _, engine in _iter_devices(root)
        ],
    }


def check(root: ET.Element, expectations: list[dict]) -> dict:
    """Evaluate simple expectations and report a line-level diff.

    ``expectations`` items::

        {"device": "R1", "route": "172.18.20.0/24"}
        {"device": "R1", "interface": "Gi0/0", "ip": "192.168.10.1"}
        {"device": "SW1", "interface": "Fa0/1", "access_vlan": 10}
        {"device": "R1", "nat": "inside"}
        {"device": "R1", "config_contains": "ip nat inside"}
    """
    results = []
    for expect in expectations:
        name = expect.get("device", "")
        state = device_state(root, name)
        problems: list[str] = []
        evidence: list[str] = []
        if "route" in expect:
            wanted = expect["route"]
            found = [r["cidr"] for r in state["static_routes"]]
            if wanted in found:
                evidence.append(f"route {wanted} present")
            else:
                problems.append(f"route {wanted} missing (have: {found or 'none'})")
        if "interface" in expect:
            iface = next(
                (i for i in state["interfaces"] if i["name"].lower() == expect["interface"].lower()),
                None,
            )
            if iface is None:
                problems.append(f"interface {expect['interface']} missing")
            else:
                if "ip" in expect and iface["ip"] != expect["ip"]:
                    problems.append(
                        f"{iface['name']} ip {iface['ip']} != {expect['ip']}"
                    )
                if "access_vlan" in expect and iface["access_vlan"] != expect["access_vlan"]:
                    problems.append(
                        f"{iface['name']} access vlan {iface['access_vlan']}"
                        f" != {expect['access_vlan']}"
                    )
                if not problems:
                    evidence.append(f"{iface['name']} matches")
        if "nat" in expect:
            hint = expect["nat"]
            hits = [line for line in state["nat"] if hint in line]
            if hits:
                evidence.extend(hits)
            else:
                problems.append(f"no 'ip nat' line containing {hint!r}")
        if "config_contains" in expect:
            needle = expect["config_contains"]
            if any(needle in line for line in state["config_lines"]):
                evidence.append(f"config contains {needle!r}")
            else:
                problems.append(f"config lacks {needle!r}")
        results.append(
            {
                "device": state["name"],
                "expect": expect,
                "ok": not problems,
                "evidence": evidence,
                "problems": problems,
            }
        )
    return {
        "ok": all(item["ok"] for item in results),
        "results": results,
    }

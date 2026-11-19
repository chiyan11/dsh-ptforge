"""Edit an existing .pkt: device config, addresses and names.

All helpers operate on a decoded document tree (``xml.etree.ElementTree``)
and keep PT's serialisation rules intact: the running configuration is a plain
list of ``<LINE>`` children under ``ENGINE/RUNNINGCONFIG`` and interface
addresses live on the ``PORT`` nodes.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from . import catalog
from .build import _set_text
from .ptcrypto import ptfile

#: IOS blocks that own their following (indented) lines.
_SECTION_RE = re.compile(r"^(?:interface|vlan|router|line)\s", re.IGNORECASE)


class EditError(RuntimeError):
    """The requested device, port or interface does not exist."""


def load(path: str | Path) -> ET.Element:
    """Decode a ``.pkt`` into its XML root element."""
    return ptfile.decode(str(path))


def save(tree: ET.ElementTree | ET.Element, path: str | Path) -> Path:
    root = tree.getroot() if isinstance(tree, ET.ElementTree) else tree
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(ptfile.encode_container(ET.tostring(root, encoding="utf-8")))
    return out


def devices(root: ET.Element) -> dict[str, ET.Element]:
    """Map device name -> DEVICE element."""
    found: dict[str, ET.Element] = {}
    for dev in root.findall("NETWORK/DEVICES/DEVICE"):
        eng = dev.find("ENGINE")
        name = eng.findtext("NAME") if eng is not None else None
        if name:
            found[name] = dev
    return found


def device(root: ET.Element, name: str) -> ET.Element:
    for dev_name, dev in devices(root).items():
        if dev_name.casefold() == name.casefold():
            return dev
    known = ", ".join(sorted(devices(root)))
    raise EditError(f"no device named {name!r}; devices: {known}")


def config_lines(dev: ET.Element, tag: str = "RUNNINGCONFIG") -> list[str]:
    eng = dev.find("ENGINE")
    if eng is None:
        return []
    block = eng.find(tag)
    if block is None:
        return []
    return [line.text or "" for line in block.findall("LINE")]


def _split_sections(lines: list[str]) -> list[list[str]]:
    """Group lines into ``[prelude, section, section, ...]`` by IOS headers."""
    groups: list[list[str]] = [[]]
    for line in lines:
        if _SECTION_RE.match(line):
            groups.append([line])
        else:
            groups[-1].append(line)
    return [group for group in groups if group]


def _section_key(lines: list[str]) -> str | None:
    return lines[0].strip().casefold() if _SECTION_RE.match(lines[0]) else None


def merge_lines(existing: list[str], extra: list[str]) -> list[str]:
    """Merge CLI lines, replacing whole sections that already exist.

    A section header (``interface``, ``vlan``, ``router``, ``line``) matches by
    its exact text, so re-applying an interface block updates it in place
    instead of appending a duplicate that Packet Tracer would reject.
    """
    body = [line for line in existing if line.strip() != "end"]
    groups = _split_sections(body)
    index: dict[str, int] = {
        key: position
        for position, group in enumerate(groups)
        if (key := _section_key(group)) is not None
    }
    for group in _split_sections([line for line in extra if line.strip() != "end"]):
        key = _section_key(group)
        if key is not None and key in index:
            groups[index[key]] = group
        else:
            groups.append(group)
    merged: list[str] = []
    for group in groups:
        merged.extend(group)
    if not merged or merged[-1].strip() != "end":
        merged.append("end")
    return merged


def set_config(
    dev: ET.Element,
    lines: list[str],
    *,
    tag: str = "RUNNINGCONFIG",
    replace: bool = True,
) -> list[str]:
    """Write CLI lines, replacing the config or merging it section-wise."""
    eng = dev.find("ENGINE")
    if eng is None:
        raise EditError("device has no ENGINE block")
    block = eng.find(tag)
    if block is None:
        block = ET.SubElement(eng, tag)
    current = [line.text or "" for line in block.findall("LINE")]
    incoming = [line for line in lines if line != ""]
    if replace or not current:
        merged = incoming
        if merged and merged[-1].strip() != "end":
            merged = [*merged, "end"]
    else:
        merged = merge_lines(current, incoming)
    for child in list(block):
        block.remove(child)
    for line in merged:
        line_el = ET.SubElement(block, "LINE")
        line_el.text = line
    return merged


def set_ipv4(
    dev: ET.Element,
    port: str,
    address: str,
    mask: str = "255.255.255.0",
    gateway: str | None = None,
) -> None:
    """Set a static IPv4 address on an end device's interface."""
    ports = catalog.ports(dev)
    idx = catalog.port_index(dev, port)
    if idx is None:
        names = ", ".join(n for n in catalog.port_names(dev) if n)
        raise EditError(f"{catalog.model_of(dev)}: no interface {port!r}; available: {names}")
    port_el = ports[idx]
    _set_text(port_el, "IP", address)
    _set_text(port_el, "SUBNET", mask)
    _set_text(port_el, "PORT_DHCP_ENABLE", "false")
    if gateway:
        _set_text(port_el, "PORT_GATEWAY", gateway)
        eng = catalog.engine(dev)
        _set_text(eng, "GATEWAY", gateway)
        dhcp = eng.find("DHCP_CLIENT")
        if dhcp is not None:
            _set_text(dhcp, "ENABLED", "false")


def rename(dev: ET.Element, name: str) -> None:
    eng = catalog.engine(dev)
    name_el = eng.find("NAME")
    if name_el is None:
        name_el = ET.SubElement(eng, "NAME")
    name_el.text = name
    name_el.set("translate", "true")
    _set_text(eng, "SYS_NAME", name)
    # Keep the IOS prompt in step with the label, otherwise `show run` and the
    # canvas disagree after a rename.
    lines = config_lines(dev)
    if any(line.startswith("hostname ") for line in lines):
        patched = [
            f"hostname {name}" if line.startswith("hostname ") else line for line in lines
        ]
        set_config(dev, patched, replace=True)

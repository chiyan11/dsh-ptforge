"""Incremental edits on an existing topology.

Re-writing an eleven-device ``.pkt`` just to change one ACL is wasteful and
risks losing hand edits, so :func:`apply_ops` mutates only the requested
device and re-encodes the container once.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from . import edit
from .ptcrypto import ptfile

__all__ = ["PatchError", "apply_ops", "patch_file"]


class PatchError(RuntimeError):
    """Raised for an unknown operation or malformed arguments."""


def _interface_body(lines: list[str], interface: str) -> tuple[int, int]:
    """Return ``(start, end)`` line indexes of one interface block."""
    start = None
    for index, line in enumerate(lines):
        if line.strip().lower() == f"interface {interface}".lower():
            start = index
            continue
        if start is not None:
            stripped = line.strip()
            if stripped and not line[:1].isspace() and not stripped.startswith("!"):
                return start, index
    if start is None:
        raise PatchError(f"interface {interface!r} not found in running-config")
    return start, len(lines)


def set_switchport(dev: ET.Element, interface: str, *, vlan: int, mode: str = "access") -> dict:
    lines = edit.config_lines(dev)
    try:
        start, end = _interface_body(lines, interface)
    except PatchError:
        # A device that never had an IOS config (a switch straight out of the
        # spec) still accepts switchport settings: create the block.
        block = [
            f"interface {interface}",
            f" switchport mode {mode}",
            f" switchport access vlan {vlan}",
        ]
        if lines and lines[-1].strip() == "end":
            rebuilt = lines[:-1] + block + ["end"]
        else:
            rebuilt = lines + block
        edit.set_config(dev, rebuilt, replace=True)
        return {"interface": interface, "mode": mode, "vlan": vlan, "created": True}
    body = [line.strip() for line in lines[start + 1 : end]]
    body = [line for line in body if not line.startswith("switchport ")]
    body.append(f"switchport mode {mode}")
    body.append(f"switchport access vlan {vlan}")
    rebuilt = lines[: start + 1] + [f" {line}" for line in body] + lines[end:]
    edit.set_config(dev, rebuilt, replace=True)
    return {"interface": interface, "mode": mode, "vlan": vlan}


def remove_lines(dev: ET.Element, needle: str, *, limit: int = 1) -> dict:
    lines = edit.config_lines(dev)
    kept: list[str] = []
    removed: list[str] = []
    for line in lines:
        if len(removed) < limit and needle.lower() in line.lower():
            removed.append(line)
            continue
        kept.append(line)
    if not removed:
        raise PatchError(f"no config line contains {needle!r}")
    edit.set_config(dev, kept, replace=True)
    return {"removed": removed}


def apply_ops(root: ET.Element, ops: list[dict]) -> dict:
    changes: list[dict] = []
    # Resolve device names once, against the names the file has *now*. A rename
    # op later in the list must not orphan the operations that follow it.
    resolved = {name.casefold(): (name, dev) for name, dev in edit.devices(root).items()}
    for index, op in enumerate(ops):
        if not isinstance(op, dict):
            raise PatchError(f"op #{index} is not an object")
        kind = op.get("op")
        if kind is None:
            raise PatchError(f"op #{index} is missing 'op'")
        name = op.get("device")
        if not name:
            raise PatchError(f"op #{index} ({kind}) needs 'device'")
        entry = resolved.get(str(name).casefold())
        if entry is None:
            known = ", ".join(sorted(original for original, _ in resolved.values()))
            raise PatchError(f"op #{index} ({kind}): no device named {name!r}; devices: {known}")
        original_name, dev = entry
        name = original_name
        if kind == "set_ipv4":
            port = op.get("port") or op.get("interface")
            if not port or not op.get("address"):
                raise PatchError("set_ipv4 needs 'port' and 'address'")
            edit.set_ipv4(
                dev,
                port,
                op["address"],
                op.get("mask", "255.255.255.0"),
                op.get("gateway"),
            )
            changes.append({"op": kind, "device": name, "port": port})
        elif kind == "set_config":
            lines = op.get("lines") or []
            if not lines:
                raise PatchError("set_config needs 'lines'")
            merged = edit.set_config(dev, lines, replace=bool(op.get("replace", False)))
            changes.append(
                {"op": kind, "device": name, "config_lines": len(merged)}
            )
        elif kind == "rename":
            new = op.get("name")
            if not new:
                raise PatchError("rename needs 'name'")
            edit.rename(dev, new)
            changes.append({"op": kind, "device": name, "new_name": new})
        elif kind == "set_switchport":
            interface = op.get("port") or op.get("interface")
            if not interface or "vlan" not in op:
                raise PatchError("set_switchport needs 'port' and 'vlan'")
            changes.append(
                {
                    "op": kind,
                    "device": name,
                    **set_switchport(
                        dev, interface, vlan=int(op["vlan"]), mode=op.get("mode", "access")
                    ),
                }
            )
        elif kind == "remove_config":
            needle = op.get("contains")
            if not needle:
                raise PatchError("remove_config needs 'contains'")
            changes.append(
                {"op": kind, "device": name, **remove_lines(dev, needle, limit=int(op.get("limit", 1)))}
            )
        else:
            raise PatchError(f"unknown op {kind!r}")
    return {"ops": changes}


def patch_file(
    source: str | Path,
    ops: list[dict],
    *,
    out: str | Path | None = None,
) -> dict:
    root = ptfile.decode(str(source))
    summary = apply_ops(root, ops)
    target = Path(out) if out else Path(source)
    ptfile.encode(root, str(target))
    summary["path"] = str(target)
    summary["bytes"] = target.stat().st_size
    return summary

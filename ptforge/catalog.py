"""Device template catalog and port naming for Packet Tracer documents."""

from __future__ import annotations

import copy
import functools
import json
import xml.etree.ElementTree as ET
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"
TEMPLATE_DIR = ASSETS / "templates"
SKELETON = ASSETS / "skeleton_8.1.1.xml"
NAMES_JSON = ASSETS / "port_names.json"

# XML port type enum -> IOS interface family
FAMILY = {
    "eCopperFastEthernet": "FastEthernet",
    "eCopperGigabitEthernet": "GigabitEthernet",
    "eCopperTenGigabitEthernet": "TenGigabitEthernet",
    "eCopperEthernet": "Ethernet",
    "eSerial": "Serial",
    "eFiberFastEthernet": "FastEthernet",
    "eFiberGigabitEthernet": "GigabitEthernet",
    "eCopperGigabitEthernetFiber": "GigabitEthernet",
    "eDot11abg": "Wireless",
    "eWireless": "Wireless",
}

#: Models whose ports are numbered per module starting at 1 (IOS switch style).
#: Router model numbers such as 2901/2911 must NOT be caught by a "29" prefix.
SWITCH_TYPES = (
    "2960",
    "2950",
    "3550",
    "3560",
    "3650",
    "3750",
    "CGR",
    "IE-",
    "Cat",
    "Switch-PT",
)


class CatalogError(RuntimeError):
    pass


@functools.lru_cache(maxsize=1)
def models() -> tuple[str, ...]:
    return tuple(sorted(p.stem for p in TEMPLATE_DIR.glob("*.xml")))


@functools.lru_cache(maxsize=1)
def _naming_rules() -> dict:
    try:
        return json.loads(NAMES_JSON.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def skeleton_tree() -> ET.ElementTree:
    if not SKELETON.exists():
        raise CatalogError(f"missing skeleton asset: {SKELETON}")
    return ET.parse(SKELETON)


def template(model: str) -> ET.Element:
    """Return a fresh copy of the harvested device template for ``model``."""
    path = TEMPLATE_DIR / f"{model}.xml"
    if not path.exists():
        raise CatalogError(
            f"unknown device model {model!r}; available: {', '.join(models())}"
        )
    return copy.deepcopy(ET.parse(path).getroot())


def engine(device: ET.Element) -> ET.Element:
    eng = device.find("ENGINE")
    if eng is None:
        raise CatalogError("device XML has no ENGINE element")
    return eng


def model_of(device: ET.Element) -> str | None:
    typ = engine(device).find("TYPE")
    return typ.get("model") if typ is not None else None


def ports(device: ET.Element) -> list[ET.Element]:
    """All PORT elements in document order."""
    return list(engine(device).iter("PORT"))


def port_family(port: ET.Element) -> str | None:
    return FAMILY.get(port.findtext("TYPE") or "")


def _is_switch(model: str | None) -> bool:
    return bool(model) and model.startswith(SWITCH_TYPES)


def _walk_ports(
    module: ET.Element,
    path: tuple[int, ...] = (),
) -> list[tuple[tuple[int, ...], ET.Element]]:
    """Yield (slot path, PORT) for every port, in document order."""
    out: list[tuple[tuple[int, ...], ET.Element]] = []
    for slot_index, slot in enumerate(module.findall("SLOT")):
        for sub in slot.findall("MODULE"):
            out.extend(_walk_ports(sub, path + (slot_index,)))
    for port in module.findall("PORT"):
        out.append((path, port))
    return out


def _port_name(
    model: str,
    path: tuple[int, ...],
    index: int,
    family: str,
    total: int,
) -> str:
    """PT interface name for one port.

    PT derives names from the chassis slot path plus the port index inside that
    module: the onboard gigabit ports of a 2911 become GigabitEthernet0/0..0/2,
    a WIC in slot 3 becomes Serial0/3/0 and an ISR4331 becomes 0/0/0.  Switches
    number their ports from 1 per module, end devices have a bare FastEthernet0.
    """
    if total == 1 and family in ("FastEthernet", "GigabitEthernet", "Ethernet"):
        return f"{family}0"
    if _is_switch(model):
        return f"{family}0/{index + 1}"
    suffix = "".join(f"/{step}" for step in path[1:])
    return f"{family}0{suffix}/{index}"


def port_names(device: ET.Element) -> list[str]:
    """Compute IOS interface names for every PORT, in document order."""
    model = model_of(device) or ""
    root = engine(device).find("MODULE")
    if root is None:
        return []
    walked = _walk_ports(root)
    total = sum(1 for _path, port in walked if port_family(port))
    names: list[str] = []
    counters: dict[tuple, int] = {}
    family_next: dict[str, int] = {}
    seen: set[str] = set()
    switch = _is_switch(model)
    for path, port in walked:
        family = port_family(port)
        if not family:
            names.append("")
            continue
        # Switches number each interface family from 1 inside its own module, so
        # the two gigabit uplinks of a 2960-24TT stay GigabitEthernet0/1..0/2
        # instead of continuing after FastEthernet0/24.
        key: tuple = (path, family) if switch else path
        index = counters.get(key, 0)
        counters[key] = index + 1
        name = _port_name(model, path, index, family, total)
        if name in seen:  # modular chassis keep separate modules per port
            nxt = family_next.get(family, 0)
            while f"{family}0/{nxt + 1}" in seen:
                nxt += 1
            name = f"{family}0/{nxt + 1}"
            family_next[family] = nxt + 1
        seen.add(name)
        names.append(name)
    return names


def port_index(device: ET.Element, name: str) -> int | None:
    """Resolve an interface name to its PORT index, or None."""
    for idx, candidate in enumerate(port_names(device)):
        if candidate == name:
            return idx
    return None


def free_ports(device: ET.Element, used: set[str]) -> list[tuple[int, str, str]]:
    """Ports not yet cabled: list of (index, family, name)."""
    out = []
    for idx, name in enumerate(port_names(device)):
        if not name or name in used:
            continue
        fam = port_family(ports(device)[idx]) or ""
        out.append((idx, fam, name))
    return out

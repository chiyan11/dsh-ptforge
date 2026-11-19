"""Build Packet Tracer topologies from a declarative specification."""

from __future__ import annotations

import copy
import random
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from . import catalog
from .ptcrypto import ptfile

def _cable_family(model: str) -> str:
    """Rough device class, used only to pick a cable type."""
    text = model.lower()
    if text.startswith(("2960", "2950", "3550", "3560", "3650", "3750", "switch", "hub", "cgr", "ie-", "cat")):
        return "switch"
    if text.startswith(("pc", "laptop", "server", "printer", "smart", "tablet")):
        return "host"
    if text.startswith(("router", "isr", "1841", "1941", "2620", "2801", "2811", "2901", "2911", "4321", "4331", "819", "829", "1240")):
        return "router"
    return text[:4]


CABLE_TYPES = {
    "straight": ("eCopper", "eStraightThrough", "#6ba72e"),
    "cross": ("eCopper", "eCrossOver", "#b03a2e"),
    "fiber": ("eFiber", "eFiber", "#d4ac0d"),
    "serial": ("eSerial", "eSerial", "#2e86c1"),
    "console": ("eConsole", "eConsole", "#7f8c8d"),
    "phone": ("ePhone", "ePhone", "#8e44ad"),
    "coaxial": ("eCoaxial", "eCoaxial", "#5d6d7e"),
}

_rng = random.Random()

#: Name chain of the physical workspace node that generated devices live in.
#: PT resolves the comma separated GUID chain in DEVICE/WORKSPACE/PHYSICAL
#: against PHYSICALWORKSPACE; a device without a matching node still opens, but
#: PT then saves a document whose physical data is corrupt and cannot be
#: reopened.  So every generated device gets a real node here.
PHYSICAL_CHAIN = (
    "Intercity",
    "Home City",
    "Corporate Office",
    "Main Wiring Closet",
)
DEFAULT_PHYSICAL_PATH = ",".join(PHYSICAL_CHAIN)


def mac_address(seed: int | None = None) -> str:
    r = random.Random(seed) if seed is not None else _rng
    octets = [0x00, 0xE0, 0xF9] + [r.randrange(256) for _ in range(3)]
    hexs = "".join(f"{b:02X}" for b in octets)
    return f"{hexs[0:4]}.{hexs[4:8]}.{hexs[8:12]}"


@dataclass
class DeviceHandle:
    name: str
    model: str
    ref: str
    element: ET.Element
    used_ports: set[str] = field(default_factory=set)


class TopologyBuilder:
    """Assemble a PT document (skeleton + devices + links) in memory."""

    def __init__(self) -> None:
        self.tree = catalog.skeleton_tree()
        self.root = self.tree.getroot()
        network = self.root.find("NETWORK")
        if network is None:
            raise catalog.CatalogError("skeleton has no NETWORK element")
        self.devices_el = network.find("DEVICES")
        self.links_el = network.find("LINKS")
        if self.devices_el is None or self.links_el is None:
            raise catalog.CatalogError("skeleton NETWORK lacks DEVICES/LINKS")
        self.devices: dict[str, DeviceHandle] = {}
        self._refs: set[str] = set()
        self._physical_uuids, self._physical_container = self._find_physical_anchor()

    # ---------------------------------------------------------------- physical
    def _find_physical_anchor(self) -> tuple[list[str], ET.Element]:
        """Locate the physical workspace node devices are placed under.

        Returns the UUIDs of the ancestor chain plus the container element whose
        CHILDREN list receives one node per generated device.
        """
        workspace = self.root.find("PHYSICALWORKSPACE")
        if workspace is None:
            raise catalog.CatalogError("skeleton has no PHYSICALWORKSPACE")
        uuids: list[str] = []
        node: ET.Element | None = None
        nodes = workspace.findall("NODE")
        for wanted in PHYSICAL_CHAIN:
            match = next((n for n in nodes if n.findtext("NAME") == wanted), None)
            if match is None:
                raise catalog.CatalogError(
                    f"physical workspace has no node {wanted!r}"
                )
            uuid = match.findtext("UUID_STR")
            if not uuid:
                uuid = _random_uuid()
                _set_text(match, "UUID_STR", uuid)
            uuids.append(uuid)
            node = match
            children = match.find("CHILDREN")
            if children is None:
                children = ET.SubElement(match, "CHILDREN")
            nodes = children.findall("NODE")
        assert node is not None
        # Devices live inside the wiring closet; prefer a rack when one exists.
        children = node.find("CHILDREN")
        if children is None:
            children = ET.SubElement(node, "CHILDREN")
        racks = [n for n in children.findall("NODE") if n.findtext("NAME") == "Rack"]
        if racks:
            rack_uuid = racks[0].findtext("UUID_STR")
            if not rack_uuid:
                rack_uuid = _random_uuid()
                _set_text(racks[0], "UUID_STR", rack_uuid)
            uuids.append(rack_uuid)
            inner = racks[0].find("CHILDREN")
            if inner is None:
                inner = ET.SubElement(racks[0], "CHILDREN")
            return uuids, inner
        return uuids, children

    def _attach_physical(self, name: str, index: int) -> str:
        """Create the device's physical node and return its GUID path."""
        uuid = _random_uuid()
        node = ET.Element("NODE")
        head = (
            ("X", str(index % 8)),
            ("Y", "0"),
            ("TYPE", "6"),
            ("NAME", name),
            ("SX", "1"),
            ("SY", "1"),
            ("W", "0"),
            ("H", "0"),
            ("D", "0"),
            ("PATH", "../art/Background/grid_100x100.png"),
        )
        for tag, text in head:
            el = _add_text(node, tag, text)
            if tag == "NAME":
                el.set("translate", "true")
        _add_text(node, "CHILDREN", "")
        tail = (
            ("MANUAL_SCALING", "false"),
            ("SCALED_PIXMAP_WIDTH", "0"),
            ("SCALED_PIXMAP_HEIGHT", "0"),
            ("INIT_WIDTH", "0"),
            ("INIT_HEIGHT", "0"),
            ("INIT_DEPTH", "0"),
            ("INIT_SX", "1"),
            ("INIT_SY", "1"),
            ("INIT_SZ", "1"),
            ("BG_TILED", "false"),
            ("CUSTOM_IMAGE_WIDTH", "-1"),
            ("CUSTOM_IMAGE_HEIGHT", "-1"),
            ("SCALE_FACTOR", "1"),
            ("UUID_STR", uuid),
            ("SLOT", "0"),
            ("SUB_SLOT", "0"),
        )
        for tag, text in tail:
            _add_text(node, tag, text)
        self._physical_container.append(node)
        return ",".join(self._physical_uuids + [uuid])

    # ------------------------------------------------------------------ devices
    def add_device(
        self,
        model: str,
        name: str | None = None,
        x: float = 200.0,
        y: float = 200.0,
        *,
        config: list[str] | None = None,
        start_config: list[str] | None = None,
        physical: str | None = None,
        ipv4: tuple[str, str, str] | None = None,
        port: str | None = None,
    ) -> DeviceHandle:
        if name and name in self.devices:
            raise ValueError(f"duplicate device name: {name}")
        element = catalog.template(model)
        eng = catalog.engine(element)
        name_el = eng.find("NAME")
        if name is None:
            name = f"{model}-{len(self.devices)}"
        if name_el is None:
            name_el = ET.SubElement(eng, "NAME")
        name_el.text = name
        name_el.set("translate", "true")

        ref = self._new_ref()
        ref_el = eng.find("SAVE_REF_ID")
        if ref_el is None:
            ref_el = ET.SubElement(eng, "SAVE_REF_ID")
        ref_el.text = ref

        coord = eng.find("COORD_SETTINGS")
        if coord is None:
            coord = ET.SubElement(eng, "COORD_SETTINGS")
        _set_text(coord, "X_COORD", f"{x:.2f}")
        _set_text(coord, "Y_COORD", f"{y:.2f}")
        _set_text(coord, "Z_COORD", "0")

        physical_path = (
            self._attach_physical(name, len(self.devices))
            if physical is None
            else physical
        )
        self._place(element, x, y, physical_path)

        _set_text(eng, "POWER", "true")
        serial = eng.find("SERIALNUMBER")
        if serial is not None:
            serial.text = "PTT" + "".join(_rng.choice("0123456789ABCDEF") for _ in range(8))

        for port_el in catalog.ports(element):
            mac = mac_address()
            _set_text(port_el, "MACADDRESS", mac)
            _set_text(port_el, "BIA", mac)

        if ipv4 is not None:
            self._apply_ipv4(element, ipv4, port)

        _apply_config(eng, "RUNNINGCONFIG", config)
        _apply_config(eng, "STARTUPCONFIG", start_config)

        self.devices_el.append(element)
        handle = DeviceHandle(name=name, model=model, ref=ref, element=element)
        self.devices[name] = handle
        return handle

    # -------------------------------------------------------------------- links
    def connect(
        self,
        a: str,
        b: str,
        *,
        a_port: str | None = None,
        b_port: str | None = None,
        cable: str | None = None,
    ) -> None:
        da = self._dev(a)
        db = self._dev(b)
        pa = self._pick_port(da, a_port)
        pb = self._pick_port(db, b_port)
        if cable is None:
            # Same-kind devices (PC-PC, router-router, switch-switch) need a
            # crossover cable; everything else is a straight-through run.
            model_a = self.devices[a].model
            model_b = self.devices[b].model
            cable = "cross" if _cable_family(model_a) == _cable_family(model_b) else "straight"
        link_type, cable_type, color = CABLE_TYPES.get(cable, CABLE_TYPES["straight"])

        link = ET.SubElement(self.links_el, "LINK")
        _add_text(link, "TYPE", link_type)
        c = ET.SubElement(link, "CABLE")
        # PT keys the endpoints on position: CABLE holds FROM, PORT, TO, PORT in
        # that order, so the two PORT elements must be appended, not looked up.
        _add_text(c, "LENGTH", "1")
        _add_text(c, "FUNCTIONAL", "true")
        _add_text(c, "FROM", da.ref)
        _add_text(c, "PORT", pa)
        _add_text(c, "TO", db.ref)
        _add_text(c, "PORT", pb)
        _add_text(c, "FROM_DEVICE_MEM_ADDR", _dev_addr(da.element))
        _add_text(c, "TO_DEVICE_MEM_ADDR", _dev_addr(db.element))
        _add_text(c, "FROM_PORT_MEM_ADDR", str(_rng.randrange(2**41, 2**42)))
        _add_text(c, "TO_PORT_MEM_ADDR", str(_rng.randrange(2**41, 2**42)))
        _add_text(c, "GEO_VIEW_COLOR", color)
        _add_text(c, "IS_MANAGED_IN_RACK_VIEW", "false")
        _add_text(c, "TYPE", cable_type)

    # ------------------------------------------------------------------- output
    def to_xml(self) -> bytes:
        return ET.tostring(self.root, encoding="utf-8", xml_declaration=False)

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(ptfile.encode_container(self.to_xml()))
        return path

    # ------------------------------------------------------------------ helpers
    def _apply_ipv4(
        self,
        element: ET.Element,
        ipv4: tuple[str, str, str],
        port_name: str | None,
    ) -> None:
        """Give an end device a static IPv4 address (desktop/ip style config)."""
        address, mask, gateway = ipv4
        plist = catalog.ports(element)
        if not plist:
            raise catalog.CatalogError(f"{catalog.model_of(element)}: no ports")
        if port_name:
            idx = catalog.port_index(element, port_name)
            if idx is None:
                raise ValueError(
                    f"no interface {port_name!r}; available: "
                    + ", ".join(n for n in catalog.port_names(element) if n)
                )
            port = plist[idx]
        else:
            port = plist[0]
        _set_text(port, "IP", address)
        _set_text(port, "SUBNET", mask)
        _set_text(port, "PORT_GATEWAY", gateway)
        _set_text(port, "PORT_DHCP_ENABLE", "false")
        eng = catalog.engine(element)
        _set_text(eng, "GATEWAY", gateway)
        dhcp = eng.find("DHCP_CLIENT")
        if dhcp is not None:
            _set_text(dhcp, "ENABLED", "false")

    def _place(
        self,
        element: ET.Element,
        x: float,
        y: float,
        physical: str | None,
    ) -> None:
        """Write the WORKSPACE block: logical canvas position and physical path."""
        ws = element.find("WORKSPACE")
        if ws is None:
            ws = ET.SubElement(element, "WORKSPACE")
        logical = ws.find("LOGICAL")
        if logical is None:
            logical = ET.SubElement(ws, "LOGICAL")
        _set_text(logical, "X", f"{x:g}")
        _set_text(logical, "Y", f"{y:g}")
        if logical.find("DEVCLUSTERID") is None:
            _set_text(logical, "DEVCLUSTERID", "1-1")
        # MEM_ADDR/DEV_ADDR are runtime handles: cables reference the device address,
        # so both must be unique per device or PT rejects the file.
        _set_text(logical, "MEM_ADDR", str(_rng.randrange(2**41, 2**42)))
        dev_addr = str(_rng.randrange(2**41, 2**42))
        _set_text(logical, "DEV_ADDR", dev_addr)

        ph = ws.find("PHYSICAL")
        if ph is None:
            ph = ET.SubElement(ws, "PHYSICAL")
            ph.set("translate", "true")
        ph.text = physical or ""

    def _dev(self, name: str) -> DeviceHandle:
        try:
            return self.devices[name]
        except KeyError:
            raise ValueError(
                f"unknown device {name!r}; known: {', '.join(sorted(self.devices))}"
            ) from None

    def _pick_port(self, dev: DeviceHandle, requested: str | None) -> str:
        if requested and requested != "auto":
            if catalog.port_index(dev.element, requested) is None:
                raise ValueError(
                    f"{dev.name}: no interface {requested!r}; available: "
                    + ", ".join(n for n in catalog.port_names(dev.element) if n)
                )
            if requested in dev.used_ports:
                raise ValueError(f"{dev.name}: interface {requested} already cabled")
            dev.used_ports.add(requested)
            return requested

        candidates = catalog.free_ports(dev.element, dev.used_ports)
        # prefer copper Ethernet-ish ports, then everything else
        preferred = [c for c in candidates if c[1].startswith("eCopper")]
        chosen = (preferred or candidates)
        if not chosen:
            raise ValueError(f"{dev.name}: no free ports left")
        idx, _fam, name = chosen[0]
        dev.used_ports.add(name)
        return name

    def _new_ref(self) -> str:
        while True:
            ref = f"save-ref-id:{_rng.randrange(10**17, 10**18)}"
            if ref not in self._refs:
                self._refs.add(ref)
                return ref


def _random_uuid() -> str:
    return "{" + str(__import__("uuid").uuid4()) + "}"


def _dev_addr(element: ET.Element) -> str:
    addr = element.find("WORKSPACE/LOGICAL/DEV_ADDR")
    if addr is None or not addr.text:
        raise catalog.CatalogError("device is missing WORKSPACE/LOGICAL/DEV_ADDR")
    return addr.text


def _add_text(parent: ET.Element, tag: str, text: str) -> ET.Element:
    el = ET.SubElement(parent, tag)
    el.text = text
    return el


def _set_text(parent: ET.Element, tag: str, text: str) -> ET.Element:
    el = parent.find(tag)
    if el is None:
        el = ET.SubElement(parent, tag)
    el.text = text
    return el


def _apply_config(eng: ET.Element, tag: str, lines: list[str] | None) -> None:
    el = eng.find(tag)
    if el is None:
        if not lines:
            return
        el = ET.SubElement(eng, tag)
    for child in list(el):
        el.remove(child)
    for line in lines or []:
        line_el = ET.SubElement(el, "LINE")
        line_el.text = line


def blank_document() -> ET.ElementTree:
    """A pristine PT 8.1.1 document with no devices."""
    return catalog.skeleton_tree()



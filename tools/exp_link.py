"""Isolate which LINK field PT rejects, by cloning a known-good link."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ptforge.build import TopologyBuilder, _dev_addr  # noqa: E402
from ptforge.ptcrypto import ptfile  # noqa: E402

OUT = ROOT / "fixtures" / "exp"
OUT.mkdir(parents=True, exist_ok=True)


def base_builder() -> TopologyBuilder:
    b = TopologyBuilder()
    b.add_device("PC-PT", "PC0", 260, 180)
    b.add_device("2960-24TT", "SW1", 520, 300)
    return b


def clone_real_link() -> ET.Element:
    src = ET.parse(ROOT / "fixtures" / "decoded" / "8.3.xml").getroot()
    return ET.fromstring(ET.tostring(src.find("NETWORK/LINKS/LINK")))


def write(name: str, builder: TopologyBuilder) -> None:
    out = OUT / name
    out.write_bytes(ptfile.encode_container(builder.to_xml()))
    print(f"{name}: {out.stat().st_size} B")


def main() -> int:
    # g1: real link element retargeted to our refs/ports
    b = base_builder()
    link = clone_real_link()
    cable = link.find("CABLE")
    cable.find("FROM").text = b.devices["PC0"].ref
    cable.find("TO").text = b.devices["SW1"].ref
    ports = cable.findall("PORT")
    ports[0].text = "FastEthernet0"
    ports[1].text = "FastEthernet0/1"
    cable.find("FROM_DEVICE_MEM_ADDR").text = _dev_addr(b.devices["PC0"].element)
    cable.find("TO_DEVICE_MEM_ADDR").text = _dev_addr(b.devices["SW1"].element)
    b.links_el.append(link)
    write("g1_cloned_real_link.pkt", b)

    # g2: our link, but mem addrs copied from the real link (no DEV_ADDR linkage)
    b = base_builder()
    b.connect("PC0", "SW1", a_port="FastEthernet0", b_port="FastEthernet0/1")
    ours = list(b.links_el)[0]
    real = clone_real_link().find("CABLE")
    oc = ours.find("CABLE")
    for tag in ("FROM_DEVICE_MEM_ADDR", "TO_DEVICE_MEM_ADDR",
                "FROM_PORT_MEM_ADDR", "TO_PORT_MEM_ADDR"):
        oc.find(tag).text = real.find(tag).text
    write("g2_our_link_real_addrs.pkt", b)

    # g3: our link with mem addr elements emptied
    b = base_builder()
    b.connect("PC0", "SW1", a_port="FastEthernet0", b_port="FastEthernet0/1")
    oc = list(b.links_el)[0].find("CABLE")
    for tag in ("FROM_DEVICE_MEM_ADDR", "TO_DEVICE_MEM_ADDR",
                "FROM_PORT_MEM_ADDR", "TO_PORT_MEM_ADDR"):
        oc.find(tag).text = ""
    write("g3_our_link_empty_addrs.pkt", b)

    # g4: our link with the elements removed entirely
    b = base_builder()
    b.connect("PC0", "SW1", a_port="FastEthernet0", b_port="FastEthernet0/1")
    oc = list(b.links_el)[0].find("CABLE")
    for tag in ("FROM_DEVICE_MEM_ADDR", "TO_DEVICE_MEM_ADDR",
                "FROM_PORT_MEM_ADDR", "TO_PORT_MEM_ADDR"):
        oc.remove(oc.find(tag))
    write("g4_our_link_no_addrs.pkt", b)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

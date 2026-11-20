"""Engine tests that need no Packet Tracer installation.

Run with: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ptforge import catalog, edit
from ptforge.build import TopologyBuilder
from ptforge.ptcrypto import ptfile


class ContainerTests(unittest.TestCase):
    def test_roundtrip_keeps_xml(self) -> None:
        xml = b"<PACKETTRACER5><VERSION>8.1.1.0022</VERSION></PACKETTRACER5>"
        blob = ptfile.encode_container(xml)
        self.assertTrue(ptfile.looks_like_pkt(blob))
        self.assertEqual(ptfile.decode_container(blob), xml)

    def test_rejects_garbage(self) -> None:
        with self.assertRaises(ptfile.PacketTracerFormatError):
            ptfile.decode_container(b"not a packet tracer file")


class CatalogTests(unittest.TestCase):
    def test_switch_uplinks_restart_per_family(self) -> None:
        names = [n for n in catalog.port_names(catalog.template("2960-24TT")) if n]
        self.assertIn("FastEthernet0/24", names)
        self.assertIn("GigabitEthernet0/1", names)
        self.assertIn("GigabitEthernet0/2", names)
        self.assertNotIn("GigabitEthernet0/25", names)

    def test_router_slot_paths(self) -> None:
        self.assertEqual(
            [n for n in catalog.port_names(catalog.template("2911")) if n],
            ["GigabitEthernet0/0", "GigabitEthernet0/1", "GigabitEthernet0/2"],
        )
        self.assertTrue(all("/0/" in n for n in catalog.port_names(catalog.template("ISR4331")) if n))


class MergeTests(unittest.TestCase):
    def test_interface_block_is_updated_in_place(self) -> None:
        existing = [
            "hostname R1",
            "interface GigabitEthernet0/0",
            " ip address 10.0.0.1 255.255.255.0",
            "interface GigabitEthernet0/1",
            " no shutdown",
            "end",
        ]
        merged = edit.merge_lines(
            existing,
            ["interface GigabitEthernet0/1", " ip address 10.20.0.1 255.255.255.0", " no shutdown"],
        )
        self.assertEqual(merged.count("interface GigabitEthernet0/1"), 1)
        self.assertIn(" ip address 10.20.0.1 255.255.255.0", merged)
        self.assertIn("hostname R1", merged)
        self.assertEqual(merged[-1], "end")

    def test_new_lines_are_appended(self) -> None:
        merged = edit.merge_lines(["hostname R1", "end"], ["ip route 0.0.0.0 0.0.0.0 10.0.0.254"])
        self.assertEqual(merged, ["hostname R1", "ip route 0.0.0.0 0.0.0.0 10.0.0.254", "end"])


class BuildTests(unittest.TestCase):
    def test_build_has_devices_links_and_physical_nodes(self) -> None:
        builder = TopologyBuilder()
        builder.add_device(
            "PC-PT", "PC0", 200, 200, ipv4=("192.168.1.10", "255.255.255.0", "192.168.1.1")
        )
        builder.add_device("2960-24TT", "SW1", 400, 200, config=["hostname SW1"])
        builder.connect("PC0", "SW1", a_port="FastEthernet0", b_port="FastEthernet0/1")
        root = builder.root
        devices = root.findall("NETWORK/DEVICES/DEVICE")
        self.assertEqual(len(devices), 2)
        links = root.findall("NETWORK/LINKS/LINK")
        self.assertEqual(len(links), 1)
        ports = links[0].find("CABLE").findall("PORT")
        self.assertEqual([p.text for p in ports], ["FastEthernet0", "FastEthernet0/1"])
        physical = devices[0].find("WORKSPACE/PHYSICAL")
        self.assertEqual(len(physical.text.split(",")), 5)  # 4 ancestors + device node

    def test_save_then_edit_config(self) -> None:
        builder = TopologyBuilder()
        builder.add_device("2911", "R1", 200, 200)
        # Write inside the workspace: the DSH sandbox denies temp-directory
        # deletion outside it, which would fail the test during cleanup.
        tmp = Path(__file__).with_name("_tmp")
        tmp.mkdir(exist_ok=True)
        path = tmp / "r1.pkt"
        builder.save(path)
        root = edit.load(path)
        dev = edit.device(root, "R1")
        edit.set_config(
            dev,
            ["hostname R1", "interface GigabitEthernet0/0", "ip address 10.0.0.1 255.255.255.0"],
        )
        edit.save(root, path)
        again = edit.load(path)
        lines = edit.config_lines(edit.device(again, "R1"))
        self.assertEqual(lines[0], "hostname R1")
        self.assertEqual(lines[-1], "end")


class StateTests(unittest.TestCase):
    def _office(self) -> Path:
        builder = TopologyBuilder()
        builder.add_device("2911", "R1", 200, 200, config=[
            "hostname R1",
            "interface GigabitEthernet0/0",
            " ip address 192.168.10.1 255.255.255.0",
            " no shutdown",
            "ip route 172.18.20.0 255.255.255.0 192.168.10.254",
        ])
        builder.add_device("PC-PT", "PC0", 200, 400, ipv4=("192.168.10.10", "255.255.255.0", "192.168.10.1"))
        builder.connect("PC0", "R1", a_port="FastEthernet0", b_port="GigabitEthernet0/0")
        tmp = Path(__file__).with_name("_tmp")
        tmp.mkdir(exist_ok=True)
        path = tmp / "state.pkt"
        builder.save(path)
        return path

    def test_describe_reads_addresses_and_routes(self) -> None:
        from ptforge import state

        root = state.load(self._office())
        summary = state.describe(root)
        self.assertEqual(summary["version"], "8.1.1.0022")
        r1 = next(d for d in summary["devices"] if d["name"] == "R1")
        self.assertEqual(r1["hostname"], "R1")
        self.assertEqual(r1["static_routes"][0]["cidr"], "172.18.20.0/24")

    def test_check_reports_line_level_problems(self) -> None:
        from ptforge import state

        root = state.load(self._office())
        result = state.check(root, [
            {"device": "R1", "route": "172.18.20.0/24"},
            {"device": "PC0", "interface": "FastEthernet0", "ip": "192.168.10.10"},
            {"device": "R1", "route": "10.99.0.0/16"},
        ])
        self.assertFalse(result["ok"])
        self.assertEqual([r["ok"] for r in result["results"]], [True, True, False])
        self.assertIn("missing", result["results"][2]["problems"][0])

    def test_unindented_interface_commands_stay_in_the_block(self) -> None:
        from ptforge import state

        builder = TopologyBuilder()
        builder.add_device("2911", "R1", 200, 200, config=[
            "hostname R1",
            "interface GigabitEthernet0/0",
            "ip address 10.10.0.254 255.255.255.0",
            "no shutdown",
            "ip route 0.0.0.0 0.0.0.0 10.10.0.1",
        ])
        tmp = Path(__file__).with_name("_tmp") / "flat_config.pkt"
        builder.save(tmp)
        r1 = state.device_state(state.load(tmp), "R1")
        gi0 = next(i for i in r1["interfaces"] if i["name"] == "GigabitEthernet0/0")
        self.assertEqual(gi0["ip"], "10.10.0.254")
        self.assertEqual(gi0["prefix"], 24)
        self.assertEqual(r1["static_routes"][0]["cidr"], "0.0.0.0/0")


class PatchTests(unittest.TestCase):
    def test_rename_does_not_orphan_later_ops(self) -> None:
        from ptforge import patch, state

        builder = TopologyBuilder()
        builder.add_device("2960-24TT", "SW1", 300, 200)
        builder.add_device("PC-PT", "PC0", 100, 400, ipv4=("192.168.10.10", "255.255.255.0", None))
        builder.connect("PC0", "SW1", a_port="FastEthernet0", b_port="FastEthernet0/1")
        tmp = Path(__file__).with_name("_tmp")
        tmp.mkdir(exist_ok=True)
        path = tmp / "patch.pkt"
        builder.save(path)

        result = patch.patch_file(path, [
            {"op": "rename", "device": "SW1", "name": "CORE"},
            {"op": "set_switchport", "device": "SW1", "port": "FastEthernet0/1", "vlan": 20},
        ], out=tmp / "patched.pkt")
        self.assertEqual(result["ops"][1]["device"], "SW1")
        root = state.load(tmp / "patched.pkt")
        core = next(d for d in state.describe(root)["devices"] if d["name"] == "CORE")
        self.assertEqual(core["interfaces"][0]["access_vlan"], 20)

    def test_set_config_appends_by_default(self) -> None:
        from ptforge import patch, state

        builder = TopologyBuilder()
        builder.add_device("2911", "R1", 200, 200, config=[
            "hostname R1",
            "interface GigabitEthernet0/0",
            " ip address 10.0.0.1 255.255.255.0",
        ])
        tmp = Path(__file__).with_name("_tmp")
        tmp.mkdir(exist_ok=True)
        path = tmp / "append.pkt"
        builder.save(path)
        patch.patch_file(path, [
            {"op": "set_config", "device": "R1", "lines": ["ip route 0.0.0.0 0.0.0.0 10.0.0.254"]},
        ])
        root = state.load(path)
        r1 = next(d for d in state.describe(root)["devices"] if d["name"] == "R1")
        self.assertEqual(r1["hostname"], "R1")
        self.assertTrue(any(i["ip"] == "10.0.0.1" for i in r1["interfaces"]))
        self.assertEqual(r1["static_routes"][0]["next_hop"], "10.0.0.254")


class DoctorTests(unittest.TestCase):
    def test_verify_file_reports_version_and_counts(self) -> None:
        from ptforge import doctor

        builder = TopologyBuilder()
        builder.add_device("PC-PT", "PC0", 100, 100)
        tmp = Path(__file__).with_name("_tmp")
        tmp.mkdir(exist_ok=True)
        path = tmp / "doctor.pkt"
        builder.save(path)
        report = doctor.verify_file(path)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["version"], "8.1.1.0022")
        self.assertEqual(report["devices"], 1)

    def test_file_check_does_not_require_packet_tracer(self) -> None:
        import contextlib
        import io
        import os
        from unittest import mock

        from ptforge import cli

        builder = TopologyBuilder()
        builder.add_device("PC-PT", "PC0", 100, 100)
        tmp = Path(__file__).with_name("_tmp")
        tmp.mkdir(exist_ok=True)
        path = tmp / "doctor_cli.pkt"
        builder.save(path)

        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"PT_EXE": str(tmp / "missing.exe")}):
            with contextlib.redirect_stdout(buf):
                code = cli.main(["doctor", str(path)])
        self.assertEqual(code, 0, buf.getvalue())
        self.assertIn("missing", buf.getvalue())


class ReportTests(unittest.TestCase):
    def test_report_writes_tables_and_captions(self) -> None:
        from ptforge import report

        builder = TopologyBuilder()
        builder.add_device("2911", "R1", 200, 200)
        builder.add_device("PC-PT", "PC0", 200, 400, ipv4=("192.168.10.10", "255.255.255.0", "192.168.10.1"))
        builder.connect("PC0", "R1", a_port="FastEthernet0", b_port="GigabitEthernet0/0")
        tmp = Path(__file__).with_name("_tmp")
        tmp.mkdir(exist_ok=True)
        path = tmp / "report.pkt"
        builder.save(path)
        out = tmp / "report_out"
        result = report.build_report(path, out, figures=[{"path": "figures/topology.png", "caption": "拓扑"}])
        self.assertTrue((out / "report.md").exists())
        self.assertTrue((out / "captions.json").exists())
        self.assertEqual(result["links"], 1)
        self.assertEqual(result["devices"], 2)
        self.assertEqual(result["figures"], 1)
        self.assertIn("地址表", (out / "report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()


class NoteTests(unittest.TestCase):
    def test_add_note_anchors_and_survives_roundtrip(self) -> None:
        from ptforge import build, notes

        builder = build.TopologyBuilder()
        builder.add_device("PC-PT", name="PC0", x=200, y=300)
        root = builder.root
        added = notes.add_note(root, "PC0 10.0.0.10", x=0, y=0, anchor_device="PC0", dy=-60)
        self.assertEqual(added["text"], "PC0 10.0.0.10")
        self.assertEqual(added["y"], 240.0)
        self.assertGreaterEqual(added["z"], 40000)
        listed = notes.notes(root)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["text"], "PC0 10.0.0.10")


class WebTests(unittest.TestCase):
    def test_read_and_replace_server_page(self) -> None:
        import tempfile
        import pathlib

        from ptforge import build, web

        builder = build.TopologyBuilder()
        builder.add_device("Server-PT", name="S1", x=200, y=300)
        path = pathlib.Path(tempfile.mkdtemp()) / "srv.pkt"
        builder.save(path)
        pages = web.list_pages(str(path))["pages"]
        self.assertIn("index.html", pages)
        original = web.read_page(str(path), device="S1")["html"]
        self.assertIn("Cisco", original)
        result = web.set_page(str(path), "<h1>hi</h1>", device="S1", name="index.html")
        self.assertEqual(result["device"], "S1")
        self.assertEqual(web.read_page(str(path), device="S1")["html"], "<h1>hi</h1>")


class SpecTests(unittest.TestCase):
    def test_ipv4_forms(self) -> None:
        from ptforge import spec

        cases = [
            (["192.168.10.1/24"], ("192.168.10.1", "255.255.255.0", "")),
            (
                ["192.168.10.1/24", "192.168.10.254"],
                ("192.168.10.1", "255.255.255.0", "192.168.10.254"),
            ),
            (["192.168.10.1", "255.255.255.0"], ("192.168.10.1", "255.255.255.0", "")),
            (
                "192.168.10.1 255.255.255.0 192.168.10.254",
                ("192.168.10.1", "255.255.255.0", "192.168.10.254"),
            ),
            (
                {"address": "192.168.10.1/24", "gateway": "192.168.10.254"},
                ("192.168.10.1", "255.255.255.0", "192.168.10.254"),
            ),
        ]
        for value, expected in cases:
            self.assertEqual(spec._parse_ipv4(value, "D"), expected, value)

    def test_single_item_list_builds(self) -> None:
        from ptforge import spec

        data = {
            "name": "t",
            "devices": [{"name": "PC0", "model": "PC-PT", "ipv4": ["10.0.0.10/24"]}],
            "links": [],
        }
        devices, _ = spec.parse_spec(data)
        self.assertEqual(devices[0].ipv4, ("10.0.0.10", "255.255.255.0", ""))


class ModelsCliTests(unittest.TestCase):
    def test_query_filters_model_list(self) -> None:
        import contextlib
        import io

        from ptforge import cli

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(["models", "--query", "2960"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("2960-24TT", out)
        self.assertNotIn("2911", out)


class JsonArgumentTests(unittest.TestCase):
    def test_inline_json_and_file_path_are_both_accepted(self) -> None:
        from ptforge import cli

        inline = cli._json_argument('[{"device": "PC1"}]')
        self.assertEqual(inline, [{"device": "PC1"}])

        tmp = Path(__file__).with_name("_tmp")
        tmp.mkdir(exist_ok=True)
        path = tmp / "ops.json"
        path.write_text('{"ops": [{"op": "rename"}]}', encoding="utf-8")
        from_file = cli._json_argument(str(path))
        self.assertEqual(from_file, {"ops": [{"op": "rename"}]})

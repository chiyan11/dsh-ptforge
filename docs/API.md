# Python API

[中文版](API.zh-CN.md)

The engine is a plain Python package; you can call it without the CLI. Every signature below is taken from the current code, and the return shapes are the real ones.

```python
pip install dsh-ptforge        # the import name is still ptforge
```

Modules at a glance:

| Module | Responsibility |
| --- | --- |
| `ptforge.spec` | Parse a JSON spec, automatic layout |
| `ptforge.build` | Assemble a document (devices + links), produce `.pkt` |
| `ptforge.ptcrypto.ptfile` | Container codec (Twofish-EAX + zlib) |
| `ptforge.state` | Read-only state and assertions |
| `ptforge.edit` | Per-device edits (IP, config, rename) |
| `ptforge.patch` | Batch incremental edit operators |
| `ptforge.notes` | Canvas annotations |
| `ptforge.web` | Read/write Server-PT web pages |
| `ptforge.report` | Report material |
| `ptforge.doctor` | Environment and file-version checks |
| `ptforge.runtime` | Windows runtime (commands, ping, http, ftp) |
| `ptforge.gui` | Lower-level Win32 primitives (focus, click, screenshot, clipboard) |

---

## ptforge.spec

```python
def load_spec(path: str | Path) -> dict
def parse_spec(data: dict) -> tuple[list[DeviceSpec], list[LinkSpec]]
def auto_layout(devices: list[DeviceSpec], *, spacing: float = 190.0) -> None
def build_from_spec(data: dict, out_path: str | Path) -> Path
```

`DeviceSpec` / `LinkSpec` are dataclasses:

```python
DeviceSpec(name, model, x=None, y=None, config=[], start_config=[],
           ipv4: tuple[str, str, str] | None = None, port=None, physical=None)
LinkSpec(source, target, source_port=None, target_port=None, cable="straight")
```

`parse_spec` validates required fields and unique device names; failures raise `SpecError` (a `ValueError` subclass) with the offending device name in the message.

```python
from ptforge import spec

path = spec.build_from_spec(
    {"name": "lab", "devices": [{"model": "PC-PT", "name": "PC1", "ipv4": "10.0.0.1/24"}], "links": []},
    "lab.pkt",
)
```

---

## ptforge.build

```python
class TopologyBuilder:
    def __init__(self) -> None
    def add_device(self, model, name=None, x=200.0, y=200.0, *,
                   config=None, start_config=None, physical=None,
                   ipv4: tuple[str, str, str] | None = None,
                   port: str | None = None) -> DeviceHandle
    def connect(self, a, b, *, a_port=None, b_port=None, cable=None) -> None
    def to_xml(self) -> bytes
    def save(self, path: str | Path) -> Path
```

`DeviceHandle` exposes `name`, `model`, `ref` (`save-ref-id:N`), `element` and `used_ports`.

```python
from ptforge.build import TopologyBuilder

b = TopologyBuilder()
b.add_device("2911", "R1", 200, 200,
             config=["hostname R1", "interface GigabitEthernet0/0",
                     "ip address 10.0.0.254 255.255.255.0"])
b.add_device("2960-24TT", "SW1", 400, 200)
b.add_device("PC-PT", "PC1", 200, 380, ipv4=("10.0.0.11", "255.255.255.0", "10.0.0.254"))
b.connect("R1", "SW1")            # ports are picked automatically
b.connect("PC1", "SW1")
b.save("lab.pkt")
```

- With `cable=None`, the cable family is chosen from the device kinds: same kind (host/host, router/router, switch/switch) gets a crossover, everything else a straight-through.
- `add_device` creates the physical-workspace node for you; do not hand-build `PHYSICAL` unless you are cloning an existing lab.
- `save` goes through `ptfile.encode_container`, so the output is a `.pkt` that PT can load.

---

## ptforge.ptcrypto.ptfile

```python
def decode(path: str | Path) -> ET.Element          # .pkt -> <PACKETTRACER5>
def encode(root: ET.Element, path: str | Path) -> Path
def decode_container(data: bytes) -> bytes          # container -> XML bytes
def encode_container(xml: bytes) -> bytes           # XML bytes -> container
def looks_like_pkt(data: bytes) -> bool
```

```python
from ptforge.ptcrypto import ptfile

root = ptfile.decode("lab.pkt")
print(root.findtext("VERSION"), len(root.findall("NETWORK/DEVICES/DEVICE")))
ptfile.encode(root, "copy.pkt")
```

A file that cannot be decoded raises `ptfile.PacketTracerFormatError`. The XML has strict PT constraints (physical-workspace nodes, the order of `FROM/PORT/TO/PORT`); prefer `edit` / `patch` over hand-editing XML.

---

## ptforge.state

```python
def load(path) -> ET.Element
def describe(root: ET.Element) -> dict
def device_state(root: ET.Element, name: str) -> dict
def check(root: ET.Element, expectations: list[dict]) -> dict
```

`device_state` returns:

```python
{
  "name": "R1", "kind": "Router", "model": "2911", "hostname": "R1",
  "interfaces": [
    {"name": "GigabitEthernet0/0", "ip": "10.0.0.254", "mask": "255.255.255.0",
     "prefix": 24, "gateway": None, "shutdown": False, "description": None,
     "switchport_mode": None, "access_vlan": None, "trunk_vlans": []}
  ],
  "static_routes": [{"network": "0.0.0.0", "mask": "0.0.0.0", "cidr": "0.0.0.0/0",
                     "next_hop": "10.0.0.1"}],
  "nat": [...], "acls": {"1": [...]}, "config_lines": ["hostname R1", ...]
}
```

`check` returns `{ok, results: [{device, expect, ok, evidence, problems}]}`. Supported assertion keys:

```python
{"device": "R1", "route": "172.18.20.0/24"}
{"device": "R1", "interface": "Gi0/0", "ip": "10.0.0.254"}
{"device": "SW1", "interface": "Fa0/1", "access_vlan": 10}
{"device": "R1", "nat": "inside"}
{"device": "R1", "config_contains": "ip nat inside"}
```

An unknown device raises `StateError` and the message lists all available device names.

---

## ptforge.edit

```python
def load(path) -> ET.Element
def save(tree_or_root, path) -> Path
def devices(root) -> dict[str, ET.Element]
def device(root, name) -> ET.Element
def config_lines(dev, tag="RUNNINGCONFIG") -> list[str]
def set_config(dev, lines, *, tag="RUNNINGCONFIG", replace=True) -> list[str]
def set_ipv4(dev, port, address, mask="255.255.255.0", gateway=None) -> dict
def rename(dev, name) -> None
```

`set_config(replace=False)` merges by `interface` / `router` / `line` section instead of overwriting the whole block; `rename` updates `NAME`, `SYS_NAME` and the `hostname` line inside `RUNNINGCONFIG`.

---

## ptforge.patch

```python
def apply_ops(root, ops: list[dict]) -> dict        # {"ops": [summary of applied ops…]}
def patch_file(source, ops, *, out=None) -> dict    # {"path", "bytes", "ops"}
```

Operators:

```python
{"op": "set_ipv4", "device": "PC1", "port": "FastEthernet0",
 "address": "10.0.0.21", "mask": "255.255.255.0", "gateway": "10.0.0.254"}
{"op": "set_config", "device": "R1", "lines": ["ip route 0.0.0.0 0.0.0.0 10.0.0.1"],
 "append": True}
{"op": "rename", "device": "R1", "name": "CORE"}
{"op": "set_switchport", "device": "SW1", "interface": "FastEthernet0/5", "vlan": 20}
{"op": "remove_config", "device": "R1", "match": "ip route 0.0.0.0"}
```

Without `out` the source file is overwritten in place; pass `out` to keep the original.

---

## ptforge.notes

```python
def notes(root) -> list[dict]                       # [{"uuid","x","y","z","text"}]
def add_note(root, text, *, x, y, z=None, anchor_device=None, dx=0.0, dy=-60.0) -> dict
def set_note_text(root, index, text) -> dict
def remove_note(root, index) -> dict
```

Notes live under `PHYSICALWORKSPACE/NOTES`; `anchor_device` positions the note at the device's top-right corner and `dx/dy` are relative offsets.

```python
from ptforge import notes, edit

root = edit.load("lab.pkt")
notes.add_note(root, "10.0.0.254 / Gi0/0", x=0, y=0, anchor_device="R1")
notes.add_note(root, "PC1 10.0.0.11", x=0, y=0, anchor_device="PC1", dy=40)
edit.save(root, "lab_notes.pkt")
```

---

## ptforge.web

```python
def list_pages(path) -> dict
def read_page(path, device=None, name="index.html") -> dict
def set_page(path, html, *, device=None, name="index.html", out=None) -> dict
```

With `device=None` the first Server-PT is used. Pages live at `DEVICE/FILES/FILE[NAME=http:]/FILES/FILE[NAME=index.html]/FILE_CONTENT/TEXT`.

```python
from ptforge import web

web.set_page("web_lab.pkt", "<h1>Hello</h1>", device="S1", out="web_lab_custom.pkt")
print(web.read_page("web_lab_custom.pkt")["html"])
```

---

## ptforge.report

```python
def build_report(pkt, out_dir, *, figures=None, title=None) -> dict
```

`figures` is `[{"path": "figures/topology.png", "caption": "Logical topology"}]`; missing files are skipped. Returns `{dir, report, captions, devices, figures, addresses, links}`.

Output:

```
out_dir/
├── figures/
├── captions.json
└── report.md
```

---

## ptforge.doctor

```python
def environment() -> dict          # {"ok", "packet_tracer", "pillow", "supported_prefix", "issues"}
def verify_file(path) -> dict      # {"ok", "path", "version", "devices", "links", "bytes", "issues"}
def packet_tracer_path() -> Path   # reads PT_EXE, defaults to the 8.1.1 install path
```

`verify_file` only inspects the file (version prefix `8.1.`, presence of devices) and does not require PT to be installed. A corrupt file raises `DoctorError`.

---

## ptforge.runtime (Windows only)

Every function expects the matching PT window to be open and raises `ConsoleError` on failure.

```python
def exec_commands(device, commands, *, out=None, wait=1.2,
                  fx=0.5, fy=0.62, read=True) -> dict
def check_output(device, checks, *, wait=2.0) -> dict
def ping(device, target, *, count=4, wait=8.0) -> dict
def http_get(device, url, *, wait=3.0, out=None) -> dict
def ftp_session(device, server, *, username="cisco", password="cisco",
                commands=None, wait=3.0, out=None) -> dict
```

```python
from ptforge import runtime

out = runtime.exec_commands("R1", ["show ip route"], out="route.png")
print(out["output"][:400])

assert runtime.check_output("R1", [
    {"command": "show ip route", "contains": "O    10.0.0.0/24"},
])["ok"]

print(runtime.ping("PC1", "10.0.0.12"))   # {'sent','received','lost','loss_percent','ok',...}
```

- `exec_commands` inputs through the context-menu Paste, submits with Enter, reads the visible area back with drag-select + context-menu Copy, and also screenshots the window rectangle.
- `check_output` checks support `command` plus `contains` / `regex` / `not_contains`.
- `http_get` requires the device's Web Browser to be open (Desktop tab); it returns the page text in a `{ok, url, status, body, screenshot}` shape.
- `ftp_session` is prompt-driven: connect, `Username:`, `Password:`, `ftp>`, each command, `quit`; every step records `{step, sent, prompt, ok}`, and the transcript is the longest snapshot captured during the session.

---

## Exceptions

| Exception | Source |
| --- | --- |
| `SpecError` | Missing spec field or malformed `ipv4` |
| `ptfile.PacketTracerFormatError` | Not a valid container / authentication failed |
| `StateError` | Unknown device name |
| `EditError` / `PatchError` | Invalid edit target or operator |
| `NoteError` / `WebError` | Annotation or page structure mismatch |
| `DoctorError` | Unreadable file |
| `ConsoleError` | Runtime window/read-back failure (Windows only) |


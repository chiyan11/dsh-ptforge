# Python API

引擎是一个普通 Python 包，可以脱离 CLI 直接调用。下面所有签名都来自当前代码，返回结构是实际形状。

```python
pip install dsh-ptforge        # import 名仍是 ptforge
```

模块一览：

| 模块 | 职责 |
| --- | --- |
| `ptforge.spec` | 解析 JSON spec、自动布局 |
| `ptforge.build` | 组装文档（设备 + 链路），产出 `.pkt` |
| `ptforge.ptcrypto.ptfile` | 容器编解码（Twofish-EAX + zlib） |
| `ptforge.state` | 只读状态与断言 |
| `ptforge.edit` | 单设备编辑（IP、配置、改名） |
| `ptforge.patch` | 批量增量修改算子 |
| `ptforge.notes` | 画布标注 |
| `ptforge.web` | Server-PT 网页读写 |
| `ptforge.report` | 报告素材 |
| `ptforge.doctor` | 环境与文件版本检查 |
| `ptforge.runtime` | Windows 运行时（执行命令、ping、http、ftp） |
| `ptforge.gui` | 更底层的 Win32 原语（焦点、点击、截图、剪贴板） |

---

## ptforge.spec

```python
def load_spec(path: str | Path) -> dict
def parse_spec(data: dict) -> tuple[list[DeviceSpec], list[LinkSpec]]
def auto_layout(devices: list[DeviceSpec], *, spacing: float = 190.0) -> None
def build_from_spec(data: dict, out_path: str | Path) -> Path
```

`DeviceSpec` / `LinkSpec` 是 dataclass：

```python
DeviceSpec(name, model, x=None, y=None, config=[], start_config=[],
           ipv4: tuple[str, str, str] | None = None, port=None, physical=None)
LinkSpec(source, target, source_port=None, target_port=None, cable="straight")
```

`parse_spec` 会校验必填字段与设备名唯一性，错误抛 `SpecError`（`ValueError` 子类），消息里带设备名。

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

`DeviceHandle` 有 `name`、`model`、`ref`（`save-ref-id:N`）、`element`、`used_ports`。

```python
from ptforge.build import TopologyBuilder

b = TopologyBuilder()
b.add_device("2911", "R1", 200, 200,
             config=["hostname R1", "interface GigabitEthernet0/0",
                     "ip address 10.0.0.254 255.255.255.0"])
b.add_device("2960-24TT", "SW1", 400, 200)
b.add_device("PC-PT", "PC1", 200, 380, ipv4=("10.0.0.11", "255.255.255.0", "10.0.0.254"))
b.connect("R1", "SW1")            # 端口自动挑
b.connect("PC1", "SW1")
b.save("lab.pkt")
```

- `cable=None` 时按设备类别自动选线：同类（host/host、router/router、switch/switch）交叉线，其余直通线。
- `add_device` 会自动创建物理工作区节点；不要手工拼 `PHYSICAL`，除非你要复刻已有实验。
- `save` 内部走 `ptfile.encode_container`，写出来就是 PT 可加载的 `.pkt`。

---

## ptforge.ptcrypto.ptfile

```python
def decode(path: str | Path) -> ET.Element          # .pkt -> <PACKETTRACER5>
def encode(root: ET.Element, path: str | Path) -> Path
def decode_container(data: bytes) -> bytes          # 容器 -> XML bytes
def encode_container(xml: bytes) -> bytes           # XML bytes -> 容器
def looks_like_pkt(data: bytes) -> bool
```

```python
from ptforge.ptcrypto import ptfile

root = ptfile.decode("lab.pkt")
print(root.findtext("VERSION"), len(root.findall("NETWORK/DEVICES/DEVICE")))
ptfile.encode(root, "copy.pkt")
```

解不开时抛 `ptfile.PacketTracerFormatError`。XML 结构与 PT 强约束（物理工作区节点、`FROM/PORT/TO/PORT` 顺序）由 `build` 模块维护，手改 XML 请优先用 `edit` / `patch`。

---

## ptforge.state

```python
def load(path) -> ET.Element
def describe(root: ET.Element) -> dict
def device_state(root: ET.Element, name: str) -> dict
def check(root: ET.Element, expectations: list[dict]) -> dict
```

`device_state` 返回：

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

`check` 返回 `{ok, results: [{device, expect, ok, evidence, problems}]}`，支持的断言键：

```python
{"device": "R1", "route": "172.18.20.0/24"}
{"device": "R1", "interface": "Gi0/0", "ip": "10.0.0.254"}
{"device": "SW1", "interface": "Fa0/1", "access_vlan": 10}
{"device": "R1", "nat": "inside"}
{"device": "R1", "config_contains": "ip nat inside"}
```

设备不存在时抛 `StateError`，消息里列出所有可用设备名。

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

`set_config(replace=False)` 会按 `interface` / `router` / `line` 段合并，而不是整段覆盖；`rename` 同时改 `NAME`、`SYS_NAME` 与 `RUNNINGCONFIG` 里的 `hostname`。

---

## ptforge.patch

```python
def apply_ops(root, ops: list[dict]) -> dict        # {"ops": [被应用的算子摘要…]}
def patch_file(source, ops, *, out=None) -> dict    # {"path", "bytes", "ops"}
```

算子：

```python
{"op": "set_ipv4", "device": "PC1", "port": "FastEthernet0",
 "address": "10.0.0.21", "mask": "255.255.255.0", "gateway": "10.0.0.254"}
{"op": "set_config", "device": "R1", "lines": ["ip route 0.0.0.0 0.0.0.0 10.0.0.1"],
 "append": True}
{"op": "rename", "device": "R1", "name": "CORE"}
{"op": "set_switchport", "device": "SW1", "interface": "FastEthernet0/5", "vlan": 20}
{"op": "remove_config", "device": "R1", "match": "ip route 0.0.0.0"}
```

不传 `out` 时原地覆盖；建议传 `out` 保留原文件。

---

## ptforge.notes

```python
def notes(root) -> list[dict]                       # [{"uuid","x","y","z","text"}]
def add_note(root, text, *, x, y, z=None, anchor_device=None, dx=0.0, dy=-60.0) -> dict
def set_note_text(root, index, text) -> dict
def remove_note(root, index) -> dict
```

标注挂在 `PHYSICALWORKSPACE/NOTES` 下；`anchor_device` 会把标注定位到设备右上角，`dx/dy` 是相对偏移。

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

`device=None` 时取第一个 Server-PT。页面存在 `DEVICE/FILES/FILE[NAME=http:]/FILES/FILE[NAME=index.html]/FILE_CONTENT/TEXT`。

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

`figures` 是 `[{"path": "figures/topology.png", "caption": "逻辑拓扑"}]`；不存在的文件会被跳过。返回 `{dir, report, captions, devices, figures, addresses, links}`。

产出：

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
def packet_tracer_path() -> Path   # 读 PT_EXE，缺省用 8.1.1 默认路径
```

`verify_file` 只检查文件本身（版本前缀 `8.1.`、是否有设备），不要求本机装了 PT。文件损坏时抛 `DoctorError`。

---

## ptforge.runtime（仅 Windows）

所有函数都要求对应的 PT 窗口已经打开；失败统一抛 `ConsoleError`。

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

- `exec_commands` 通过右键 Paste 输入、回车提交、拖选 + 右键 Copy 回读可见区域，同时按窗口矩形截图。
- `check_output` 的 check 支持 `command` + `contains` / `regex` / `not_contains`。
- `http_get` 要求设备上 Web Browser 已打开（Desktop 标签页里点开），返回 `{ok, url, status, body, screenshot}` 形状的页面文本。
- `ftp_session` 是提示符驱动的：连接、`Username:`、`Password:`、`ftp>`、每条命令、`quit`，逐步骤记录 `{step, sent, prompt, ok}`，transcript 取会话中最长的一次快照。

---

## 异常速查

| 异常 | 来源 |
| --- | --- |
| `SpecError` | spec 字段缺失、ipv4 形状不对 |
| `ptfile.PacketTracerFormatError` | 不是合法容器 / 校验失败 |
| `StateError` | 设备名不存在 |
| `EditError` / `PatchError` | 编辑目标或算子不合法 |
| `NoteError` / `WebError` | 标注或页面结构不匹配 |
| `DoctorError` | 文件不可读 |
| `ConsoleError` | 运行时窗口/回读失败（仅 Windows） |


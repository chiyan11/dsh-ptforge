# ptforge

**Cisco Packet Tracer 自动化引擎 · DeepSeek Harness 插件**

> Packet Tracer 没有公开的自动化 API，也没有可编程接口进它的 CLI 引擎。ptforge 用两条互补的路径把这件事做通：
> **容器级离线编辑**（直接读写 `.pkt`，覆盖拓扑、连线、配置、网页、标注）+ **最小 GUI 运行时**（在真窗口里执行命令、拿到回显、做断言）。

`ptforge` 提供 18 个 `pt_*` 工具，覆盖「造拓扑 → 配设备 → 离线验收 → 真机验收 → 出报告」的完整闭环。

---

## 目录

- [为什么需要它](#为什么需要它)
- [能力矩阵](#能力矩阵)
- [架构](#架构)
- [安装](#安装)
- [快速开始](#快速开始)
- [工具参考](#工具参考)
- [命令行](#命令行)
- [验收与测试](#验收与测试)
- [已知边界](#已知边界)
- [目录结构](#目录结构)
- [第三方代码](#第三方代码)

---

## 为什么需要它

Packet Tracer 8.x 的 `PacketTracer.exe` 里没有 `PTAPI`、没有 socket 服务，`plugins/` 只接受 Cisco 签名的二进制插件，`extensions/*.pts` 是加密脚本。官方没有给外部程序留任何编程入口。

因此自动化只有两种可能：

| 路径 | 可行性 | ptforge 的取舍 |
| --- | --- | --- |
| GUI 自动化（点击画布、敲终端） | 可行但脆弱：需要窗口焦点、坐标随缩放/滚动变化、终端只能逐键输入 | 只保留**必要**的运行时能力（执行命令、回显、断言、业务动作），其余全部走离线 |
| 直接读写 `.pkt` | 可行：容器是 Twofish-EAX + zlib 压缩的 `<PACKETTRACER5>` XML | 作为主力：拓扑、连线、配置、网页、标注都在这里完成 |

等价地说：**能离线证明的，绝不开窗口；只有运行时才有的状态（路由表、NAT 翻译、连通性、页面内容），才走 GUI。**

---

## 能力矩阵

| 能力 | 方式 | 工具 |
| --- | --- | --- |
| 查询型号与接口名 | 离线 | `pt_models` |
| 从 JSON spec 生成拓扑 | 离线 | `pt_build` |
| 增量修改（IP / 配置 / 改名 / VLAN / 删配置） | 离线 | `pt_patch` |
| 给单台设备写 IOS 配置 | 离线 | `pt_apply` |
| 拓扑清单与端口解析 | 离线 | `pt_inspect` |
| 结构化状态读取（接口、静态路由、NAT、ACL、VLAN） | 离线 | `pt_state` |
| 对 `.pkt` 做断言 | 离线 | `pt_check` |
| 画布标注 | 离线 | `pt_note` |
| 读写 Server-PT 网页 | 离线 | `pt_server_page` |
| 环境与版本体检 | 离线 | `pt_doctor` |
| 报告素材（图 + 图注 + 表格） | 离线 | `pt_report` |
| 打开文件并置前 | 运行时 | `pt_open` |
| 窗口焦点 / 点击 / 输入 / 截图（逃生舱） | 运行时 | `pt_gui` |
| 执行命令并回读 transcript | 运行时 | `pt_exec` |
| 带断言执行命令 | 运行时 | `pt_assert` |
| ping 与统计解析 | 运行时 | `pt_ping` |
| 浏览器取页面正文 | 运行时 | `pt_http_get` |
| FTP 会话 | 运行时 | `pt_ftp` |

---

## 架构

```
                 spec.json
                     │
              ┌──────▼──────┐
              │  spec.py    │  解析 / 自动布局 / 自动选线 / 自动配端口
              └──────┬──────┘
                     │
              ┌──────▼──────┐        ptforge/assets/
              │  build.py   │◄─────── skeleton_8.1.1.xml
              │  catalog.py │         templates/*.xml (80 型号)
              └──────┬──────┘         port_names.json
                     │ ElementTree
              ┌──────▼──────┐
              │ ptfile.py   │  Twofish-EAX(zlib(level 6)) ⇄ <PACKETTRACER5>
              └──────┬──────┘
                     │ .pkt
        ┌────────────┴─────────────┐
        │                          │
   edit/state/patch/notes/    gui.py → 真 PT 窗口
   web/report/doctor          runtime.py（exec/assert/ping/http/ftp）
```

- **容器层**：`ptcrypto/`（twofish、CMAC、CTR、EAX 的 vendored 实现）+ `ptfile.py` 负责加解密与压缩；`build.py` 用 8.1.1 骨架和 80 个设备模板拼装文档，并维护物理工作区节点、SAVE_REF_ID、端口顺序、`FROM/PORT/TO/PORT` 等 PT 强制约束。
- **语义层**：`state.py`、`patch.py`、`edit.py`、`notes.py`、`web.py`、`report.py` 只依赖 ElementTree，可以做增量修改与断言。
- **运行时层**：`gui.py` 只用 ctypes 调 Win32，`runtime.py` 在其上实现「粘贴命令 → 回车 → 拖选 → 右键 Copy」的控制台读回。PT 终端不接受合成逐键输入，但接受**右键 Paste**；回读只能取可见区域，因此长会话会保留过程中最长的一次快照。

---

## 安装

### 依赖

- Windows 10/11（运行时工具依赖 Win32 窗口 API）
- Cisco Packet Tracer **8.1.x**（文件版本需 `8.1.*`，`pt_doctor` 会校验）
- DeepSeek Harness（插件宿主）
- Python 3.10+，`lxml`、`Pillow`（DSH 自带运行时已包含）

### 以 DSH bundle 安装

```powershell
# 在 DSH 会话中
plugin_manager install_bundle target="D:\coding\daily\dsh-ptforge\packages\dsh-ptforge"
```

安装后 18 个 `pt_*` 工具会出现在工具列表里。插件把引擎副本打进包内，运行时不依赖仓库目录。

### 从源码使用

```powershell
cd D:\coding\daily\dsh-ptforge
$env:PYTHONPATH = (Get-Location).Path
python -m ptforge doctor
python -m ptforge models --query 2960
```

---

## 快速开始

### 1. 用 spec 生成拓扑

```json
{
  "name": "office_lan",
  "devices": [
    {"model": "2911", "name": "R1",
     "config": ["hostname R1", "ip route 0.0.0.0 0.0.0.0 192.168.10.254"]},
    {"model": "2960-24TT", "name": "SW1",
     "config": ["hostname SW1", "vlan 10", "name USERS",
                "interface FastEthernet0/1", "switchport mode access",
                "switchport access vlan 10"]},
    {"model": "PC-PT", "name": "PC0", "ipv4": "192.168.10.10/24,192.168.10.1"},
    {"model": "PC-PT", "name": "PC1", "ipv4": "192.168.10.11/24,192.168.10.1"}
  ],
  "links": [
    {"from": "R1",  "to": "SW1"},
    {"from": "PC0", "to": "SW1"},
    {"from": "PC1", "to": "SW1"}
  ]
}
```

```powershell
python -m ptforge build fixtures\specs\office_lan.json -o office_lan.pkt
python -m ptforge inspect office_lan.pkt
```

- 不写端口 → 自动找空闲口；不写 `cable` → 同类设备交叉线、异类直通线；不写坐标 → 自动布局。
- `ipv4` 支持 `"ip/prefix,gw"`、`"ip mask gw"`、`[ip, mask, gw]`、`{address, mask, gateway}`。

### 2. 离线验收

```powershell
python -m ptforge check office_lan.pkt --expect '[{"device":"R1","interface":"Gi0/0","ip":"192.168.10.1"}]'
python -m ptforge state office_lan.pkt
```

### 3. 真机验收（可选）

先 `python -m ptforge open office_lan.pkt`，双击设备打开控制台，然后：

```powershell
python -m ptforge.guitool exec R1 "show ip route" --out route.png
python -m ptforge.guitool assert PC0 --checks '[{"command":"ipconfig","contains":"192.168.10.10"}]'
```

### 4. 出报告素材

```powershell
python -m ptforge report office_lan.pkt -o report --title "实验室验收报告" `
  --figure '{"path":"figures/topology.png","caption":"逻辑拓扑"}'
```

产出 `report/figures/`、`report/captions.json`、`report/report.md`。

---

## 工具参考

完整的参数、例子与流水线见 **[docs/TOOLS.md](docs/TOOLS.md)**。离线与运行时的分工：

| 类别 | 工具 |
| --- | --- |
| 构建 | `pt_models` `pt_build` `pt_open` |
| 修改 | `pt_patch` `pt_apply` `pt_note` `pt_server_page` |
| 读取 / 校验 | `pt_inspect` `pt_state` `pt_check` `pt_doctor` `pt_report` |
| 运行时 | `pt_gui` `pt_exec` `pt_assert` `pt_ping` `pt_http_get` `pt_ftp` |

---

## 命令行

`python -m ptforge` 子命令：`models` `build` `inspect` `apply` `patch` `state` `check` `note` `web` `doctor` `report` `demo` `open`，全部支持 `--json`。

`python -m ptforge.guitool` 子命令：`focus` `click` `type` `key` `shot` `paste` `copy` `clipboard` `exec` `assert` `ping` `http` `ftp`。

---

## 验收与测试

```powershell
python -m unittest discover -s tests     # 16 tests, OK
```

| 场景 | 结果 |
| --- | --- |
| 容器往返（真实 8.3.pkt，252 708 B） | 解密 → 重新加密 → PT 正常打开，22 台设备完整渲染 |
| 8.1.1 空骨架 | `fixtures/empty81.pkt` 34 234 B → 668 605 B XML，作为生成器基线 |
| 生成拓扑 + PT 重存 + 重开 | 通过（物理工作区节点、GUID 链、`FROM/PORT/TO/PORT` 顺序均已修正） |
| 端口命名 | 2911 `Gi0/0..0/2`、2960-24TT `FE0/1..0/24 + Gi0/1..0/2`、ISR4331 `Gi0/0/0..0/0/2`、PC-PT `FastEthernet0` |
| 命令行执行 | PC0 `ipconfig` 取回 305 字符；`ping 192.1.1.254` 回 4/4、0% 丢包 |
| 断言 | `show ip route` 命中 `O 192.1.3.0/24`、`[110/4] via 192.1.2.253`；故意断言不存在网段得到明确 FAIL |
| NAT 实验（`nat_lab.pkt`） | 6/6 离线断言 PASS；RIP 路由 `R 172.18.20.0 [120/2]`；静态 NAT `tcp 200.1.13.1:80 → 172.16.10.4:80`；PC4 访问 `http://200.1.13.1` 返回 Web1_Server 页面 |

---

## 已知边界

1. **没有官方 API**：运行时能力建立在窗口自动化上，要求 PT 窗口可见、可交互，且桌面前台可被抢占。
2. **终端只回读可见区域**：超长输出会滚出屏幕，`ftp`/长配置会保留会话中最长的一次快照；逐条命令建议加 `wait_ms`。
3. **同名设备歧义**：多个 PT 实例里存在同名设备时，需要先关闭重复实例或改名。
4. **文件版本**：只保证 `8.1.x`；其他版本的容器参数可能不同（`pt_doctor` 会先检查）。
5. **图形界面差异**：不同 PT 版本/缩放比例下，设备窗口内的相对坐标（标签页、URL 栏、Go 按钮）可能需要微调。

---

## 目录结构

```
dsh-ptforge/
├── ptforge/                 # 引擎（可独立作为 Python 包使用）
│   ├── ptcrypto/            # Twofish / CMAC / CTR / EAX / 容器格式
│   ├── assets/              # 8.1.1 骨架、80 个设备模板、端口命名表
│   ├── build.py             # spec → ElementTree → .pkt
│   ├── state.py             # 结构化状态与断言
│   ├── patch.py             # 增量修改
│   ├── notes.py             # 画布标注
│   ├── web.py               # Server-PT 网页读写
│   ├── report.py            # 报告素材
│   ├── gui.py / runtime.py  # Win32 运行时
│   └── cli.py / guitool.py  # 命令行入口
├── packages/dsh-ptforge/    # DSH bundle（含引擎副本）
├── docs/TOOLS.md            # 18 个工具速查表
├── tests/                   # 16 个单测
├── fixtures/                # 样例与 spec
└── scripts/sync_engine.ps1  # 把引擎同步进 bundle
```

---

## 第三方代码

`ptforge/ptcrypto/twofish.py` 来自 [strykey/pka-decipher](https://github.com/strykey/pka-decipher)，其内部保留了原始 Twofish 实现的版权声明（Gladman / Paulo S. L. M. Barreto）。`ptcrypto/` 下的 CMAC/CTR/EAX 与容器格式实现同样源自该仓库。

上游仓库未提供 LICENSE 文件；如果你要分发衍生版本，请先确认上游授权。本项目自身的代码可视为与研究/学习用途的参考实现。

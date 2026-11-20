# ptforge

[English](README.md)

**用代码画 Cisco Packet Tracer 的图：造拓扑、配设备、做断言、出报告。**

[![ci](https://github.com/chiyan11/dsh-ptforge/actions/workflows/ci.yml/badge.svg)](https://github.com/chiyan11/dsh-ptforge/actions/workflows/ci.yml)
[![pypi](https://img.shields.io/pypi/v/dsh-ptforge.svg)](https://pypi.org/project/dsh-ptforge/)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

```powershell
pip install dsh-ptforge
ptforge demo -o office.pkt          # 生成一份 3 设备的小实验并打印清单
```

三行就能拿到一个 Packet Tracer 8.1 能直接打开的 `.pkt`。想从 spec 描述整张网、批量改配置、在真机窗口里跑 `show` 命令、或者把结果整理成报告，继续往下看。

---

## 它解决什么问题

Packet Tracer 没有公开 API：`PacketTracer.exe` 里没有 `PTAPI`，`plugins/` 只认 Cisco 签名的二进制，`extensions/*.pts` 是加密脚本。所以外部程序只有两条路：

| 路径 | 现实 | ptforge 的取舍 |
| --- | --- | --- |
| 点画布、敲终端 | 能做，但依赖窗口焦点、坐标随缩放漂移、终端只认右键粘贴 | 只保留**必要**的运行时能力 |
| 直接读写 `.pkt` | 容器是 Twofish-EAX + zlib 的 `<PACKETTRACER5>` XML | 作为主力：拓扑/连线/配置/网页/标注全在这里 |

一句话：**能离线证明的绝不开窗口；只有运行时才有的状态（路由表、NAT 翻译、连通性、页面内容）才走 GUI。**

## 能做什么

| 你想做的事 | 用什么 |
| --- | --- |
| 用 JSON 描述一张网并生成 `.pkt` | `pt_build` / `ptforge build` |
| 查型号、查接口名、查空闲端口 | `pt_models` / `ptforge models` |
| 看拓扑清单、每条链路接在哪两个口 | `pt_inspect` |
| 改 IP、加 VLAN、改主机名、删配置 | `pt_patch` / `pt_apply` |
| 读结构化状态（接口、静态路由、NAT、ACL） | `pt_state` |
| 对 `.pkt` 做断言（离线 CI 也能跑） | `pt_check` |
| 在画布上加 IP / 端口标注 | `pt_note` |
| 改 Server-PT 的网页 | `pt_server_page` |
| 用真 PT 窗口执行 `show` 命令并回读 | `pt_exec` / `pt_assert` |
| ping / 打开网页 / FTP | `pt_ping` / `pt_http_get` / `pt_ftp` |
| 生成「图 + 图注 + 表格」的报告素材 | `pt_report` |

共 18 个工具，离线 12 个、运行时 6 个。完整参数见 [docs/TOOLS.zh-CN.md](docs/TOOLS.zh-CN.md)。

## 安装

| 方式 | 适合 | 命令 |
| --- | --- | --- |
| pip | 写脚本、CI、容器 | `pip install dsh-ptforge` |
| DSH bundle | 在 DeepSeek Harness 会话里直接调工具 | `plugin_manager install_bundle target="…/packages/dsh-ptforge"` |
| Docker | Linux 上跑离线半边 | `docker build -t ptforge:0.1.0 .` |

```powershell
pip install "dsh-ptforge[gui]"   # 需要 pt_exec / pt_ping / pt_http_get 时加 Pillow
```

- 核心引擎**零第三方依赖**，Python 3.10+ 即可。
- 运行时工具只在 Windows 有效，且需要 Packet Tracer **8.1.x** 与一个可交互的桌面。
- PyPI 分发名是 `dsh-ptforge`（`ptforge` 已被无关项目占用），import 名与命令仍是 `ptforge`。

## 五分钟上手

### 1. 写一个 spec

```json
{
  "name": "branch",
  "devices": [
    {"model": "2911", "name": "R1",
     "config": ["hostname R1", "interface GigabitEthernet0/0",
                "ip address 10.10.0.254 255.255.255.0", "no shutdown"]},
    {"model": "2960-24TT", "name": "SW1", "config": ["hostname SW1"]},
    {"model": "PC-PT", "name": "PC1", "ipv4": "10.10.0.11/24,10.10.0.254"},
    {"model": "PC-PT", "name": "PC2", "ipv4": "10.10.0.12/24,10.10.0.254"}
  ],
  "links": [
    {"from": "R1", "to": "SW1"},
    {"from": "PC1", "to": "SW1"},
    {"from": "PC2", "to": "SW1"}
  ]
}
```

端口、线型、坐标都不用写：自动配空闲口、同类设备交叉线、异类直通线、自动布局。

### 2. 生成并检查

```powershell
ptforge build branch.json -o branch.pkt
ptforge inspect branch.pkt
ptforge check branch.pkt --expect '[{"device":"PC1","interface":"FastEthernet0","ip":"10.10.0.11"}]'
```

### 3. 在 Packet Tracer 里打开

```powershell
ptforge open branch.pkt
```

或者直接双击 `.pkt`。文件是 8.1.1 格式，生成后可以继续在 PT 里手改、再存回来。

### 4. 真机验证（可选）

先在 PT 里双击设备、打开 Desktop → Command Prompt，然后：

```powershell
ptforge-gui exec PC1 "ipconfig"
ptforge-gui ping PC1 10.10.0.12
ptforge-gui assert R1 --checks '[{"command":"show ip route","contains":"10.10.0.0/24"}]'
```

### 5. 出报告

```powershell
ptforge report branch.pkt -o report --title "分支网络验收"
```

得到 `report/figures/`、`report/captions.json`、`report/report.md`。

## 三种调用方式

**命令行**（脚本、CI、容器）

```powershell
ptforge build lab.json -o lab.pkt
ptforge state lab.pkt --device R1
ptforge patch lab.pkt --ops '[{"op":"set_ipv4","device":"PC1","port":"FastEthernet0","address":"10.10.0.21"}]'
```

**Python API**（想嵌进自己的工具链）

```python
from ptforge import spec, state, report

spec.build_from_spec(data, "lab.pkt")
root = state.load("lab.pkt")
result = state.check(root, [{"device": "R1", "route": "10.10.0.0/24"}])
print(result["ok"], result["results"])
report.build_report("lab.pkt", "report")
```

完整签名与返回结构：[docs/API.zh-CN.md](docs/API.zh-CN.md)。

**DSH 工具**（在 DeepSeek Harness 会话里让 AI 直接调）

```
pt_build(spec={...}, open=true)
pt_assert(device="R1", checks=[{"command": "show ip route", "contains": "O 10.10.0.0/24"}])
```

## 示例

[`examples/`](examples) 里有可直接运行的脚本：

| 脚本 | 演示 |
| --- | --- |
| `01_build_and_check.py` | spec → `.pkt` → 结构化状态 → 断言 |
| `02_patch_and_state.py` | 增量改 IP / 改主机名，再读回状态 |
| `03_report.py` | 生成报告素材并打印摘要 |

```powershell
python examples/01_build_and_check.py
```

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/QUICKSTART.zh-CN.md](docs/QUICKSTART.zh-CN.md) | 从零到第一个可验收实验的完整走查 |
| [docs/API.zh-CN.md](docs/API.zh-CN.md) | Python API：签名、返回结构、异常 |
| [docs/TOOLS.zh-CN.md](docs/TOOLS.zh-CN.md) | 18 个 DSH 工具的速查表 |

## 已知边界

1. **没有官方 API**：运行时能力建立在窗口自动化上，需要 PT 窗口可见、可交互、能被置前。
2. **终端只回读可见区域**：超长输出会滚出屏幕；长会话会保留过程中最长的一次快照。
3. **同名设备歧义**：多个 PT 实例存在同名设备时，先关闭重复实例或改名。
4. **只保证 8.1.x**：其他版本容器参数可能不同，`pt_doctor` 会先检查文件版本。
5. **界面坐标有版本差异**：不同 PT 版本/缩放比例下，设备窗口里的相对坐标可能需要微调。

## 开发

```powershell
python -m unittest discover -s tests     # 22 个单测，无需 Packet Tracer
powershell -File scripts\sync_engine.ps1 # 改完引擎后同步进 DSH bundle
```

CI（[ci.yml](.github/workflows/ci.yml)）在 Python 3.10/3.11/3.12 上跑单测与 CLI 冒烟，构建 wheel 并断言资产完整，再构建容器镜像。发布走 [publish.yml](.github/workflows/publish.yml) 的 Trusted Publishing，仓库里不存 PyPI token。

## 免责声明

- **与 Cisco 无关。** 本项目是独立项目。Cisco、Cisco Packet Tracer、IOS 及相关标识是 Cisco Systems, Inc. 的商标；本项目未获得 Cisco 的认可、赞助或支持。
- **请自备正版 Packet Tracer。** 运行时工具驱动的是你本机安装、合法授权的 Cisco Packet Tracer。你需要自行遵守 Cisco 的许可条款、所在机构的规定和当地法律。本项目不绕过任何许可、认证或访问控制，也不分发 Cisco 软件或课程内容。
- **风险自担。** 代码按 MIT 许可提供，不附带任何担保。离线操作会重写 `.pkt` 文件；运行时操作会向前台窗口注入合成的鼠标/键盘输入。请先备份实验文件、在副本上操作，优先使用可丢弃的虚拟机或快照；不要在共享机器上无人值守地运行运行时工具。
- **只为互操作。** `.pkt` 是未公开的容器格式，IOS 命令是事实接口，本项目仅在教学与研究中用于互操作。生成的文件可能被其他版本或构建的 Packet Tracer 拒绝。
- **禁止网络滥用。** `pt_ping`、`pt_http_get`、`pt_ftp` 只在你自己的 Packet Tracer 仿真环境内工作，不要指向你无权测试的真实基础设施。
- **第三方代码。** 内置的 Twofish/EAX 实现有单独的来源与授权说明，见 [NOTICE](NOTICE)。

## 许可

本项目代码为 MIT（见 [LICENSE](LICENSE)）。`ptforge/ptcrypto/` 下的 Twofish/EAX 实现来自 [strykey/pka-decipher](https://github.com/strykey/pka-decipher)，上游没有 LICENSE，**不在 MIT 范围内**，商业分发前请替换或取得授权——细节见 [NOTICE](NOTICE)。




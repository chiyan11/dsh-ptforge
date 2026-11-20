# ptforge

**Draw Cisco Packet Tracer topologies in code: build labs, configure devices, assert on them, collect report material.**

[![ci](https://github.com/chiyan11/dsh-ptforge/actions/workflows/ci.yml/badge.svg)](https://github.com/chiyan11/dsh-ptforge/actions/workflows/ci.yml)
[![pypi](https://img.shields.io/pypi/v/dsh-ptforge.svg)](https://pypi.org/project/dsh-ptforge/)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[中文文档](README.zh-CN.md)

```powershell
pip install dsh-ptforge
ptforge demo -o office.pkt          # generates a 3-device lab and prints a summary
```

Two lines and you have a `.pkt` that Packet Tracer 8.1 opens directly. From there you can describe a whole network as JSON, patch an existing file, run `show` commands in a real PT window, or turn the result into a report.

---

## Why it exists

Packet Tracer ships no public API: `PacketTracer.exe` contains no `PTAPI`, `plugins/` only loads Cisco-signed binaries, and `extensions/*.pts` are encrypted scripts. So an external program has exactly two paths:

| Path | Reality | What ptforge does with it |
| --- | --- | --- |
| Click the canvas, type in the console | Works, but depends on window focus, drifts with zoom, and the terminal only accepts clipboard paste via the context menu | Kept only for the **runtime** facts that exist nowhere else |
| Read and write `.pkt` directly | The container is Twofish-EAX + zlib around a `<PACKETTRACER5>` XML document | The main engine: topology, links, config, web pages, annotations |

In one sentence: **anything provable offline never opens a window; only runtime state (routing tables, NAT translations, reachability, page content) goes through the GUI.**

## What it can do

| What you want | What to use |
| --- | --- |
| Describe a network as JSON and generate a `.pkt` | `pt_build` / `ptforge build` |
| Look up models, interface names, free ports | `pt_models` / `ptforge models` |
| Print a topology inventory, see which port each link lands on | `pt_inspect` |
| Change an IP, add a VLAN, rename a device, drop config | `pt_patch` / `pt_apply` |
| Read structured state (interfaces, static routes, NAT, ACLs) | `pt_state` |
| Assert on a `.pkt` (works in offline CI too) | `pt_check` |
| Label the canvas with IPs and port names | `pt_note` |
| Replace a Server-PT web page | `pt_server_page` |
| Run `show` commands in a real PT window and read the output back | `pt_exec` / `pt_assert` |
| ping / open a page / FTP | `pt_ping` / `pt_http_get` / `pt_ftp` |
| Produce "figure + caption + table" report material | `pt_report` |

18 tools in total: 12 offline, 6 runtime. Full parameter reference: [docs/TOOLS.md](docs/TOOLS.md).

## Install

| Way | Good for | Command |
| --- | --- | --- |
| pip | scripts, CI, containers | `pip install dsh-ptforge` |
| DSH bundle | calling the tools inside a DeepSeek Harness session | `plugin_manager install_bundle target="…/packages/dsh-ptforge"` |
| Docker | the offline half on Linux | `docker build -t ptforge:0.1.0 .` |

```powershell
pip install "dsh-ptforge[gui]"   # adds Pillow, needed by pt_exec / pt_ping / pt_http_get
```

- The core engine has **zero third-party dependencies** and only needs Python 3.10+.
- Runtime tools are Windows-only and require Packet Tracer **8.1.x** plus an interactive desktop.
- The PyPI distribution is named `dsh-ptforge` (`ptforge` was already taken by an unrelated project); the import name and the command are still `ptforge`.

## Quick start

### 1. Write a spec

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

Ports, cable types and coordinates are optional: free ports are picked automatically, same-kind devices get a crossover cable, different kinds get a straight-through cable, and layout is automatic.

### 2. Build and inspect

```powershell
ptforge build branch.json -o branch.pkt
ptforge inspect branch.pkt
ptforge check branch.pkt --expect '[{"device":"PC1","interface":"FastEthernet0","ip":"10.10.0.11"}]'
```

### 3. Open it in Packet Tracer

```powershell
ptforge open branch.pkt
```

Or double-click the `.pkt`. The file is 8.1.1 format, so you can keep editing it by hand and save it back.

### 4. Verify at runtime (optional)

In PT, double-click a device and open Desktop → Command Prompt, then:

```powershell
ptforge-gui exec PC1 "ipconfig"
ptforge-gui ping PC1 10.10.0.12
ptforge-gui assert R1 --checks '[{"command":"show ip route","contains":"10.10.0.0/24"}]'
```

### 5. Produce a report

```powershell
ptforge report branch.pkt -o report --title "Branch acceptance"
```

You get `report/figures/`, `report/captions.json` and `report/report.md`.

## Three ways to call it

**Command line** (scripts, CI, containers)

```powershell
ptforge build lab.json -o lab.pkt
ptforge state lab.pkt --device R1
ptforge patch lab.pkt --ops '[{"op":"set_ipv4","device":"PC1","port":"FastEthernet0","address":"10.10.0.21"}]'
```

**Python API** (embed it in your own tooling)

```python
from ptforge import spec, state, report

spec.build_from_spec(data, "lab.pkt")
root = state.load("lab.pkt")
result = state.check(root, [{"device": "R1", "route": "10.10.0.0/24"}])
print(result["ok"], result["results"])
report.build_report("lab.pkt", "report")
```

Full signatures and return shapes: [docs/API.md](docs/API.md).

**DSH tools** (let an AI call it inside a DeepSeek Harness session)

```
pt_build(spec={...}, open=true)
pt_assert(device="R1", checks=[{"command": "show ip route", "contains": "O 10.10.0.0/24"}])
```

## Examples

[`examples/`](examples) contains runnable scripts:

| Script | Shows |
| --- | --- |
| `01_build_and_check.py` | spec → `.pkt` → structured state → assertions |
| `02_patch_and_state.py` | incremental edit of IP / hostname, then read state back |
| `03_report.py` | generate report material and print a summary |

```powershell
python examples/01_build_and_check.py
```

## Documentation

| Doc | Content |
| --- | --- |
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | End-to-end walkthrough from zero to a verified lab |
| [docs/API.md](docs/API.md) | Python API: signatures, return shapes, exceptions |
| [docs/TOOLS.md](docs/TOOLS.md) | Cheat sheet for the 18 DSH tools |
| [README.zh-CN.md](README.zh-CN.md) | Chinese README |

## Known limits

1. **No official API**: runtime capabilities are built on window automation, so PT must be visible, interactive and brought to the foreground.
2. **The console can only copy what is visible**: very long output scrolls away; long sessions keep the longest snapshot captured during the run.
3. **Same-name devices are ambiguous**: if two PT instances each have a `PC0`, close the duplicate or rename the device.
4. **8.1.x only**: other versions may use different container parameters; `pt_doctor` checks the file version first.
5. **UI coordinates vary between versions**: relative coordinates inside a device window may need small adjustments for a different PT build or zoom level.

## Development

```powershell
python -m unittest discover -s tests     # 22 tests, no Packet Tracer needed
powershell -File scripts\sync_engine.ps1 # after changing the engine, sync it into the DSH bundle
```

CI ([ci.yml](.github/workflows/ci.yml)) runs the tests on Python 3.10/3.11/3.12, smokes the CLI and the examples, builds the wheel and checks the asset bank, then builds the container image. Publishing goes through [publish.yml](.github/workflows/publish.yml) with Trusted Publishing — no PyPI token is stored in the repository.

## License

The project code is MIT (see [LICENSE](LICENSE)). The Twofish/EAX implementation under `ptforge/ptcrypto/` comes from [strykey/pka-decipher](https://github.com/strykey/pka-decipher); the upstream project has no LICENSE and that code is **not** covered by MIT — replace it or obtain permission before commercial distribution, see [NOTICE](NOTICE).

Not affiliated with Cisco; Packet Tracer is their trademark. The `.pkt` container format and IOS command syntax are undocumented interfaces, used here only for interoperability in teaching and research.

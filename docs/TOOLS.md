# ptforge tool cheat sheet

18 `pt_*` tools in two groups: **offline** (only read/write `.pkt`, no Packet Tracer needed) and **runtime** (drive a real PT window, read the console back).

[中文版](TOOLS.zh-CN.md)

---

## 1. Offline: build and modify

| Tool | What it does | Key parameters | Example |
|---|---|---|---|
| `pt_models` | List available models and interface names | `query?`, `limit?` | `{query:"2960"}` |
| `pt_build` | Generate a `.pkt` from a JSON spec | `spec` or `spec_path`, `out?`, `open?` | see below |
| `pt_open` | Open a `.pkt` in PT and bring it to the front | `file`, `timeout_seconds?` | `{file:"lab.pkt"}` |
| `pt_patch` | Incremental edits: IP, config, rename, VLAN, remove config | `file`, `ops[]`, `out?` | `{file, ops:[{op:"set_ipv4",device:"PC0",address:"192.168.10.10",gateway:"192.168.10.1"}]}` |
| `pt_apply` | Write IOS config or a static IP to one device | `file`, `device`, `lines[]`/`lines_file`, `ip/mask/gateway/port?`, `out?` | `{file, device:"R1", lines:["ip route 0.0.0.0 0.0.0.0 10.0.0.1"]}` |
| `pt_note` | Add/update/remove canvas annotations | `file`, `action`, `text?`, `device?`, `x/y?`, `dx/dy?`, `index?`, `out?` | `{file, action:"add", device:"PC0", text:"PC0 10.0.0.10 / Fa0"}` |
| `pt_server_page` | Read/write a Server-PT web page | `file`, `action(list/get/set)`, `device?`, `name?`, `html?`/`html_file?`, `out?` | `{file, action:"set", html:"<h1>demo</h1>"}` |

### Minimal spec

```json
{
  "name": "demo",
  "devices": [
    {"model": "2911", "name": "R1", "config": ["hostname R1", "ip route 0.0.0.0 0.0.0.0 192.168.10.254"]},
    {"model": "2960-24TT", "name": "SW1", "config": ["hostname SW1"]},
    {"model": "PC-PT", "name": "PC0", "ipv4": "192.168.10.10/24,192.168.10.1"}
  ],
  "links": [{"from": "R1", "to": "SW1"}, {"from": "PC0", "to": "SW1"}]
}
```

- `ipv4` accepts `"192.168.10.10/24,192.168.10.1"`, `"192.168.10.10 255.255.255.0 192.168.10.1"`, `[ip, mask, gw]` or `{address,mask,gateway}`.
- Links without ports pick free ports automatically; without `cable`, same-kind devices get a crossover and different kinds a straight-through.
- Without `x/y`, layout is automatic.

---

## 2. Offline: read and verify

| Tool | What it does | Key parameters | Example |
|---|---|---|---|
| `pt_inspect` | Device / position / interface / link inventory | `file`, `config_lines?` | `{file:"lab.pkt"}` |
| `pt_state` | Structured state: interface IPs, static routes, NAT, ACLs, VLANs | `file`, `device?` | `{file:"lab.pkt", device:"R1"}` |
| `pt_check` | Assert on a `.pkt` | `file`, `expect[]` | `{file, expect:[{device:"R1", route:"172.18.20.0/24"},{device:"SW1", interface:"Fa0/1", access_vlan:10}]}` |
| `pt_doctor` | Environment and file-version check | `file?` | `{}` |
| `pt_report` | Report material: `figures/` + `captions.json` + `report.md` | `file`, `out_dir?`, `title?`, `figures?` | `{file:"lab.pkt", out_dir:"report"}` |

Assertion keys supported by `pt_check`: `route`, `interface` (with `ip` or `access_vlan`), `nat`, `config_contains`.

---

## 3. Runtime: needs a PT window

Prerequisite: PT has the `.pkt` open; the target device window is open (double-click it — PCs use Desktop → Command Prompt / Web Browser, routers the CLI tab); the desktop is interactive.

| Tool | What it does | Key parameters | Example |
|---|---|---|---|
| `pt_gui` | Low-level escape hatch: focus/click/type/screenshot/paste/copy | `action`, `title?`, `x/y?`, `double?`, `text?`, `keys?`, `path?`, `region?`, `enter?` | `{action:"shot", path:"topo.png"}` |
| `pt_exec` | Run commands, read the transcript back, take a screenshot | `device`, `commands[]`, `out?`, `wait_ms?`, `read?` | `{device:"R1", commands:["show ip route"]}` |
| `pt_assert` | Run commands and assert on the output | `device`, `checks[]`, `wait_ms?` | `{device:"R1", checks:[{command:"show ip route", contains:"O    192.1.3.0/24"}]}` |
| `pt_ping` | ping and parse the statistics | `device`, `target`, `count?`, `wait_ms?` | `{device:"PC0", target:"192.1.1.254"}` |
| `pt_http_get` | Fetch a page body through the PT browser | `device`, `url`, `out?`, `wait_ms?` | `{device:"PC0", url:"http://192.168.10.2"}` |
| `pt_ftp` | Prompt-driven FTP session | `device`, `server`, `username?`, `password?`, `commands?`, `out?`, `wait_ms?` | `{device:"PC0", server:"192.168.10.2", commands:["dir"]}` |

`pt_assert` checks support `contains`, `regex`, `not_contains` (multi-line search over the whole transcript).

---

## 4. Typical pipeline

```
pt_models → pt_build(open:true) → pt_inspect        # build a topology
pt_patch / pt_apply / pt_note / pt_server_page      # change it
pt_check / pt_state / pt_doctor                     # offline acceptance
pt_open → pt_exec / pt_assert / pt_ping / pt_http_get / pt_ftp   # runtime acceptance
pt_report                                           # report material
```

## 5. Boundaries

- Console read-back only captures the **visible area**; long sessions keep the longest snapshot seen during the run.
- Same-name devices across multiple PT instances are ambiguous — close the duplicate or rename the device.
- `pt_open` starts a new PT instance per file; opening succeeded only when the window title contains the file name.
- Files must be 8.1.x (`pt_doctor` checks this).

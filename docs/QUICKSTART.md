# Quick start

From nothing to "a lab you can verify" in about ten minutes. Commands use PowerShell; substitute your platform's Python invocation where needed.

[中文版](QUICKSTART.zh-CN.md)

---

## 0. Prerequisites

| Need | Notes |
| --- | --- |
| Python 3.10+ | Packet Tracer is not needed for the offline half |
| Packet Tracer 8.1.x | Needed to open files and run runtime commands; default path `D:\Cisco Packet Tracer 8.1.1\bin\PacketTracer.exe`, override with `PT_EXE` |
| Pillow | Only `pt_exec` / `pt_ping` / `pt_http_get` / `pt_ftp` need it: `pip install "dsh-ptforge[gui]"` |

Check the environment:

```powershell
ptforge doctor
```

A healthy output contains `packet tracer: D:\...\PacketTracer.exe`. Without PT you can continue — the offline half is unaffected; only `open` / `exec` are unavailable.

---

## 1. Write a spec

Create `branch.json`:

```json
{
  "name": "branch",
  "devices": [
    {"model": "2911", "name": "R1",
     "config": ["hostname R1",
                "interface GigabitEthernet0/0",
                "ip address 10.10.0.254 255.255.255.0",
                "no shutdown"]},
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

Three fields you can omit:

| Field | When omitted |
| --- | --- |
| `x` / `y` | Layout by role (routers on one row, switches on the next, end devices below) |
| `a_port` / `b_port` (link ports) | The first free port is picked automatically |
| `cable` | Same-kind devices (PC-PC, router-router, switch-switch) get a crossover cable, everything else a straight-through cable |

`ipv4` accepts four forms:

```json
"ipv4": "10.10.0.11/24,10.10.0.254"
"ipv4": "10.10.0.11 255.255.255.0 10.10.0.254"
"ipv4": ["10.10.0.11/24", "10.10.0.254"]
"ipv4": {"address": "10.10.0.11", "mask": "255.255.255.0", "gateway": "10.10.0.254"}
```

Look up models and interface names:

```powershell
ptforge models --query 2960
ptforge models --query 2911
```

---

## 2. Build, inspect, open

```powershell
ptforge build branch.json -o branch.pkt
ptforge inspect branch.pkt
```

`inspect` prints devices, positions, interfaces and both port names of every link. Then assert offline:

```powershell
ptforge check branch.pkt --expect '[{"device":"R1","interface":"GigabitEthernet0/0","ip":"10.10.0.254"}]'
```

It returns `PASS 1/1` or per-item problems. Supported keys:

| Key | Example |
| --- | --- |
| `route` | `{"device":"R1","route":"172.18.20.0/24"}` |
| `interface` + `ip` | `{"device":"R1","interface":"Gi0/0","ip":"10.10.0.254"}` |
| `interface` + `access_vlan` | `{"device":"SW1","interface":"Fa0/1","access_vlan":10}` |
| `nat` | `{"device":"R1","nat":"inside"}` |
| `config_contains` | `{"device":"R1","config_contains":"ip nat inside"}` |

Open it:

```powershell
ptforge open branch.pkt
```

> `ptforge open` requires PT to be installed. You can also just double-click the `.pkt`.

---

## 3. Runtime verification

This is the only step that needs a Packet Tracer window. The flow is fixed:

1. `ptforge open branch.pkt` opens the file and brings it to the front;
2. **Double-click a device** on the canvas to open its window;
3. PCs use `Desktop → Command Prompt`; routers/switches use the `CLI` tab (press Enter once if the prompt is not ready);
4. Keep the window open and run the commands below.

```powershell
ptforge-gui exec R1 "show ip route"
ptforge-gui exec PC1 "ipconfig" --out pc1.png
ptforge-gui ping PC1 10.10.0.12
ptforge-gui assert R1 --checks '[{"command":"show ip route","contains":"10.10.0.0/24"}]'
```

Practical constraints:

- Commands are entered through the **context-menu Paste** (the PT terminal ignores synthetic keystrokes), then submitted with Enter;
- Output is read back with drag-select + context-menu Copy, so **only the visible area** is captured; enlarge the window or split long output;
- The default wait between commands is 1.2 s, `ping` waits 8 s; pass `--wait` when a device is slow.

Fetch a page in the browser:

```
Desktop → Web Browser (open it first)
```

```powershell
ptforge-gui http PC1 http://10.10.0.1
```

FTP (Server-PT default account `cisco` / `cisco`):

```powershell
ptforge-gui ftp PC1 10.10.0.2 --cmd dir
```

---

## 4. Patch an existing lab

Do not rebuild the whole file — change only what you need:

```powershell
ptforge patch branch.pkt --ops '[{"op":"set_ipv4","device":"PC1","port":"FastEthernet0","address":"10.10.0.21"}]' -o branch2.pkt
ptforge state branch2.pkt --device PC1
```

Supported ops: `set_ipv4`, `set_config` (append or replace), `rename`, `set_switchport`, `remove_config`.

---

## 5. Report material

```powershell
ptforge report branch.pkt -o report --title "Branch acceptance" `
  --figure '{"path":"figures/pc1_ping.png","caption":"PC1 pings the gateway 4/4"}'
```

Output:

```
report/
├── figures/          # screenshots you passed in are copied here
├── captions.json     # figure captions
└── report.md         # device table + address table + link table + figures
```

Drop the files exported by `pt_exec` / `pt_ping` into `figures/` and they become part of the report.

---

## 6. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `Packet Tracer executable not found` | PT is not installed or lives elsewhere; set `PT_EXE` or ignore it (offline features still work) |
| Title says `Invalid File` after `pt_open` | The file is not 8.1.x, or an external tool corrupted it; run `ptforge doctor <file>` |
| `exec` returns empty output | The device window is not open, or the console does not have focus; make sure it is visible on the desktop |
| Assertions keep failing although the screenshot shows the text | Output scrolled out of the visible area; enlarge the window or split `show ...` into several commands |
| Two PT instances with same-name devices | Close the duplicate instance or rename the device |
| `pt_exec` cannot find the window | The device window title must be the device name (e.g. `R1`); reopen the window after renaming |

---

## Next

- [API.md](API.md): embed these capabilities in Python code
- [TOOLS.md](TOOLS.md): full parameters for the 18 DSH tools
- `examples/`: three runnable scripts

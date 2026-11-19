# dsh-ptforge — Cisco Packet Tracer 自动化插件（DSH bundle）

让 DeepSeek Harness 直接操控 Cisco Packet Tracer：**离线读写 `.pkt` 容器**，生成拓扑、精确连线、注入 IOS 配置，再交给 Packet Tracer 打开。

不依赖 PT 内部 API（PT 8.x 没有 PTAPI），而是复刻 PT 自己的文件格式：

1. `.pkt` 容器 = Twofish-EAX（key `0x89*16` / nonce `0x10*16`）+ 两级混淆 + zlib，解出 `<PACKETTRACER5>` XML；
2. 设备、端口、链路、物理工作区、运行配置都在 XML 里，直接读写；
3. Packet Tracer 打开文件时按自己的 CLI 引擎解析 `RUNNINGCONFIG`，所以写进去的 `hostname` / `interface` / `ip address` / `switchport` 等会被真正应用。

## 工具

| 工具 | 作用 |
| --- | --- |
| `pt_models` | 列出本机 PT 模板中的型号与将生成的 IOS 接口名 |
| `pt_build` | 从 JSON spec 生成 `.pkt`（设备、位置、连线、CLI、静态 IPv4），可顺手打开 |
| `pt_inspect` | 解析现有 `.pkt`：设备、坐标、接口、链路端点、运行配置 |
| `pt_apply` | 给现有拓扑里的设备补写 IOS 配置 / 静态 IP，按 `interface`/`vlan` 段合并后重新加密保存（`replace:true` 才整体覆盖） |
| `pt_open` | 用 PT 打开文件，等窗口标题确认成功并前置 |

## spec 示例

```json
{
  "name": "office_lan",
  "devices": [
    { "model": "2911", "name": "R1", "x": 320, "y": 200,
      "config": ["enable", "configure terminal", "hostname R1",
                 "interface GigabitEthernet0/0", "ip address 192.168.10.1 255.255.255.0",
                 "no shutdown", "exit", "end"] },
    { "model": "2960-24TT", "name": "SW1", "x": 320, "y": 380,
      "config": ["hostname SW1"] },
    { "model": "PC-PT", "name": "PC0", "x": 200, "y": 560,
      "ipv4": ["192.168.10.10", "255.255.255.0", "192.168.10.1"] }
  ],
  "links": [
    { "from": "R1", "to": "SW1", "from_port": "GigabitEthernet0/0", "to_port": "FastEthernet0/1" },
    { "from": "PC0", "to": "SW1", "to_port": "FastEthernet0/2" }
  ]
}
```

`cable` 可选：`straight`（默认）、`cross`、`fiber`、`serial`、`console`、`phone`、`coaxial`。

## 运行前提

- 本机安装 Cisco Packet Tracer 8.1.1（`D:\Cisco Packet Tracer 8.1.1\bin\PacketTracer.exe`，可用配置覆盖）。
- Python 3.9+：优先用 DSH 自带运行时，其次 `python` / `py`；也可用 `DSH_PTFORGE_PYTHON` 或插件配置 `python` 指定。

## 已知边界

- 只覆盖逻辑工作区拓扑与 IOS 配置；PT 的 Activity/Assessment 脚本、IoT 面板、图形标注未实现。
- 设备型号来自本机 PT 的 80 个采集模板，未采到的型号需要先补模板。
- 生成文件的物理机架路径固定落在 `Intercity/Home City/Corporate Office/Main Wiring Closet`。

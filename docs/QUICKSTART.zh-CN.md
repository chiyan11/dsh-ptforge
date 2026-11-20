# 快速上手

[English](QUICKSTART.md)

从零到「一个能验收的实验」，大约 10 分钟。命令都在 PowerShell 里，Python 换成对应平台即可。

---

## 0. 准备

| 需要 | 说明 |
| --- | --- |
| Python 3.10+ | 只用离线功能时不需要 Packet Tracer |
| Packet Tracer 8.1.x | 打开文件、跑运行时命令时需要；默认路径 `D:\Cisco Packet Tracer 8.1.1\bin\PacketTracer.exe`，可用 `PT_EXE` 改 |
| Pillow | 只有 `pt_exec` / `pt_ping` / `pt_http_get` / `pt_ftp` 需要：`pip install "dsh-ptforge[gui]"` |

确认环境：

```powershell
ptforge doctor
```

正常输出里会有 `packet tracer: D:\...\PacketTracer.exe`。没有 PT 也能继续——离线部分不受影响，只是 `open` / `exec` 不可用。

---

## 1. 写 spec

新建 `branch.json`：

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

三个可以省的字段：

| 字段 | 省略后 |
| --- | --- |
| `x` / `y` | 按角色自动布局（路由器一行、交换机一行、终端一行） |
| `a_port` / `b_port`（链路端口） | 自动挑第一个空闲口 |
| `cable` | 同类设备（PC-PC、路由器-路由器、交换机-交换机）用交叉线，其余直通线 |

`ipv4` 支持四种写法：

```json
"ipv4": "10.10.0.11/24,10.10.0.254"
"ipv4": "10.10.0.11 255.255.255.0 10.10.0.254"
"ipv4": ["10.10.0.11/24", "10.10.0.254"]
"ipv4": {"address": "10.10.0.11", "mask": "255.255.255.0", "gateway": "10.10.0.254"}
```

查型号与接口名：

```powershell
ptforge models --query 2960
ptforge models --query 2911
```

---

## 2. 生成、检查、打开

```powershell
ptforge build branch.json -o branch.pkt
ptforge inspect branch.pkt
```

`inspect` 会打印设备、位置、接口与每条链路的两端端口名。接着做离线断言：

```powershell
ptforge check branch.pkt --expect '[{"device":"R1","interface":"GigabitEthernet0/0","ip":"10.10.0.254"}]'
```

返回 `PASS 1/1` 或逐条问题。断言支持这些键：

| 键 | 例子 |
| --- | --- |
| `route` | `{"device":"R1","route":"172.18.20.0/24"}` |
| `interface` + `ip` | `{"device":"R1","interface":"Gi0/0","ip":"10.10.0.254"}` |
| `interface` + `access_vlan` | `{"device":"SW1","interface":"Fa0/1","access_vlan":10}` |
| `nat` | `{"device":"R1","nat":"inside"}` |
| `config_contains` | `{"device":"R1","config_contains":"ip nat inside"}` |

打开：

```powershell
ptforge open branch.pkt
```

> `ptforge open` 需要 PT 已安装。也可以直接双击 `.pkt`。

---

## 3. 真机验证

这一步才需要 Packet Tracer 窗口。流程固定：

1. `ptforge open branch.pkt` 把文件打开并置前；
2. 在画布上**双击设备**，打开设备窗口；
3. PC 走 `Desktop → Command Prompt`；路由器/交换机走 `CLI` 标签页（可能需要先按一次回车）；
4. 保持窗口打开，再执行下面的命令。

```powershell
ptforge-gui exec R1 "show ip route"
ptforge-gui exec PC1 "ipconfig" --out pc1.png
ptforge-gui ping PC1 10.10.0.12
ptforge-gui assert R1 --checks '[{"command":"show ip route","contains":"10.10.0.0/24"}]'
```

几条实际约束：

- 命令通过**右键菜单 Paste** 输入（PT 终端不接受合成逐键输入），回车提交；
- 回读靠拖选 + 右键 Copy，**只拿得到可见区域**；输出很长时把窗口拉大或分段执行；
- 每条命令之间默认等待 1.2 s，`ping` 默认 8 s；不稳定时加 `--wait`。

浏览器取页面：

```
Desktop → Web Browser 打开后
```

```powershell
ptforge-gui http PC1 http://10.10.0.1
```

FTP（Server-PT 默认账号 `cisco` / `cisco`）：

```powershell
ptforge-gui ftp PC1 10.10.0.2 --cmd dir
```

---

## 4. 改一个已经存在的实验

不重建整包，只改变量：

```powershell
ptforge patch branch.pkt --ops '[{"op":"set_ipv4","device":"PC1","port":"FastEthernet0","address":"10.10.0.21"}]' -o branch2.pkt
ptforge state branch2.pkt --device PC1
```

支持的算子：`set_ipv4`、`set_config`（追加或替换）、`rename`、`set_switchport`、`remove_config`。

---

## 5. 报告素材

```powershell
ptforge report branch.pkt -o report --title "分支网络验收" `
  --figure '{"path":"figures/pc1_ping.png","caption":"PC1 ping 网关 4/4"}'
```

产出：

```
report/
├── figures/          # 你传入的截图会被复制到这里
├── captions.json     # 图注
└── report.md         # 设备表 + 地址表 + 链路表 + 图
```

把 `figures/*.png` 换成 `pt_exec` / `pt_ping` 的导出一并放进来即可。

---

## 6. 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| `Packet Tracer executable not found` | 没装或路径不同；设 `PT_EXE` 或忽略（不影响离线功能） |
| `pt_open` 打开后标题是 `Invalid File` | 文件版本不是 8.1.x，或文件被外部工具改坏；先跑 `ptforge doctor <file>` |
| `exec` 输出为空 | 设备窗口没打开、或控制台没获得焦点；确认窗口在桌面可见 |
| 断言一直失败但截图里有内容 | 输出滚出了可见区域；拉大窗口或把 `show ...` 拆成多条 |
| 多个 PT 实例同名设备 | 关掉重复实例，或给设备改名 |
| `pt_exec` 报找不到窗口 | 设备窗口标题必须是设备名（如 `R1`），改过名要重新打开窗口 |

---

## 下一步

- [API.md](API.zh-CN.md)：把上面的能力嵌进 Python 代码
- [TOOLS.md](TOOLS.zh-CN.md)：18 个 DSH 工具的完整参数
- `examples/`：三个可直接运行的脚本


# ptforge 工具速查表

18 个 `pt_*` 工具，分两类：**离线**（只读写 `.pkt`，不需开 Packet Tracer）与**运行时**（真开 PT 窗口敲命令、取回显）。

---

## 一、离线：构建与修改

| 工具 | 作用 | 关键参数 | 例子 |
|---|---|---|---|
| `pt_models` | 列出可用设备型号与接口名 | `query?`, `limit?` | `{query:"2960"}` |
| `pt_build` | 从 JSON spec 生成 `.pkt` | `spec` 或 `spec_path`, `out?`, `open?` | 见下 |
| `pt_open` | 用 PT 打开 `.pkt` 并置前 | `file`, `timeout_seconds?` | `{file:"lab.pkt"}` |
| `pt_patch` | 增量改：IP、配置、改名、VLAN、删配置 | `file`, `ops[]`, `out?` | `{file, ops:[{op:"set_ipv4",device:"PC0",address:"192.168.10.10",gateway:"192.168.10.1"}]}` |
| `pt_apply` | 往单台设备写 IOS 配置或静态 IP | `file`, `device`, `lines[]`/`lines_file`, `ip/mask/gateway/port?`, `out?` | `{file, device:"R1", lines:["ip route 0.0.0.0 0.0.0.0 10.0.0.1"]}` |
| `pt_note` | 画布标注增删改 | `file`, `action`, `text?`, `device?`, `x/y?`, `dx/dy?`, `index?`, `out?` | `{file, action:"add", device:"PC0", text:"PC0 10.0.0.10 / Fa0"}` |
| `pt_server_page` | 读写 Server-PT 的网页 | `file`, `action(list/get/set)`, `device?`, `name?`, `html?`/`html_file?`, `out?` | `{file, action:"set", html:"<h1>demo</h1>"}` |

### spec 最小形态

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

- `ipv4` 三种形状都行：`"192.168.10.10/24,192.168.10.1"`、`"192.168.10.10 255.255.255.0 192.168.10.1"`、`[ip, mask, gw]` 或 `{address,mask,gateway}`。
- 链路不写端口 → 自动找空闲口；不写 `cable` → 同类设备自动交叉线，异类直通线。
- 不写 `x/y` → 自动布局。

---

## 二、离线：读取与校验

| 工具 | 作用 | 关键参数 | 例子 |
|---|---|---|---|
| `pt_inspect` | 设备/位置/接口/链路清单 | `file`, `config_lines?` | `{file:"lab.pkt"}` |
| `pt_state` | 结构化状态：接口 IP、静态路由、NAT、ACL、VLAN | `file`, `device?` | `{file:"lab.pkt", device:"R1"}` |
| `pt_check` | 对 `.pkt` 断言 | `file`, `expect[]` | `{file, expect:[{device:"R1", route:"172.18.20.0/24"},{device:"SW1", interface:"Fa0/1", access_vlan:10}]}` |
| `pt_doctor` | 环境与文件版本体检 | `file?` | `{}` |
| `pt_report` | 出报告素材：`figures/`+`captions.json`+`report.md` | `file`, `out_dir?`, `title?`, `figures?` | `{file:"lab.pkt", out_dir:"report"}` |

`pt_check` 支持的断言键：`route`、`interface`（配 `ip` 或 `access_vlan`）、`nat`、`config_contains`。

---

## 三、运行时：需要 PT 窗口

前提：PT 已打开对应 `.pkt`；目标设备窗口已双击打开（PC 用 Desktop → Command Prompt / Web Browser，路由器用 CLI 页）；桌面可交互。

| 工具 | 作用 | 关键参数 | 例子 |
|---|---|---|---|
| `pt_gui` | 底层逃生舱：焦点/点击/输入/截图/粘贴/复制 | `action`, `title?`, `x/y?`, `double?`, `text?`, `keys?`, `path?`, `region?`, `enter?` | `{action:"shot", path:"topo.png"}` |
| `pt_exec` | 执行命令并回读 transcript + 截图 | `device`, `commands[]`, `out?`, `wait_ms?`, `read?` | `{device:"R1", commands:["show ip route"]}` |
| `pt_assert` | 带断言的命令回读 | `device`, `checks[]`, `wait_ms?` | `{device:"R1", checks:[{command:"show ip route", contains:"O    192.1.3.0/24"}]}` |
| `pt_ping` | ping 并解析统计 | `device`, `target`, `count?`, `wait_ms?` | `{device:"PC0", target:"192.1.1.254"}` |
| `pt_http_get` | 浏览器取页面正文 | `device`, `url`, `out?`, `wait_ms?` | `{device:"PC0", url:"http://192.168.10.2"}` |
| `pt_ftp` | FTP 会话（提示符驱动） | `device`, `server`, `username?`, `password?`, `commands?`, `out?`, `wait_ms?` | `{device:"PC0", server:"192.168.10.2", commands:["dir"]}` |

`pt_assert` 的 checks 支持 `contains`、`regex`、`not_contains`（对整段 transcript 做多行匹配）。

---

## 四、典型流水线

```
pt_models → pt_build(open:true) → pt_inspect        # 造拓扑
pt_patch / pt_apply / pt_note / pt_server_page      # 改拓扑
pt_check / pt_state / pt_doctor                     # 离线验收
pt_open → pt_exec / pt_assert / pt_ping / pt_http_get / pt_ftp   # 真机验收
pt_report                                           # 出报告素材
```

## 五、边界

- 终端回读只能取**可见区域**；长会话取过程中最长的一次快照。
- 多个 PT 实例里有同名设备会歧义 → 先关掉重复实例或改名。
- `pt_open` 每文件起一个新 PT 实例；确认窗口标题含文件名才算打开成功。
- 文件版本需 8.1.x（`pt_doctor` 会检查）。

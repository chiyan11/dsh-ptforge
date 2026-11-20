# 示例

三个脚本都只依赖核心引擎（不需要 Packet Tracer、不需要 Pillow），产物写到 `examples/out/`。

```powershell
cd D:\coding\daily\dsh-ptforge
pip install -e .            # 或 pip install dsh-ptforge
python examples\01_build_and_check.py
python examples\02_patch_and_state.py
python examples\03_report.py
```

| 脚本 | 演示 | 产物 |
| --- | --- | --- |
| `01_build_and_check.py` | 读 `lab.json` → 生成 `.pkt` → 打印结构化状态 → 断言 | `out/branch.pkt` |
| `02_patch_and_state.py` | 在 `branch.pkt` 上改 IP、改主机名、追加配置（不重建整包） | `out/branch_patched.pkt` |
| `03_report.py` | 建一个含 Server-PT 的小实验、加画布标注、生成报告素材 | `out/web_lab_annotated.pkt`、`out/report/` |

`lab.json` 是一份可直接改成你自己实验的 spec：设备、配置、`ipv4`、链路；端口、线型、坐标都可以省略。

想看真机执行（`pt_exec` / `pt_ping` / `pt_http_get`）的用法，见 [../docs/QUICKSTART.md](../docs/QUICKSTART.md) 第 3 节。

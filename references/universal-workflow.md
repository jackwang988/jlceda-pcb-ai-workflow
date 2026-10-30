# 统一流程 · R1

范围：**需求 → 导出 Gerber + BOM + 坐标 → 封存**。取消项（维护者 2026-10-30 决定）：E0 能力探测（用户已配好环境，skill 不检查配置）、M3 外部复核、L1/L2 试产与 ECO。下单、上传不在流程内。
几何类检查（线距/焊盘距/阻焊桥/孔环/板边）**由 EDA 自身 DRC 负责**（维护者决定），本 skill 只保证设计规则不低于嘉立创工艺。

## 六组导航 → 节点 → 门禁

| 组 | 节点 | 内容 | 门禁 |
|---|---|---|---|
| 工程保护 | E1 | 记录基线计数；约定每轮 save | — |
| 需求架构 | A1 需求量化 | 需求表：ID、来源、量化验收；未知项列“待确认”不猜 | — |
| | A2 工艺声明 | **用户填写** `process.json`：layers / copper_oz 必填，另有 thickness_mm / surface / edge / mask_color / smt | — |
| 原理图 | S1 选型 | C 编号、引脚与封装对照 datasheet（见 library-selection） | |
| | S2 绘制 | 经 Bridge 分批放置/连线，网络名连线优先 | |
| | S3 评审 | `sch_Drc.check` + 引脚/电源谓词 + AI 逐功能读图 | **G1 原理图**、**G2 库/封装** |
| PCB | P1 规则 | 读官方预设→建网络类/差分→写回；`rules_check.py` 确认规则不低于工艺 | |
| | P2 布局 | 分区、天线净空、去耦就近、板边与孔位 | **G3 布局** |
| | P3 布线 | 关键网络优先；铺铜后 save→重载→再 DRC | |
| | P4 评审 | `drc_check.py` 清零 + AI 逐层读图 | **G4 PCB** |
| 制造 | M1 导出 | `export_gerber.py`、`export_bom_cpl.py`（均只读，拒绝覆盖） | |
| | M2 复核 | `gerber_guard.py`、`bom_cpl_guard.py check` | **G5 导出放行** |
| 终点 | 封存 | `release.py --apply`：重新复核 + 校验确认未过期 + 写哈希清单 | — |

## 门禁机制（workflow.py，dialogue 模式）

- `confirm` 必须带 `--user-reply`（用户原话）；通过(1)必须 `--bind` 被确认的文件，记录其 sha256。
- **按顺序**：前序门禁不是 CONFIRMED，后序不能确认。
- **自动失效**：被绑定文件一变，该门禁与其后全部门禁变 `STALE`，必须重新确认。
- `release.py` 封存前再次要求：G1–G5 全 CONFIRMED、Gerber/BOM/坐标都被 G5 绑定且哈希未变、并**当场重新复核**（不信旧报告）。

## 节点约定

- **默认预览**：写入类动作先输出“将执行的 JS + 预计影响”，用户答复编号后才执行；执行后回读对账。
- **save**：每个写入节点结尾 `bridge_client.py save`。分批：器件 ≤12、导线 ≤15–20。
- 重大改动在新 Board 里做；`openProject()` 会丢弃未保存修改，调用前必须先 save。
- 流程里需要连 EDA 的只有：`drc_check`、`export_gerber`、`export_bom_cpl` 以及你自己的绘制/布线脚本；其余全部离线。

## 失败回退

规格错回 A1；参数/连接错回 S2；封装/引脚错回 S1；规则错回 P1；布局/走线错在新候选修复；Gerber/BOM 复核有阻断回 P3/P4，修后**重新导出并重新确认**（不覆盖旧包，文件变化使门禁自动失效）。

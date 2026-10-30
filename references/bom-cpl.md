# BOM 与坐标（CPL）

规则数据：`data/jlc-bom-cpl-spec.json`（24 条，带来源与原文）。脚本：`export_bom_cpl.py`（导出，连 EDA）、`bom_cpl_guard.py`（复核与规范化，纯离线）。

## 实测：EDA 4.1.93 原生导出长什么样（2026-10-30；`tests/fixtures/synthetic_native_*` 是按这个形态**合成**的同构夹具，不含真实设计）

| 项 | 原生 BOM | 原生 坐标 |
|---|---|---|
| 编码 / 分隔 | **UTF-16 LE（带 BOM 头）+ 制表符** | 同左 |
| 表头 | No. / Quantity / Comment / Designator / Footprint / Value / Manufacturer Part / Manufacturer / Supplier Part / Supplier | Designator / Device / Footprint / Mid X / Mid Y / Ref X / Ref Y / Pad X / Pad Y / Pins / Layer / Rotation / SMD / Comment / Value / Type / Supplier / Datasheet |
| 位号 | 同型号合并，`C1,C2,C3` | 一位号一行 |
| 其他 | 嘉立创编号在 `Supplier Part`（如 C90544） | **坐标值带 `mm` 后缀**（`"52.188mm"`），Layer 为 `T`/`B` |
| 一致性 | 展开后的位号集合与坐标文件完全一致 | 一位号一行 |

官方文档（docs.lceda.cn）也明说：EDA 的 BOM 和坐标文件是 Unicode + 制表符，**上传嘉立创前需转 UTF-8/ANSI 逗号 CSV**。所以流程是 `导出(原生，留证据) → normalize → 复核 → 上传前人工看一眼`。

## 规范化（normalize）做什么

UTF-16/制表符 → UTF-8/逗号 CSV；去空行；坐标去掉 `mm` 后缀（官方：mm 可直接写数值）；**mil 文件相反，必须保留单位后缀**。不改任何内容字段（中文如 `FH(风华)` 原样保留）。拒绝覆盖已存在文件。

## 复核做什么（可全自动的硬规则）

| 对象 | 检查 |
|---|---|
| BOM | 必需列 Comment/Designator/Footprint；必填不为空；位号只用英文逗号/空格；`R1-4` 范围前缀一致且起<止；位号 ≤64 字符、无中文、无 `@#$%^&{}[]`；**大小写不敏感**（R1 与 r1 视为重复）；位号不重复；`Quantity` = 展开后位号数；合计行告警；Comment 纯数字（如 `100`）告警 |
| 坐标 | 必需列 Designator/Mid X/Mid Y/Layer/Rotation；**表头不得带单位**；单位只能 mm/mil 且不混用；mil 须带后缀；Layer 仅 T/B/Top/Bottom；Rotation 为数字且 ≤3 位小数；位号不重复；**坐标极差 ≤ 板尺寸**（`--board-size` 或 `--gerber` 自动取板框） |
| 交叉 | BOM 与坐标位号集合必须一致（不一致列出两边各自多出的） |
| 格式 | xls/xlsx 不解析 → BLOCKED(2)，要求另存 CSV（官方只读首个工作表前 12 列） |

## 复核不能做什么（报告里每次都会提示）

- **无法验证 C 编号与型号/封装是否对应**（不联网）。官方：填了编号则**以编号为准，错误编号比缺少更危险**。只检查格式 `C+数字` 并列出缺失项，对应关系须以嘉立创下单页的匹配结果为准。
- 不判断极性/旋转是否正确：官方明说 EDA 封装 0° 与嘉立创封装 0° 可能不一致，贴片预览若提示极性错误，需人工看 2D 图，嘉立创会人工修正。
- 不处理“不贴器件(DNP)”的业务含义，只检查 BOM 与坐标处理方式一致（位号集合相同）。

## 导出的实现要点

`getBomFile('BOM','csv')` 与 `getPickAndPlaceFile('CPL','csv','mm')`：单位参数传字符串 `'mm'`（运行时枚举不可用）；返回浏览器 File，读成 base64 分块回传、不截断；回传后校验字节数。导出只读，不改工程。

# jlceda-pcb-ai-workflow

> 嘉立创EDA（LCEDA / EasyEDA Pro）**设计流程与制板规范门禁** skill —— 从需求到导出 Gerber / BOM / 坐标并封存。
> An AI-agent skill that wraps a *design-to-fabrication-files* workflow for JLCEDA / EasyEDA Pro with JLCPCB-process gates.

状态：**0.9.0 beta** · 许可：MIT（第三方引文见 [LICENSE](LICENSE)） · 离线仅依赖 **Python ≥ 3.8 标准库**

---

## 中文

### 它是什么
一套给 AI 编程助手用的 skill：**AI 负责设计与判断，脚本只负责在声明范围内独立复核**，用户用编号答复通过 5 道门禁，最后封存成带哈希清单的发布包。
全程**不上传、不下单**；缺工艺声明、缺证据一律 `BLOCKED`，不猜、不默认通过。

### 它能做什么 / 不能做什么

| 能做 | 不能做 |
|---|---|
| 把嘉立创制板工艺（线宽线距、过孔、孔径、板厚、阻焊、丝印、板边…）做成**带官方原文与来源**的规范库，三档判定（极限 / 建议 / 成本触发） | 判断电路功能是否正确；SI / EMC / 热 / 阻抗求解 |
| 核对 EDA **设计规则本身**不低于嘉立创工艺（DRC 的“尺子”） | 线距、焊盘距、阻焊桥、孔环、板边等**设计实际值**：这些交给 EDA 自身 DRC |
| 导出 Gerber，并**直接读文件**独立复核（结构、板框闭合、最小线宽/孔径/槽宽…） | 验证 C 编号与器件是否对应（离线做不到，以嘉立创下单页匹配为准） |
| 导出 BOM/坐标，转 UTF-8 逗号 CSV，按官方格式规范复核（位号、数量、单位、层、旋转、两边位号一致、坐标不超板） | 判断极性/旋转是否正确（需人工看 2D 图） |
| G1–G5 对话确认：必须带用户原话、按序、绑定文件哈希、文件一变自动失效 | 下单、上传、CAM/DFM 外部复核、样机、ECO |

### 依赖与兼容

| 项 | 要求 |
|---|---|
| Python | ≥ 3.8，**仅标准库**（无需 `pip install`） |
| 离线部分 | 无需 EDA：`gerber_guard` `bom_cpl_guard` `rules_check` `spec_check` `workflow` `release` `spec_drift` |
| 连 EDA 的部分 | `drc_check` `export_gerber` `export_bom_cpl`：需要 **嘉立创EDA 专业版 ≥ 4.1**，以及 [`easyeda-api`](https://github.com/easyeda/easyeda-api-skill) 提供的 Bridge 与 `run-api-gateway` 扩展（本 skill **不检查你的环境**，通道不通则 `BLOCKED` 并停止） |
| 已验证版本 | EDA 4.1.93（在线端到端）；Gerber 解析在 3.2.149 与 4.1.93 导出上验证（**仅 2 层板**） |
| 数据口径 | 国内站 jlc.com；数值抓取于 2026-10-30 |

### 安装到 AI Agent（全新用户）

**这两个 Skill 需要分开安装：** `jlceda-pcb-ai-workflow`（本项目，工作流/检查/门禁）以及上游 [`easyeda-api`](https://github.com/easyeda/easyeda-api-skill)（EDA API / Bridge）。只做离线 Gerber、BOM 和规则检查，不需要安装后者。

**方式 A｜交给支持本地文件操作的 Agent 安装（推荐）**

复制下面的指令，安装到支持本地 Skills 的 AI 工具：

> 请从 https://github.com/jackwang988/jlceda-pcb-ai-workflow 安装 `jlceda-pcb-ai-workflow` 到当前 AI 工具的用户级 Skills 目录。检查安装后目录根部直接包含 `SKILL.md`、`scripts/`、`data/`、`references/`，不要多嵌套一层。运行 `python tools/validate_skill.py .`、`python tools/privacy_scan.py .` 和 `python -B tests/run_tests.py`，确认全部通过。要连接并操作 EDA 时，再按官方指南安装 `easyeda-api` 与 `run-api-gateway` 扩展。不要自动下单、上传制造文件或替用户确认门禁。

**方式 B｜手工安装到 Codex（Windows PowerShell）**：解压发布包之后，在 `jlceda-pcb-ai-workflow` 文件夹内打开 PowerShell：

```powershell
$dest = Join-Path $HOME '.agents/skills/jlceda-pcb-ai-workflow'
New-Item -ItemType Directory -Force $dest | Out-Null
Get-ChildItem -Force | Copy-Item -Destination $dest -Recurse -Force
python "$dest/tools/validate_skill.py" "$dest"
python "$dest/tools/privacy_scan.py" "$dest"
python -B "$dest/tests/run_tests.py"
```

最终结构应为 `$HOME/.agents/skills/jlceda-pcb-ai-workflow/SKILL.md`，而**不是**再嵌套一个同名目录。其他支持 Agent Skills 标准的 AI 工具请改用它们各自的 Skills 路径。Codex 可通过 `/skills` 或 `$jlceda-pcb-ai-workflow` 调用；未识别时重启会话。<https://learn.chatgpt.com/docs/build-skills>

**连接嘉立创EDA（只在需要远程 API 操作时执行）**：

1. 在与嘉立创EDA运行于**同一台电脑**的环境中安装 Node.js 22 LTS+、Python 3.8+；安装上游 `easyeda-api` Skill 后，在该目录执行 `npm install`（非本项目目录）。
2. 按官方文档启动上游 `node scripts/bridge-server.mjs`（须保持运行或后台运行）；它只监听本机 `127.0.0.1` 的 49620–49629 端口。
3. 在嘉立创EDA专业版安装并启用官方适配的 [`run-api-gateway` 扩展](https://jlc-ext.com/item/oshwhub/run-api-gateway)，启用允许外部交互，保持 EDA 已打开目标工程。
4. 执行 `python scripts/bridge_client.py health`，必须确认 Bridge 在线且 `edaConnected=true`，然后才能用 `drc_check.py`、`export_gerber.py`、`export_bom_cpl.py`。**没有 Bridge 时这三项不能运行，离线脚本仍可运行。**

如出现 Bridge 启动失败、EDA 连接断开或 API 版本不兼容，先查阅上游文档再继续；本 Skill 不会自动修改运行环境。**未在本次公开版审查中实际连接你的 EDA，因此线上自动设计与导出仍需使用者现场验证。**

### 使用场景（直接对 Agent 说）

- 「用 jlceda-pcb-ai-workflow 检查这个双层 1oz Gerber 是否满足嘉立创打样条件，先让我填写工艺声明，不要下单。」
- 「用 jlceda-pcb-ai-workflow 核对当前 EDA 规则与 PCB DRC，异常先报告再让工程师确认。」
- 「用 jlceda-pcb-ai-workflow 检查 BOM 和贴片坐标的一致性，任何缺证据项不得自动通过。」

### 快速开始

```bash
S="/absolute/path/to/jlceda-pcb-ai-workflow"  # 替换成你的 Skill 目录
# 1) 建工程目录与工艺声明模板（layers / copper_oz 必须由你填写，不会被猜）
python $S/scripts/workflow.py init ./myboard --apply

# 2) 对已有的 Gerber / BOM / 坐标做离线复核（不需要 EDA）
python $S/scripts/gerber_guard.py board_gerber.zip --process ./myboard/process.json
python $S/scripts/bom_cpl_guard.py check --bom bom.csv --cpl cpl.csv --gerber board_gerber.zip

# 3) 设计规则是否低于嘉立创工艺（用官方预设自测）
python $S/scripts/rules_check.py --preset "JLCPCB Capability(Two Layers Board)" --process ./myboard/process.json

# 4) 全部门禁确认后封存（默认只预览，--apply 才写入；不上传、不下单）
python $S/scripts/release.py ./myboard --version V1.0 --gerber gerber.zip --bom bom.csv --cpl cpl.csv
```
全节点与规则图表见 [`docs/workflow.html`](docs/workflow.html)；完整流程见 [`references/universal-workflow.md`](references/universal-workflow.md)；能力边界见 [`references/capabilities.md`](references/capabilities.md)。

### 输出术语对照（运行时输出为中文）

| 输出 | English |
|---|---|
| 【阻断级】/ BLOCK | blocker – below the process limit, must fix |
| 【中风险】/ WARN | warning – between limit and recommended value |
| PASS | meets the recommended value |
| 【待证据】/ NEEDS_EVIDENCE | rule applies but no measured value was provided |
| N/A | no such objects on the board |
| COST_TRIGGER ⚑ | falls in a range the fab flags as "unusual / extra cost" |
| `BLOCKED`（退出码 2） | cannot conclude: missing declaration / evidence / unparsable input / gate not confirmed |
| 退出码 0 / 1 / 2 | no blocker in declared scope / blocker found / BLOCKED |
| G1–G5 | gates: schematic · library & footprint · placement · PCB · export release |
| STALE | a confirmed gate whose bound file has changed since → must re-confirm |

> 退出码 0 只代表“声明范围内无阻断”，**不代表电路正确，也不代表可以生产**。

### 测试与可信度

```bash
python -B tests/run_tests.py         # 离线，全部使用合成夹具
python -B tests/run_tests.py --live     # 额外连 EDA 做端到端（需要 Bridge）
python tools/make_fixtures.py --check   # 夹具必须与生成器逐字节一致
python tools/privacy_scan.py .          # 扫描常见密钥、邮箱、敏感路径与内网地址
```
- 夹具全部由 `tools/make_fixtures.py` 生成，**不含任何真实设计**。解析器在真实导出上验证过，但真实文件不能随包分发；如果你有自己的导出文件，设置环境变量 `JLCEDA_REAL_FIXTURES=<目录>` 可追加真实文件回归（见 `tests/run_tests.py` 顶部说明）。
- `tests/trigger_cases.md` 的 22 条触发用例**尚未实测**。

### 维护
- 规范数值抓取于 2026-10-30。出厂前运行 `python scripts/spec_drift.py`（联网，只报告不改库），并人工抽查原文片段；`jlc-pcb.com` 对程序化访问返回 403，需手动核对。
- 新增规则只改 `data/*.json`（须带来源、抓取日期、原文片段），再跑 `python scripts/spec_check.py --validate-data` 与测试。脚本内**禁止出现裸阈值**（测试 B07 检查）。
- 踩坑登记簿：[`data/known-pitfalls.json`](data/known-pitfalls.json)。

---

## English (summary)

**What**: a skill for AI coding agents that drives a *requirements → schematic → PCB → Gerber + BOM + pick-and-place → sealed release* workflow in JLCEDA / EasyEDA Pro (Professional edition), with gates derived from JLCPCB's published process capabilities.

**Design rules**: fail-closed (missing process declaration / evidence ⇒ `BLOCKED`, never a silent pass) · every threshold lives in `data/*.json` with a source URL, retrieval date and the verbatim quote · scripts contain no hard-coded thresholds · the agent never fills in user confirmations · **never places an order, never uploads anything**.

**Requirements**: Python ≥ 3.8 (stdlib only). Offline checks need nothing else. The three EDA-connected scripts need EasyEDA/JLCEDA Pro ≥ 4.1 plus the Bridge from [`easyeda-api`](https://github.com/easyeda/easyeda-api-skill).

**Limits**: rule data is for the **domestic site (jlc.com)** only; verified on 2-layer boards and EDA 3.2.149/4.1.93; cannot verify that an LCSC part number matches the component, nor polarity/rotation; geometric DRC (clearance, annular ring, mask bridge…) is left to the EDA's own DRC — this skill only checks that your *rule settings* are not looser than the fab's limits. Runtime messages are Chinese (see the glossary above).

**Not affiliated** with JLCPCB / 嘉立创 / EasyEDA. Short quotations in `data/*.json` remain the property of their sources.

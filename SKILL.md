---
name: jlceda-pcb-ai-workflow
description: 嘉立创EDA专业版(LCEDA/EasyEDA Pro)的设计流程与制板规范门禁，范围从需求到导出 Gerber/BOM/坐标并封存为止：按嘉立创官方工艺（线宽线距、过孔钻孔、板厚、阻焊、丝印、板边）核对设计规则与导出文件，复核 BOM 与坐标(贴片文件)格式，运行原生 DRC，并用 G1–G5 对话确认门禁留痕后封存发布包。当用户要在嘉立创EDA 里做板、检查能否按嘉立创工艺打样、导出生产文件/制造文件(Gerber、BOM、坐标)前做检查、或核对立创选型(C编号/引脚/封装)时使用。依赖 easyeda-api 提供的 Bridge 通道；缺工艺声明或证据时阻断，不承诺自动设计合格，不下单、不上传。英文关键词：JLCEDA EasyEDA-Pro JLCPCB Gerber BOM pick-and-place DRC fabrication-rules。触发词：嘉立创EDA 立创EDA LCEDA 嘉立创制板工艺 打样 立创选型 Gerber导出 BOM坐标 导出前检查 DRC 设计规则 嘉立创DFM可制造性
license: MIT
compatibility: Python>=3.8 (stdlib only). Offline checks need nothing else; drc_check/export_gerber/export_bom_cpl need JLCEDA/EasyEDA Pro >=4.1 and the easyeda-api bridge.
metadata:
  version: "0.9.0"
  status: beta
  data_site: jlc.com
  data_retrieved: "2026-10-30"
---

# 嘉立创EDA 设计流程 · R1

**范围**：需求 → 原理图 → PCB → 导出 **Gerber + BOM + 坐标** → 封存。不含：下单、上传、CAM/DFM 外部复核、样机与 ECO。**不检查环境与配置**（用户已配好 Bridge 与 EDA 扩展）；需要通道时先加载 `easyeda-api`。

先读 [统一流程](references/universal-workflow.md) 与 [对话确认门](references/stage-approvals.md)。退出码 0 只代表“声明范围内无阻断”，**不代表电路正确，也不代表可以生产**。

## 红线（不可绕过）

1. **永不调用** `placePcbOrder / placeSmtComponentsOrder / placeComponentsOrder`（会真实开订单页）。`bridge_client.py` 发送前拦截。
2. **永不上传**文件到任何第三方；`release.py` 只在本地封存。
3. 已知会卡死 EDA 的接口 `getPdfFile/getSvgFile/getPngFile/getDxfFile` 默认拦截（BR-06）。
4. 缺来源 / 缺工艺声明 / 缺证据 → **BLOCKED**，不得写 PASS 或 N/A。不猜工艺：`layers`、`copper_oz` 必须由用户声明。
5. 不为过检查而改网络、删器件、放宽规则；放宽规则须有工艺依据并留痕。
6. 写入类操作结尾必须 save 并回读对账（未 save 重启即丢整板）。
7. 单位/图层 ID 用常量表：[单位与 ID](references/units-and-ids.md)。
8. **确认必须是用户的原话**：`workflow.py confirm --user-reply` 不得由 Agent 代填。

## 阶段 → 读什么

| 阶段 | 做什么 | 读 |
|---|---|---|
| E1 A1 A2 | 工程保护、需求量化、工艺声明 | [universal-workflow](references/universal-workflow.md) |
| S1 选型 | C 编号、引脚/封装对照 datasheet | [library-selection](references/library-selection.md) |
| S2 S3 | 绘制与评审（分批、save、ERC） | [bridge-runtime](references/bridge-runtime.md)、[api-map](references/api-map.md) |
| P1–P4 | 设计规则、布局、布线、DRC | [pcb-rules](references/pcb-rules.md) |
| M1 M2 | Gerber / BOM / 坐标 导出与复核 | [gerber-export](references/gerber-export.md)、[bom-cpl](references/bom-cpl.md) |
| 终点 | 封存发布包 | [universal-workflow](references/universal-workflow.md) |
| 规范来源 | 数值从哪来、冲突与漂移 | [spec-provenance](references/spec-provenance.md) |
| 能力边界 | 能做 / 不能做 / 必须人工 | [capabilities](references/capabilities.md) |

## 快速调用（`$S` = 本 skill 目录；只依赖 Python 标准库）

```bash
# 流程（纯本地，不连 EDA）
python $S/scripts/workflow.py init <工程目录> --apply            # 建 workflow.json + process.json 模板
python $S/scripts/workflow.py status <工程目录>                  # 五道门禁状态(PENDING/CONFIRMED/STALE)
python $S/scripts/workflow.py confirm <工程目录> --gate G1 --choice 1 --user-reply "<用户原话>" --bind process.json
python $S/scripts/workflow.py plan --task list                   # 白名单任务清单
# 检查
python $S/scripts/rules_check.py --config rules.json --process process.json   # 设计规则不低于嘉立创工艺（离线）
python $S/scripts/drc_check.py                                   # 原生 DRC（连 EDA，只读）
python $S/scripts/export_gerber.py --out <新.zip>                # 导出 Gerber（连 EDA，拒绝覆盖）
python $S/scripts/gerber_guard.py <zip> --process process.json   # Gerber 独立复核
python $S/scripts/export_bom_cpl.py --out-dir <目录> --prefix <名>  # 导出 BOM+坐标并规范化（连 EDA）
python $S/scripts/bom_cpl_guard.py check --bom b.csv --cpl c.csv --gerber <zip>
# 终点与维护
python $S/scripts/release.py <工程目录> --version V1.0 --gerber gerber.zip --bom bom.csv --cpl cpl.csv [--apply]
python $S/scripts/spec_drift.py                                  # 规范数值 vs 官方页面（联网，只报告）
python $S/tests/run_tests.py [--live]                            # 缺陷注入与单元测试
```

工艺声明模板 `assets/process.template.json`。阈值只存在于 `data/*.json`，每条带来源与原文片段；脚本内不得出现裸阈值（测试 B07 检查）。

## 判定语义

`BLOCK` 低于官方极限；`WARN` 介于极限与建议之间（须写理由）；`PASS` 达建议值；`COST_TRIGGER` 命中官方“非常规/费用高”；`NEEDS_EVIDENCE` 缺实测值；`N/A` 板上无此类对象。

## 放行边界

- **线距、焊盘距、阻焊桥、孔环、板边等几何检查由 EDA 自身 DRC 负责**，本 skill 不重复实现；它保证的是“给 DRC 的尺子（设计规则）不低于嘉立创工艺”（`rules_check`）以及“导出文件本身没问题”（`gerber_guard`/`bom_cpl_guard`）。
- DRC 通过 ≠ 满足嘉立创工艺（规则可被放宽）；Gerber/BOM 文件存在 ≠ 内容正确；**C 编号与器件是否对应无法离线验证**，以嘉立创下单页匹配结果为准。
- 本 skill 不替代电路功能验证、SI/EMC/热分析与嘉立创自身的下单审核。数值抓取于 2026-10-30（国内站 jlc.com），出厂前跑 `spec_drift` 并人工抽查。

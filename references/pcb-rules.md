# P1–P4 PCB 规则与评审

## 1. 嘉立创官方预设规则（T0 来源，已实测读取）

你的客户端内置 7 套预设，可由 API 直接读取（`eda.pcb_Drc.getAllRuleConfigurations(true)`，原始快照 `data/rule-presets/_all_raw.json`）：

| 层别 | 预设名 |
|---|---|
| 单层 | `JLCPCB Capability(Single Layer Board)` |
| 双层 | `JLCPCB Capability(Two Layers Board)` |
| 多层 | `JLCPCB Capability(Multiple Layers Board)` |
| 另有 | High Frequency / Aluminum Substrate / Copper Substrate / `自定义配置` |

每套含四块：`Spacing`（安全间距矩阵、其他间距）/ `Expansion`（阻焊/锡膏扩展）/ `Physics`（线宽、过孔、差分、网络长度）/ `Plane`（铺铜与内电层）。安全间距是下三角矩阵，行列为 `Track / SMD Pad / TH Pad / … / Via / Copper Zone / Board Outline / Hole`。

## 2. 预设 = 建议值，工艺页 = 极限值

| 项目 | 官方预设（recommended） | 工艺页（limit） |
|---|---|---|
| 1oz 最小线宽：单层 / 双层 / 多层 | 0.102 / **0.127** / 0.102 mm | 0.10 / 0.10 / 0.0889 mm |
| 2oz 最小线宽 | 0.203 mm（三套） | 双层 0.16 / 多层 0.15 mm |
| 1oz 安全间距（线-线） | 0.102 mm（三套） | 同线宽极限 |
| 过孔内径最小：单 / 双 / 多 | 0.3 / 0.3 / **0.2** mm | 0.3 / 0.15 / 0.15 mm |
| 过孔外径最小：单 / 双 / 多 | 0.5 / 0.5 / **0.3** mm | 0.5 / 0.25 / 0.25 mm |
| 孔边到孔边 | 0.3 mm | 0.2 mm |
| 阻焊扩展（焊盘单边） | 0.051 mm | ≥0 |

因此：**规则不要低于预设**；确需低于预设的，必须有工艺依据与留痕，且不得低于 limit。三档判定即由此而来（见 spec-provenance）。

## 3. P1 规则流程

1. 按层数选对应预设作基线（不要凭记忆填数）。
2. 在其基础上建网络类（电源/高速/普通），线宽 ≥ 预设最小值；差分对按阻抗计算结果设置（阻抗需官方计算器 + 板厂确认，目标阻抗数字不等于线宽）。
3. 写回：`eda.pcb_Drc.overwriteCurrentRuleConfiguration(ruleConfiguration)`；网络类 `createNetClass(name, nets, color)`、差分 `createDifferentialPair(...)`。
4. 保存规则配置快照作为证据；规则被放宽会让 DRC 一并放宽，**所以 DRC 通过不等于满足工艺**。
5. **规则门禁（离线）**：`python scripts/rules_check.py --config <当前规则.json> --process process.json`（当前规则用 `bridge_client.py exec` 执行 `rules_check.py --dump-js` 打印的那一句取回）。它把规则里的线宽/线距/焊盘距/板边/过孔/孔距/阻焊扩展下限当作“实测值”，按三档对照嘉立创工艺：低于极限→BLOCK，介于极限与建议→WARN。官方三套预设自测全 PASS。注意这检查的是**规则值**，不是设计实际值；设计实际是否违规由 EDA 的 DRC 负责。

## 4. P2–P4 要点

- **布局**：模块分区、去耦就近、天线净空（模组天线端禁铺铜/走线/摆件）、板边与孔位；`autoLayout` 仅作候选，且先 `typeof` 判断。
- **布线**：关键网络优先；`autoRouting` 内部 900s 硬上限，大板分网络批次；铺铜重建后必须 **save → 重载 → 再 DRC**。
- **评审（G4）**：`drc_check.py`（记录规则预设名）+ AI 逐层读图。DRC 返回的 `Connection Error` 须全部清零才能进入导出放行。
- 板框用 11 层 Polyline；槽孔用挖槽区域；有铜槽最小宽 双面 0.5 / 多层 0.35mm，无铜槽 1.0mm。

## 5. 边界

线距、焊盘距、阻焊桥、孔环、板边等**几何检查由 EDA 自身 DRC 负责**，本 skill 不重复实现。本 skill 不做阻抗求解、SI/EMC/热、电流承载分析；这些需要外部工具/实测，只在 G4 中作为人工清单列出，不得在报告里写成“已验证”。

# 阶段 → eda.* 接口速查

完整签名以 `easyeda-api/references/classes/<类名>.md` 为准；**不要猜签名**，文档没有的就是不存在。以下方法名均已对照该字典核实存在（2026-10-30）。多数为 BETA。

| 阶段 | 目的 | 接口 |
|---|---|---|
| 通用 | 当前文档/工程 | `dmt_SelectControl.getCurrentDocumentInfo()`、`dmt_Project.getCurrentProjectInfo()` |
| 通用 | 打开文档/保存 | `dmt_EditorControl.openDocument(uuid)`、`sch_Document.save()`、`pcb_Document.save()` |
| 通用 | 版本 | `sys_Environment.getEditorCurrentVersion(onlySemantic)` |
| S2 | 放置器件 / 连线 | `sch_PrimitiveComponent.create(...)`、`sch_PrimitiveWire.create(line, net)`、`sch_Primitive*.getAll()` |
| S3 | 原理图 DRC | `sch_Drc.check(strict, userInterface, includeVerboseError)` |
| P1 | 读规则 | `pcb_Drc.getAllRuleConfigurations(includeSystem)`、`getCurrentRuleConfiguration()`、`getCurrentRuleConfigurationName()`、`getNetRules()`、`getRegionRules()` |
| P1 | 写规则 | `pcb_Drc.overwriteCurrentRuleConfiguration(cfg)`、`overwriteNetRules(...)`、`createNetClass(name, nets, color)`、`createDifferentialPair(name, pos, neg)` |
| P2 | 原理图→PCB | `pcb_Document.importChanges(uuid)`；`autoLayout()`（先 typeof） |
| P2/P3 | 器件/走线/过孔/焊盘 | `pcb_PrimitiveComponent / Line / Via / Pad .getAll()、create、modify、delete` |
| P2 | 板框 | `pcb_PrimitivePolyline.create(net, layer, polygon, lineWidth)`、`pcb_MathPolygon.createPolygon([...])` |
| P3 | 布线 | `pcb_Document.autoRouting(props)`（先 typeof；900s 上限）、`clearRouting(type)` |
| P4/M1 | PCB DRC | `pcb_Drc.check(strict, userInterface, includeVerboseError)`（verbose=true 返回分类数组） |
| M2 | Gerber | `pcb_ManufactureData.getGerberFile(fileName, colorSilkscreen, unit, digitalFormat, other, layers, objects)` → `File` |
| 通用 | 修改图元 | PCB 用 `prim.toAsync()` → `setState_*()` → `done()`；SCH 用类级 `modify()` |

## 禁用（红线）

`pcb_ManufactureData.placePcbOrder / placeSmtComponentsOrder / placeComponentsOrder`、`sch_ManufactureData.placeComponentsOrder / placeSmtComponentsOrder`：会真实开订单页。`bridge_client.py` 已拦截前三者的名称。

## 导出接口

| 用途 | 接口 | 备注 |
|---|---|---|
| BOM | `pcb_ManufactureData.getBomFile(fileName, 'csv'|'xlsx', ...)` | 实测输出 UTF-16+制表符 |
| 坐标 | `pcb_ManufactureData.getPickAndPlaceFile(fileName, 'csv', 'mm')` | 单位传字符串；坐标值带 mm 后缀 |

**禁用/不使用**：`getPdfFile`、`getSvgFile`、`getPngFile`、`getDxfFile`（实测卡死 EDA，默认拦截）；`getNetlistFile` 不在范围。

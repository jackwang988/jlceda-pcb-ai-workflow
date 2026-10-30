# M1/M2 导出与复核 Gerber（BOM/坐标见 bom-cpl.md）

## 步骤

```bash
# 0) 准备工艺声明（用户给，不猜）：assets/process.template.json → process.json
# 1) 预检：原生 DRC 清零
python $S/scripts/drc_check.py
# 2) 导出（只读操作，不改工程、不上传、不下单；拒绝覆盖已有文件）
python $S/scripts/export_gerber.py --out <新目录>/<项目>_<日期>.zip --name <项目名>
# 3) 独立复核（直接读文件，不信 EDA 自述）
python $S/scripts/gerber_guard.py <zip> --process process.json [--extra-measurements m.json] [--strict]
```

`export_gerber` 产出 zip 与 `.manifest.json`（sha256、文件清单、EDA 版本、导出时间、工程名）。**导出成功 ≠ 内容正确**，必须过 `gerber_guard`。

## gerber_guard 覆盖范围

| 能做（从文件反推） | 不能做（必须 EDA API / 几何运算 / 人工，报告会逐项列出） |
|---|---|
| 文件清单齐全、内层数与声明层数一致 | 线距 `min_track_space` |
| 单位/坐标格式一致、M02/M30 收尾、无空文件 | 焊盘到线距离 `min_pad_to_track` |
| 板框闭合（端点度数奇偶）与外接尺寸 | 阻焊桥 `min_mask_bridge` |
| 铜层近空 / 无走线告警 | 丝印字高 `min_silk_height`、丝印到焊盘间隙 |
| 最小线宽（圆光圈 D01 画线）、丝印**文字**线宽 | 铜到板边距离 `min_copper_to_edge` |
| 最小金属化孔、插件孔、NPTH 孔、槽宽 | 过孔外径/孔环（需 API） |
| 过孔数量（可与 EDA API 的过孔数交叉核对） | 电路功能、SI/EMC/热 |

缺证据项默认以“局部模式”出报告（明确标 `NEEDS_EVIDENCE`，**不代表通过**）；`--strict` 下任何适用规则缺证据即 `BLOCKED`（退出码 2）。可用 `--extra-measurements` 补充来自 EDA API 的实测值（单位 mm）。

## 版本差异（实测）

| 项 | EDA 3.2.149 | EDA 4.1.93 |
|---|---|---|
| 坐标格式 | `FSLAX26Y26`（2:6） | `FSLAX45Y45`（4:5，与官方默认一致） |
| 钻孔文件 | `Drill_PTH_Through.DRL` + `Drill_NPTH_Through.DRL` | 另有 `Drill_PTH_Through_Via.DRL` 与 `Gerber_DrillDrawingLayer.GDD` |
| 导出文件数 | 13 | 15 |

重要：`Drill_PTH_Through_Via.DRL` 是 `Drill_PTH_Through.DRL` 的**过孔子集**，不是“另一半”（实测 PTH = 0.305mm 孔×51 + 1.5mm 孔×2 + 0.6mm 槽×4，Via = 0.305×51，过孔数 51 与 EDA API 一致）。插件孔最小孔径用“PTH 按孔径个数 − Via 按孔径个数”反推；`G85` 写法的是**槽**，宽度单独统计，不混入孔径。

## 解析注意（已固化在代码）

- 光圈选择写作 `G54Dnn*`（旧式），不是 `Dnn*`。
- `G36…G37` 内的 D01 是铺铜/多边形轮廓，不计入走线宽度。
- 丝印层按 `G04 <段名> Start*` 分段：**官方规范是“字符粗细”**，只用 `Text` 段；元件轮廓(`PolygonModel`)等图形的细线只作提示，避免误报。
- 只支持前导零省略 + 绝对坐标（`FSLA`）；其他格式 `BLOCK`，不得当作通过。
- 圆弧板框的外接尺寸为近似值。

## 放行（G5）

汇报：`gerber_guard` 全量输出（含“不评估”清单）、成本触发项（如 0.15mm 孔）、导出包 sha256、板框尺寸与用户声明是否一致、导出时间与 EDA 版本是否对应当前设计。之后用 `release.py` 封存（见 universal-workflow）。是否上传嘉立创、是否下单由用户自行决定，本 skill 不参与。

注：表中“不能做”的几何项（线距、焊盘距、阻焊桥、丝印字高等）按维护者的决定交给 **EDA 自身 DRC**；`gerber_guard` 报告里的“未覆盖”清单是提示，不是缺陷。

# 单位与 ID 常量

运行时 `EPCB_LayerId` / `EDMT_EditorDocumentType` 等枚举对象**不可用**（实测 `is not defined`，见 pitfalls EV-02），必须硬编码数值。下表已对照 `easyeda-api/references/enums/` 核实（2026-10-30）。

## 坐标单位（差 10 倍，最常见事故）

| 域 | 单位 | 换算 |
|---|---|---|
| **PCB** | 1 mil | 1 mm ≈ 39.37；60×40 mm = 2362×1575 |
| **原理图** | 0.01 inch = 10 mil | 1 mm ≈ 3.937 |

放置后必须回读坐标对账。`drc_check` 返回的坐标为画布坐标，仅作辅助，定位问题以**网络名 + 器件焊盘**为准（DR-02）。

## 文档类型 `documentType`

| 值 | 含义 | 值 | 含义 |
|---|---|---|---|
| 1 | SCHEMATIC_PAGE 原理图页 | 4 | FOOTPRINT 封装 |
| 3 | **PCB** | 5 | PROJECT 工程 |

PCB 不是 2。调用 `PCB_*` 接口前必须确认当前文档为 3；`SCH_*` 需为 1。

## 图层 ID（常用）

| ID | 名称 | ID | 名称 |
|---|---|---|---|
| 1 | TOP 顶层铜 | 7 / 8 | TOP / BOTTOM_PASTE_MASK 锡膏 |
| 2 | BOTTOM 底层铜 | 9 / 10 | TOP / BOTTOM_ASSEMBLY 装配 |
| 3 / 4 | TOP / BOTTOM_SILKSCREEN 丝印 | **11** | **BOARD_OUTLINE 板框** |
| 5 / 6 | TOP / BOTTOM_SOLDER_MASK 阻焊 | 12 | MULTI 多层（通孔焊盘） |
| 13 | DOCUMENT 文档 | 14 | MECHANICAL 机械 |
| 15… | INNER_n = 14 + n（INNER_1=15 … INNER_30=44） | 47 | HOLE 孔层 |
| 56 | DRILL_DRAWING 钻孔图 | 57 | RATLINE 飞线 |

## 其他实测约定

- 板框必须用 **Polyline** 画在 11 层，`pcb_PrimitivePolyline.create(net, layer, polygon, lineWidth)` —— **net 在 layer 前**（EV-03）。多边形：`eda.pcb_MathPolygon.createPolygon([x,y,'L',x2,y2,...])`。
- 槽孔用“挖槽区域”绘制（嘉立创官方提示）；槽与实心非镀铜孔最终体现在板框文件 GKO。
- 原理图引脚字段名是 `pinNumber` / `pinName`；`sch_PrimitiveWire.create(line, net)` 第二参数直接指定网络名，同名网络自动连通。

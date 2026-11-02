# 几何审计 JSON 证据契约 v1

调用：

    python scripts/geometry_audit.py --input evidence.json --json-out report.json

公共字段：`schema_version=1`、`domain=schematic|pcb`、`capture_source=eda_readback`、`items[]`。每项需唯一 `id`、`kind`、`bbox:[minX,minY,maxX,maxY]`、`bbox_source=eda_measured`。没有这些测量值则 `NEEDS_EVIDENCE`。`capture_source` 为输入声明，**不等于真实性证明**；必须保存 Bridge 只读回读、设计版本与测量日期等外部证据。

- **Schematic**：`unit=sch_api_10mil`、`drawable_bbox`（扣除图框和标题栏的可用区域）。对象 `kind` 可为 `component/label/port/title_block/annotation/wire/stub/section`。`wire` 需 `segment:[x1,y1,x2,y2]` 及 `net`。`section` 包含对象属于允许的版式结构。
- **PCB**：`unit=pcb_mil`、`board_bbox`、`board_geometry=eda_measured`。元件允许指定 `assembly_side=top|bottom`；获批准的连接器外伸需 `allow_mechanical_overhang=true` 及非空 `overhang_evidence`。**BBox 内不代表位于非矩形板轮廓内部**。
- **Keepout**：`kind=keepout`，带 `forbid:["component","trace","copper"]` 等适用对象类型，可配 `layers:[1,...]`，缺层信息不能放行。
- **USB-C / 天线**：角色 `role=usb_c_receptacle|antenna_module`，`edge=top|right|bottom|left`、`outward_direction=up|right|down|left`、`direction_evidence=verified_mechanical_geometry`。有 `antenna_module` 时须提供 `role=antenna_keepout` 的禁布区。

实例（合成值，不是实测）：

    {"schema_version":1,"domain":"schematic","unit":"sch_api_10mil",
     "capture_source":"synthetic","drawable_bbox":[0,0,200,150],
     "items":[{"id":"U1","kind":"component","bbox":[20,20,60,50],
               "bbox_source":"estimated"}]}

此例正确结果包含 `NEEDS_EVIDENCE`；不能因字段齐全就假装真实 EDA 验证。`sch_Primitive.getPrimitivesBBox([id])` 和 `pcb_Primitive.getPrimitivesBBox([id])` 可回读指定 ID 的真实包围盒；提供多个 ID 得到的是集合整体 BBox，不能假设它代表单件尺寸。图元 `kind`、net、层、外形朝向、板框、Keepout 与焊盘必须另行有权威来源。本版**不承诺已打通所有 Bridge 字段提取**。

判定：退出码 `1 = BLOCKED`（明确硬冲突），`2 = NEEDS_EVIDENCE`（缺来源或非法证据），`0 = PASS_SCOPE_ONLY / PASS_WITH_WARN`（仅表示本检查范围无阻断）。实际电路仍须 ERC、PCB DRC、Gerber/BOM/CPL 及 G1–G5 门禁。鼠线总长、交叉数、可布线评分没有被本脚本测量，不得虚构。
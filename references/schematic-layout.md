# 原理图：项目规格、模块与真实几何

适用于 S2/S3 原理图规划及 G1/G2 候选复核。只提炼参考图的功能分区、清晰连线与标题栏规律，不复制电路、参数或 LOGO。没有实现通用全局布局求解器；PCB 流程不变。

## 先建项目规格，再落图

从 `assets/schematic-project.template.json` 建立本项目规格。null/unresolved 是待决定项，不是合格样例。工程/原理图/正式页范围、型号、电气依据由本项目声明；测量页、备选方案和废弃页不混入正式清单。

1. 定义电源域、功能模块、器件成员和关键连接依据，再列模块接口。每个器件单元只有一个明确所属模块；功能模块先于虚线框，不固定模块数、页数或 MCU。
2. 按供电/信号依赖分页，强关联小回路优先同页。跨页网络登记源/目的模块、实际端口和作用域。多点网络可有多个端点；全局电源与普通信号以原生语义和网表判断连通，不由颜色或名字猜。
3. 隔离测量符号本体、引脚方向和可见文本，测量器件不进入正式 BOM。预留引脚 Stub、模块内线路、端口、标题与边距，联合安排器件；禁止先铺满器件再挤走线和文字。
4. 分批落图，保存并回读。旋转/镜像、换料、改型号或字号后重新测引脚与文字；不能仅按估算变换继续连线。只修改本轮授权模块，不默认清除整页导线。
5. 对照规格检查结构、实际网表、页内/全工程 ERC，再看总览与关键局部图。未覆盖项保留待证据，修正后提交当前版本 G1/G2；规格、实际工程、原始回读和评审证据一起绑定，不以语义相同绕过既有哈希失效规则。

## 模块与页面的几何规则

- 逐图元读取 `sch_Primitive.getPrimitivesBBox([id])`；集合 BBox 不能当作各器件尺寸。本体、引脚、Stub、导线、端口、可见位号/型号、标题和图框分别记录。
- 用稳定 module_id 关联模块、边框、标题和成员，不按 getAll 数组下标配对。同级模块框不非法重叠；明确父子关系允许包含。成员、标题和可见标签满足模块边距，不侵入绘图区外/标题栏。接口越过模块边界须明确登记。
- 换符号、长型号改变和布局修改后重新检查完整占位。页面容量包括文字和线路走廊，不能用器件面积占比或质心宣布“放得下”。失败时局部重排、扩大模块或功能分页，不靠缩小字号、隐藏标签消除冲突。
- 电源阅读优先自上向下，信号优先自左向右；保持正交连线和一致的文字方向。留白/质心为建议，不凌驾于电气拓扑。原理图上去耦画得近不证明实际 PCB 距离。
- 栅格、字号、间距带明确单位。SCH API 1 单位为 10mil，不使用未定义的 5raw，不固定所有项目为 5mil 栅格；不要为对齐改动库符号内部引脚。

## 连通与阅读分别核对

关键电源、复位、下载及小模拟回路优先以可追踪实线展示。跨模块/跨页、重复电源和复杂总线可用端口或标签，明确阅读入口；不要给每脚贴同名标签代替全部拓扑展示。

每个符号引脚明确 connected、nc（带依据/设计理由）或 unresolved。未知不能自动转 NC，不能靠 NC 消除 ERC。检查全量实际引脚及意外连接，不只比较已列连接点。多单元符号用 ref + subpart 区分，不合并不同单元。

连线创建前读已有网络属性，避免重复 NET。按实际网络值筛选 getAll 结果，不假定过滤参数总有效；已有线段须核对网络，不只按端点判重。合法端点/T 接与父子包含不误报；异网交叉核对连接语义和 ERC。多段线拆为实际线段，不都当四坐标线段。不要根据图上上下位置交换有极性器件的针脚含义。

实际网表符合计划只证明落图一致。电源、复位、启动、接口、极性和驱动拓扑仍按具体型号/手册独立复核。BI、专用 Off-page 等类型分别记录，未验证的类型不宣称等价。保存重开后核对标题/标签对象集合；黑图、未缩放和渲染失败单独报告，不仅凭它们断言导线丢失。

## 只读检查与边界

    python scripts/schematic_spec_check.py --spec schematic-project.json --evidence schematic-readback.json --json-out spec-report.json
    python scripts/geometry_audit.py --input page-geometry.json --json-out geometry-report.json
    python -B tests/test_schematic_spec_check.py

新工具检查项目归属、模块、标签边距、接口、引脚状态与覆盖；原几何工具检查导线/实体等粗冲突，其单页契约保持不变。新工具不连接 EDA、不运行 ERC、不读图、不改图或审批。退出 0 仅为 PASS_SCOPE_ONLY/PASS_WITH_WARN，1 为冲突，2 为缺证据/非法输入；报告拒绝覆盖。

### 项目规格 v1

根字段为 schema_version=1、domain=schematic、unit=sch_api_10mil、project_id、schematic_id，以及模板中的清单。几何和 layout 均使用该单位，不隐式转换。

| 字段 | 要求 |
|---|---|
| pages | 唯一 id、实际 drawable_bbox，可选 forbidden_bboxes（如标题栏） |
| modules | 唯一 id、title、page_id、parent_id（无则 null），明确 frame_required/title_required；purpose、critical_connections、datasheet_refs 为规划记录，脚本不认证电路/手册 |
| components | ref、可选 subpart、module_id、全量 pins；number 为字符串，state=connected/nc/unresolved。connected 有 net、net_scope=page/project；nc 有 reason 且不声明网络 |
| interfaces | 唯一 id、net、net_scope；endpoints 至少两个，可多点，每端有 module_id、port_id、native_type。所有实际原生端口须登记，同名局部网络不等于跨页连通 |
| layout | 明确 module_padding、label_gap，非负有限数；0 表示不要求正边距，不证明美观。脚本不决定栅格/字号或最优分页 |
| required_geometry | 本项目须完整采集的类型，至少 component/label。需要通道预审时包含 stub，不为通过删除应检类型 |

### 归一化证据 v1

这是多页补充契约，不直接接受旧单页输入。没有随包的已验证 Bridge 自动采集器；调用方保留原始回读再规范化，字段齐全不证明真实性。

- 根包含一致的 schema_version/domain/unit/project_id/schematic_id、非空 revision、capture_source=eda_readback、pages 和 project_erc。
- 每页有 id、items、coverage、erc、visual_review。items 有页内唯一 id、kind、bbox、bbox_source=eda_measured、module_id。kind 为 component/label/wire/stub/port/section/annotation。标题是 annotation + role=module_title + content；页面注释可用 role=page_note，不归模块。
- component 有 ref/subpart 和全量 pins，每脚有 number、net、net_scope、原生 no_connect 布尔值。Stub 有 component_key（U1 或 U1.A）、pin_number、net/net_scope、segment=[x1,y1,x2,y2]，连接引脚另有实际 x/y。每个连接引脚一条引出 Stub，后续路径记 wire；通道碰撞另作几何审计。
- label 可带 parent_id，父子同页同模块。port 有 net/net_scope/native_type。跨模块 wire 可带已登记 interface_id 与对应网络，允许越过模块框但不能越出绘图区；该声明不代替连通检查。
- coverage 每类记录完整性及数量，如 `"stub":{"complete":true,"count":0}`，数量须匹配 items。零对象也要声明；规格中连接引脚缺 Stub 仍为待证据，未要求的检查不宣称完成。
- 页内 erc 和根 project_erc 是已执行原生检查的摘要，source=native_erc、completed=true，fatal/error/warning/information 为非负整数。致命/错误阻断，警告单列，信息不算错误；空对象/false 不冒充零错误。
- visual_review 有 status=reviewed、非空字符串数组 capture_refs/observations，关联实际总览/局部图及观察。工具只验证记录结构，不认证图像；原始 ERC、截图、版本和报告一起接受 G1/G2 复核。

报告区分冲突、缺证据和警告，记录输入 SHA-256。它不证明采集完整/实时、物理电路正确、图片可读或全部规划要求满足，仍需原生 ERC、读图与工程评审。

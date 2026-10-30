# P0 取证记录（2026-10-30）

开发期一次性只读探针的结论，**不是运行时节点**（E0 能力探测已按维护者决定取消）。预设快照在 `data/rule-presets/`，探针脚本在 `tests/probes/`。环境：嘉立创EDA 专业版 4.1.93，`isJLCEDAProEdition=true`。

## 1. 预设规则可读（原“未查证项”已闭合）

`getAllRuleConfigurations(true)` 返回 7 项 `{name, config}`；名称见 pcb-rules。`config` 四块：`Spacing / Expansion / Physics / Plane`。预设比官方工艺页更保守（见 pcb-rules 第 2 节对照表）。此前搜索未能取得 DRC 页具体数值，现以 T0 实测为准。

## 2. DRC 返回结构

`pcb_Drc.check(true, false, false)` → `boolean`；`(true, false, true)` → 分类数组：

```
[{ name:'Connection Error', count, title, visible,
   list:[{ name:<网络名>, list:[{ errorType, errorObjType, ruleName, net, isFree,
        obj1:{typeName, suffix}, explanation:{ str, param, errData:{ position:{x,y}, layerIds, obj1, net, ... } } }] }] }]
```

基线：一块未布完的 2 层演示板，规则 `JLCPCB Capability(Two Layers Board)`，仅有 `Connection Error` 一类错误（按网络分组），无间距类错误；`documentType=3`。重复运行结果一致（可复现）。具体数量因含工程信息未随包分发。

## 3. Gerber 导出

- 新导出（4.1.93）15 个文件、78667 字节；旧包（3.2.149）13 个文件。
- 格式：旧 `FSLAX26Y26`，新 `FSLAX45Y45`。
- `Drill_PTH_Through_Via.DRL` 是 `Drill_PTH_Through.DRL` 的过孔子集；过孔数 51 与 API 一致。
- 钻孔里 `G85` 是槽（0.6mm 宽×4 个，经 parse_drill 核实）。
- 旧包底层铜仅 6 个图形操作、全包无走线（当时未布线），DRC 不会提示——促成 `GB.COPPER.EMPTY` / `GB.TRACK.NONE`。

## 4. 解析器自身踩过的坑（已修复并有测试）

1. 光圈选择为 `G54Dnn*`，原正则只认 `Dnn*` → 线宽全部漏测。
2. 把丝印层所有细线都当“字符线粗”会误报；官方原文是“字符粗细”，改为只用 `Text` 段。
3. 误以为 `_Via.DRL` 是“另一半”；实为子集，插件孔需用个数相减。
4. `==` 判定与 `tolerance_epsilon` 默认值曾在脚本里藏了裸阈值，被 `B07` lint 抓出，改为规范库必填。
5. 0.10mm 线宽曾因取 4mil 的 0.1016 而被误判阻断，改取官方并列数字中的较小者。

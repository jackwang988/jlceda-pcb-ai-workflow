# 触发测试用例

做法：每条在**全新会话**里发送，记录“实际加载了哪些 skill”。失败样本回写 SKILL.md 的 description 后复测。
通过标准：正例 ≥10/12 加载本 skill；反例 0 误触发；混淆例 4/4 路由正确。

> 现状：**尚未执行**。以下是用例清单，未经实测，不得对外宣称“触发率达标”。

## 正例（应加载本 skill）

| # | 用户输入 |
|---|---|
| P01 | 帮我检查这块板能不能按嘉立创工艺导出 Gerber |
| P02 | 导出 Gerber 前要做哪些检查 |
| P03 | 这个 Gerber 包的最小线宽和孔径够不够嘉立创的要求 |
| P04 | 嘉立创EDA 里怎么设置设计规则才符合嘉立创的制板工艺 |
| P05 | 帮我跑一下嘉立创EDA 当前 PCB 的 DRC 并整理问题 |
| P06 | 双层板 1oz，线宽 0.1mm 嘉立创能做吗 |
| P07 | 帮我把嘉立创EDA 里这块板导出 Gerber 并复核 |
| P08 | 这块板有没有违反嘉立创的丝印和阻焊要求 |
| P09 | 立创EDA 的器件选型，帮我核对 Type-C 引脚和封装对不对 |
| P10 | 我要做一块嘉立创EDA 的 PCB，从需求到出 Gerber 走一遍规范流程 |
| P11 | 帮我检查嘉立创EDA 导出的 BOM 和坐标文件能不能上传嘉立创SMT |
| P12 | 嘉立创EDA 导出的坐标文件为什么匹配不上，帮我规范化 |

## 反例（不应加载）

| # | 用户输入 | 应走 |
|---|---|---|
| N01 | 用 KiCad 画个飞控板 | KiCad 相关 skill（若有） |
| N02 | 写一个嘉立创EDA 的扩展插件 | 嘉立创EDA 扩展开发类 skill |
| N03 | 解释一下 LDO 压差是什么 | 无 skill |
| N04 | 帮我润色这篇公众号文章 | 写作类 skill |
| N05 | 帮我在嘉立创下一个 SMT 订单并付款（下单不在范围，应说明并拒绝代下单） | 不应代为下单 |
| N06 | 把我的原理图 PDF 按公司 checklist 评审一遍 | 原理图评审类 skill（若有） |

## 混淆例（路由到正确 skill）

| # | 用户输入 | 期望 |
|---|---|---|
| C01 | 嘉立创EDA，启动！ | easyeda-api（建立 Bridge）；之后若是设计流程任务再叠加本 skill |
| C02 | 查一下 pcb_PrimitiveVia 的 API 签名 | easyeda-api |
| C03 | 评审这张原理图 PDF（按公司 checklist） | 原理图评审类 skill（若有） |
| C04 | 改一下这个 .eext 扩展的菜单 | 嘉立创EDA 扩展开发类 skill（如官方 extension-dev-skill） |

## 已知风险

`easyeda-api` 的 description 含 “PCB / schematic / EDA / 原理图” 等泛词，可能抢触发。本 skill 的 description 因此刻意使用“制板工艺 / 导出前检查 / Gerber / BOM坐标 / 设计规则门禁”等区分词，并在 SKILL.md 首段声明“需要通道时先加载 easyeda-api”。不修改 easyeda-api（第三方，升级会被覆盖）。

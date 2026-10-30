# 规范来源、冲突与更新

## 来源分级

| 级别 | 来源 | 可作数值依据？ |
|---|---|---|
| **T0** 客户端实测 | 用户本机嘉立创EDA 内 API 读出的预设规则、版本号 | ✅ 最高（反映实际环境） |
| **T1** 官方工艺/规范页 | jlc.com/portal/vtechnology.html、jlc-smt.com 工艺与规范文档、prodocs.lceda.cn、docs.lceda.cn | ✅ |
| **T2** 官方社区/教程 | wiki.lceda.cn、官方公众号 | ⚠️ 仅作旁证，数值须被 T1 印证 |
| **T3** 第三方文章 | 博客/知乎等 | ❌ **禁止入库**（`spec_check --validate-data` 会拒绝） |

## 入库要求（脚本强制）

每条规则必须有：`id / name / key / op`；`limit` 或 `recommended` 至少一个；每个阈值带 `src`（已在 `sources` 登记，含 `tier/url/fetched_at`）和 **`quote` 原文片段**；`tolerance_epsilon` 必须在规范库里声明（脚本不设默认值）。`python scripts/spec_check.py --validate-data` 校验，当前 29+20 条 0 问题。

## 站点口径

默认**国内站 jlc.com**（与嘉立创EDA 同生态）。国际站 jlcpcb.com 数值不同（如板厚上限 4.8 vs 4.5mm），不混用；如需国际站，应新增独立的数据文件而不是改现有值。

## 已登记的官方口径冲突（`data/jlc-smt-capabilities.json` → `conflicts`）

| # | 主题 | 一处 | 另一处 | 处理 |
|---|---|---|---|---|
| C-1 | 阻容间距 | 国际站 0402–0402 约 0.15–0.18mm（最低可贴） | 国内 SMT P1 ≥1mm（良率推荐） | 国内口径：1mm 作 recommended，limit 留空 |
| C-2 | 工艺边宽度 | SMT 规范 5–8mm，最小 3mm | PCB 工艺页“SMT 需要 5mm” | limit=3.0，recommended=5.0 |

另有一类**不是冲突**但易混淆：T0 预设比 T1 工艺页更保守（如多层 1oz 线宽 0.102 vs 0.0889mm）。这是“建议 vs 极限”的关系，用三档判定表达（见 pcb-rules 第 2 节）。

## 官方“mm 与 mil 同行并列”的取值

官方常写 “0.10mm（4mil）”，而 4mil=0.1016mm，两者四舍五入不一致。**limit 取较小者**（如 0.10、多层 0.0889），避免把 0.10mm 这种常用合规线宽误判成阻断；该判断记录在规则的 `rounding_note`。

## 更新机制

1. 出厂前（G5）人工复核：打开 T1 来源页，抽查 `quote` 是否仍与页面一致。
2. 改规则：只改 `data/*.json`，更新 `fetched_at` 与 `quote`，跑 `--validate-data` 与 `tests/run_tests.py`。
3. 人读表（如将来的 `jlc-process-*.md`）应由 data 生成，**不得手改**，避免文档与代码两套数。
4. `python scripts/spec_drift.py`（联网，只报告不改库）：抽出每条 quote 里的数字，检查是否仍出现在官方页面。状态：OK / DRIFT_SUSPECT（数字缺失，人工核对）/ UNREADABLE（页面抓到空壳，**不能据此说没漂移**）/ UNREACHABLE。2026-10-30 试跑：58 处 OK，`jlc-pcb.com` 返回 403、`jlc-smt.com/vtechnology` 的 1 条 BGA 球距读不到（JS 渲染），这两处须手动抽查。

## 未查证项（不得当事实用）

- 嘉立创官方 DRC 帮助页具体项目清单（官方 DRC 页链接曾 404）；以客户端实测预设为准。


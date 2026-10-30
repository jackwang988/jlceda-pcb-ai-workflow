# Bridge 运行要点

本 skill **不检查环境与配置**：Bridge、`run-api-gateway` 扩展由用户自行配好。通道不可用时，`bridge_client.py` 报 `BLOCKED` 并停止，不自行排障。通道说明与 API 字典见 `easyeda-api`。

## 调用方式（统一走 `scripts/bridge_client.py`）

```bash
python $S/scripts/bridge_client.py health               # 探活 + EDA 窗口
python $S/scripts/bridge_client.py exec code.js --out r.json   # 执行 JS，结果完整写文件（不截断）
python $S/scripts/bridge_client.py save                  # 保存原理图 + PCB
```

代码在 EDA 浏览器运行时里以 `async function(eda){...}` 执行：必须 `return` 结果；`console.log` 不回传；无 Node API；所有返回 Promise 的方法都要 `await`。

## 固化的规则（均来自实测，见 `data/known-pitfalls.json`）

| 规则 | 原因 |
|---|---|
| 只返回原始类型/裁剪后的字段，**不要 return EDA 对象** | 循环引用 → 序列化失败 → HTTP 500（BR-02） |
| HTTP 500 **必须读 body** | 真实错误（如 timed out）在 body，状态码会误导（BR-01） |
| 先 `openDocument(pageUuid)` 再操作该页 | 否则 `create` 直接 30s 超时（BR-01） |
| 分批：器件 ≤12、导线 ≤15–20 | 单次过重超时（BR-03） |
| 结尾 save，并回读计数对账 | 不 save 重启即丢整板（ST-01） |
| 取回大结果不截断 | 通用脚本 `[:8000]` 会切坏 base64（FL-01） |
| BETA 接口先 `typeof` 判断 | 版本差异：autoRouting/autoLayout 在 3.2.149 为 undefined（EV-01） |
| 默认超时 900s | 官方 autoRouting 内部另有 900s 硬上限，超时中间结果不提交（BR-04） |
| 升级 easyeda-api 后复查 `REQUEST_TIMEOUT_MS` | 升级会覆盖你对 bridge-server.mjs 的 30s→900s 补丁（BR-05） |

## 红线

`bridge_client.guard()` 在发送前扫描代码，命中 `placePcbOrder / placeSmtComponentsOrder / placeComponentsOrder` 直接拒绝（已有测试 B-*）。这些接口会真实打开订单页并产生订单数据。

## 状态与多窗口

- `openProject()` 会丢弃未保存修改，调用前必须先 save。
- 多个 EDA 窗口时需先选窗口：`POST /eda-windows/select`；`bridge_client` 默认用 active 窗口。
- 开发期曾在 EDA 4.1.93 上验证（2026-10-30）；`autoRouting`/`autoLayout`/`importChanges` 均可用，**但仍应在调用前 `typeof` 判断**，因为 skill 不负责保证用户环境版本。

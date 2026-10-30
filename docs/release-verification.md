# 公开版复核记录 / Public release verification

日期：2026-10-30。范围：本仓库当前**源文件与所附合成测试夹具**，不涵盖使用者后续创建的工程、私有环境和 GitHub 历史。

## 隐私与供应链

- 本仓库没有 `.git` 历史随包，公开发布时务必**新建空仓库**，只上传脱敏目录，勿从未审查的私有仓库直接 push 全部历史。
- 移除了先前测试程序中拼接保存的个人/历史工程 ID；`tools/privacy_scan.py` 检查邮箱、用户绝对路径、RFC1918 内网地址、内部域名、常见 API token、SSH 私钥头、URL 内置密码和典型密钥赋值。
- 运行 `python tools/privacy_scan.py .` 检查本包；结果：0 个命中。**这不能从数学上保证不存在所有类型的敏感内容**，公开前仍需人工复核新增文件。
- 所有自带夹具由 `tools/make_fixtures.py` 生成，BOM/坐标与 Gerber 均为合成样例。真实 EDA 设计文件不分发。
- `127.0.0.1:49620–49629` 是上游 Bridge 本机回环地址，不是公司或家庭的敏感公网地址；官方制造工艺 URL 是公开引用。
- 不包含真实 PCB 工程、BOM 采购账号、订单密钥、设备连接凭证或配置文件；`.gitignore` 拦截常见本地文件。GitHub Actions 在不同 Python 与系统上做静态和离线回归，但仓库发布前运行状态须以实际 CI 为准。

## 实测

- `python tools/validate_skill.py .` → 32/32 PASS
- `python tools/make_fixtures.py --check` → PASS
- `python tools/privacy_scan.py .` → PASS (0 matches)
- `python -B tests/run_tests.py` → 156/156 PASS
- `tools/gen_flow_doc.py` 生成 `docs/workflow.html`，统计直接来自当次离线测试

## 仍不能保证的部分

- **未在此次复核环境连接嘉立创EDA/Bridge**，无法声称已完成新用户机器上的真实一键绘图、原生 DRC 或真实导出端到端验证。
- 开发期曾在特定版本 EDA 的两层板上验证，不代表所有层数、版本或工厂工艺均支持。
- 每次制造前需核对最新官方规则，尤其多层、特殊工艺和国际站；任何零阻断结果都不等于生产批准。
- Bridge 的 JavaScript 执行通道有较高权限，应只在受信任的本机 EDA 与受控脚本下使用；不要运行未经审查的远程 JS。

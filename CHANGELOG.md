# Changelog

格式参考 Keep a Changelog；版本号遵循语义化版本。0.x 表示功能完整但尚未经过足够多真实工程与触发实测。

## [0.9.0] — 2026-10-30

首个可分享版本（beta）。

### 范围
需求 → 原理图 → PCB → 导出 **Gerber + BOM + 坐标** → 封存。不含下单、上传、CAM/DFM 外部复核、样机与 ECO。

### 包含
- 规范库 `data/`：PCB 制板工艺 29 条、SMT 设计规则 20 条（声明贴片才启用）、BOM/坐标 24 条；每条带来源、抓取日期与官方原文片段；三档判定（limit / recommended / cost_trigger）。
- 脚本（仅 Python 标准库）：`bridge_client` `drc_check` `export_gerber` `gerber_guard` `spec_check` `rules_check` `bom_cpl_guard` `export_bom_cpl` `workflow` `release` `spec_drift`。
- 流程：G1–G5 对话确认门禁（必须带用户原话、按序、绑定文件哈希、文件变化自动失效）；封存前当场重新复核。
- 红线：永不调用下单类接口；已知会卡死 EDA 的导出接口默认拦截；缺工艺声明一律 BLOCKED，不猜工艺。
- 测试：缺陷注入 + 单元共 156 项（离线），全部使用**合成夹具**（`tools/make_fixtures.py` 生成，字节级可复现）。

### 已知限制
- 触发用例（`tests/trigger_cases.md`，22 条）**尚未在真实会话中实测**。
- 在线端到端（`--live`）仅在 EDA 4.1.93 上验证；Gerber 解析在 3.2.149 与 4.1.93 的导出上验证过，且只验证过 **2 层板**，内层/内电层解析未经真实多层文件验证。
- 规范数据取自国内站（jlc.com），国际站（jlcpcb.com）数值不同且未提供。
- 运行时输出为中文；英文只有本 README 与术语对照。
- 无法验证 C 编号与器件是否对应、极性/旋转是否正确；几何类检查（线距/焊盘距/阻焊桥/孔环/板边）交给 EDA 自身 DRC。
- `jlc-pcb.com` 站点对程序化访问返回 403，`spec_drift` 对它无法比对，需人工抽查。

### 规范符合性
- 对照公开的 Agent Skills 规范（agentskills.io/specification）逐条自检：`python tools/validate_skill.py`（32 项）；回归测试 V01–V06 同时验证校验器本身能抓到典型违规。
- 修复了发布前自检发现的两个真实问题：frontmatter 的 `metadata:` 行里混入了字面量 `/n`（会使 YAML 无法解析）；全包文本文件使用 CRLF 换行（已统一为 LF）。
- `description` 补充了“当用户…时使用”场景句与常用说法（打样、生产文件、制造文件、钻孔、阻焊、贴片文件）。

### 隐私
- 发布前已移除所有真实设计数据；回归测试 `B08` 会扫描整个包，发现个人/本机/项目标识即失败。

### 公开发布复核（2026-10-30）
- 移除公开测试脚本中旧有个人/工程标识的拼接字符串，改为通用隐私特征扫描（包括嵌套 ZIP 与 UTF-16 CSV）。
- 合成 Gerber 测试 ZIP 改为无压缩、固定元数据，确保不同 zlib 版本生成的夹具可以逐字节复现。
- 测试阻止产生 Python 字节码缓存，避免其干扰结构与分发检查。
- 补充跨平台离线 CI、安装指南、Bridge 分层依赖说明、忽略本地项目和私密文件的规则。
- 修正生成的流程 HTML 里误称“随仓库提供真实设计文件”的旧描述。

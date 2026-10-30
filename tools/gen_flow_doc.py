#!/usr/bin/env python3
"""生成《运行流程与节点设计规则》HTML。规则表、踩坑表、测试数量全部从 data/ 与实际测试结果读取，不手敲数字。
用法：python tools/gen_flow_doc.py <输出.html>     （纯离线）
"""
import html
import json
import re
import subprocess
import sys
sys.dont_write_bytecode = True
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = lambda f: json.loads((ROOT / "data" / f).read_text(encoding="utf-8"))  # noqa: E731
E = html.escape

PCB, SMT, BC, PIT, GL = (D("jlc-pcb-capabilities.json"), D("jlc-smt-capabilities.json"), D("jlc-bom-cpl-spec.json"),
                         D("known-pitfalls.json"), D("jlc-gerber-layout.json"))

# 各脚本实际能产出的"实测键"（与脚本一致；用于标注每条规则由谁来查）
RULES_CHECK_KEYS = {"min_track_width", "min_track_space", "min_pad_to_track", "min_mask_bridge", "min_copper_to_edge",
                    "min_plated_drill", "min_via_outer", "min_via_hole_edge_gap", "min_mask_expansion"}
GERBER_KEYS = {"min_track_width", "min_silk_width", "min_plated_drill", "min_th_drill", "min_npth_drill",
               "min_slot_plated_width", "min_slot_npth_width", "min_board_dim"}


def _verify_key_sets():
    """“谁来查”标签必须与真实代码一致，对不上就报错（文档不能说谎）。"""
    sys.path.insert(0, str(ROOT / "scripts"))
    import gerber_guard as gg
    import rules_check as rc
    presets = json.loads((ROOT / "data" / "rule-presets" / "_all_raw.json").read_text(encoding="utf-8"))
    meas, _ = rc.extract_measurements(presets["JLCPCB Capability(Two Layers Board)"], 1)
    if set(meas) != RULES_CHECK_KEYS:
        raise AssertionError(f"rules_check 实际产出键 {sorted(set(meas))} != 文档声明 {sorted(RULES_CHECK_KEYS)}")
    zp = ROOT / "tests" / "fixtures" / "synthetic_2layer_fs45.zip"
    _items, gm, _n, _l = gg.check_package(gg.read_package(zp), {"layers": 2, "copper_oz": 1})
    extra = set(gm) - GERBER_KEYS - {"board_w", "board_h", "via_count"}
    if extra:
        raise AssertionError(f"gerber_guard 实际产出了文档没列的键 {sorted(extra)}")
    used = {r["key"] for r in PCB["rules"]}
    dead = (RULES_CHECK_KEYS | GERBER_KEYS) - used
    if dead:
        raise AssertionError(f"文档声明的键在规范库里没有对应规则: {sorted(dead)}")


def mm(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return E(str(v))
    s = f"{v:g}"
    return s


def fmt_spec(spec):
    if not spec:
        return "<span class=mut>—</span>"
    if "value" in spec:
        return mm(spec["value"])
    if "set" in spec:
        return "{" + ", ".join(mm(x) for x in spec["set"]) + "}"
    if "by" in spec:
        return "<br>".join(f"<span class=k>{E(k)}</span> {mm(v)}" for k, v in spec["by"].items())
    return ""


def fmt_applies(a):
    if not a:
        return "全部"
    out = []
    names = {"layer_class": "层别", "copper_oz": "铜厚oz", "layers_ge": "层数≥", "layers_lt": "层数<", "thickness_le": "板厚≤"}
    for k, v in a.items():
        if k == "when":
            for kk, vv in v.items():
                out.append(f"{kk}∈{'/'.join(map(str, vv))}")
        else:
            out.append(f"{names.get(k, k)} {'/'.join(map(str, v)) if isinstance(v, list) else v}")
    return "；".join(out)


def who(rule):
    k = rule["key"]
    if rule.get("from") == "process":
        return [("声明", "t-info", "process.json 声明值直接对照（spec_check）")]
    r = []
    if k in RULES_CHECK_KEYS:
        r.append(("规则", "t-blue", "rules_check：核对 EDA 设计规则里的下限"))
    if k in GERBER_KEYS:
        r.append(("文件", "t-green", "gerber_guard：从导出的 Gerber/钻孔反推"))
    r.append(("DRC", "t-gray", "设计实际值由 EDA 自身 DRC 负责") if k in RULES_CHECK_KEYS or k in GERBER_KEYS else ("手填", "t-amber", "无自动抽取；用 spec_check --measurements / gerber_guard --extra-measurements 手动提供实测值"))
    return r


def tags(lst):
    return " ".join(f'<span class="tag {c}" title="{E(t)}">{E(n)}</span>' for n, c, t in lst)


def src_label(spec, sources):
    if not spec or spec.get("src") not in sources:
        return ""
    s = sources[spec["src"]]
    return f'{E(s["tier"])}'


def rule_table(data, with_who=True):
    rows = []
    for r in data["rules"]:
        lim, rec = r.get("limit"), r.get("recommended")
        quote = (lim or rec or {}).get("quote", "")
        srcid = (lim or rec or {}).get("src")
        s = data["sources"].get(srcid, {})
        cost = r.get("cost_trigger")
        extra = f'<div class=cost>⚑ 成本触发：&lt;{mm(cost["below"])}mm —— {E(cost["quote"])}</div>' if cost else ""
        note = f'<div class=mut>注：{E(r["note"])}</div>' if r.get("note") else ""
        rows.append(
            f'<tr><td class=id>{E(r["id"])}<div class=mut>{E(r["key"])} {E(r["op"])}</div></td>'
            f'<td><b>{E(r["name"])}</b><div class=q>{E(quote)}</div>{extra}{note}</td>'
            f'<td class=num>{fmt_spec(lim)}</td><td class=num>{fmt_spec(rec)}</td>'
            f'<td>{E(fmt_applies(r.get("applies")))}</td>'
            + (f'<td>{tags(who(r))}</td>' if with_who else "")
            + f'<td class=mut>{E(s.get("tier", ""))}<br>{E(s.get("fetched_at", ""))}</td></tr>')
    head = ("<tr><th>ID / 比较键</th><th>规则（官方原文片段）</th><th>极限 limit<br><small>低于=BLOCK</small></th>"
            "<th>建议 recommended<br><small>低于=WARN</small></th><th>适用条件</th>"
            + ("<th>谁来查</th>" if with_who else "") + "<th>来源</th></tr>")
    return f"<table class=rules><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table>"


def smt_table():
    return rule_table(SMT, with_who=False).replace("<th>来源</th>", "<th>来源</th>")


def bc_table():
    rows = []
    for r in BC["rules"]:
        s = BC["sources"][r["src"]]
        cls = "t-red" if r["severity"] == "BLOCK" else "t-amber"
        rows.append(f'<tr><td class=id>{E(r["id"])}</td><td><span class="tag {cls}">{E(r["severity"])}</span></td>'
                    f'<td class=q2>{E(r["quote"])}</td><td class=mut>{E(s["tier"])}</td></tr>')
    return ("<table class=rules><thead><tr><th>ID</th><th>级别</th><th>规则（官方原文片段）</th><th>来源</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")


GB_CHECKS = [
    ("GB.LAYERS.MATCH", "BLOCK", "声明层数与包内内层文件数一致（内层数 = 层数 − 2）"),
    ("GB.FILE.REQUIRED", "BLOCK", "必需文件齐全：" + "、".join(x["name"] for x in GL["required"])),
    ("GB.FILE.EXPECTED", "WARN", "通常应有的文件：" + "、".join(x["name"] for x in GL["expected"])),
    ("GB.FILE.EMPTY", "BLOCK", "不允许 0 字节空文件"),
    ("GB.PARSE", "BLOCK", "无法解析 / 不支持的坐标格式（仅支持前导零省略+绝对坐标）一律阻断，不得当作通过"),
    ("GB.END.M02 / M30", "BLOCK", "Gerber 以 M02* 收尾、钻孔以 M30 收尾（防截断）"),
    ("GB.FMT.CONSIST / UNIT.CONSIST", "BLOCK", "各层坐标格式一致、单位一致（mm/in 不得混用）"),
    ("GB.OUTLINE.CLOSED / EMPTY", "BLOCK", "板框非空且闭合（端点度数奇偶判定），并给出外接尺寸"),
    ("GB.DRILL.VIA_SUBSET", "BLOCK", "*_Via.DRL 必须是 PTH 钻孔的子集（按孔径计数）"),
    ("GB.COPPER.EMPTY", "WARN", "铜层图形操作数过少（启发式阈值取自 data，不是官方规范）"),
    ("GB.TRACK.NONE", "WARN", "所有铜层都没有走线：疑似未布线或导出遗漏，不得视为线宽合格"),
]


def gb_table():
    rows = "".join(f'<tr><td class=id>{E(i)}</td><td><span class="tag {"t-red" if s == "BLOCK" else "t-amber"}">{s}</span></td><td>{E(m)}</td></tr>' for i, s, m in GB_CHECKS)
    return f"<table class=rules><thead><tr><th>ID</th><th>级别</th><th>检查内容</th></tr></thead><tbody>{rows}</tbody></table>"


def pit_table(ids=None):
    rows = []
    for p in PIT["pitfalls"]:
        if ids and p["id"] not in ids:
            continue
        rows.append(f'<tr><td class=id>{E(p["id"])}</td><td>{E(p["symptom"])}</td><td>{E(p["countermeasure"])}</td>'
                    f'<td class=mut>{E(p["evidence"])}</td></tr>')
    return ("<table class=rules><thead><tr><th>ID</th><th>现象（实测）</th><th>对策</th><th>证据</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")


def rid(*ids):
    """节点内引用：规则库(PCB/SMT)或踩坑库的 ID。两边都找不到就报错，保证文档不悬空。"""
    allr = {r["id"]: r["name"] for r in PCB["rules"] + SMT["rules"]}
    allr.update({p["id"]: p["symptom"][:60] for p in PIT["pitfalls"]})
    out = []
    for i in ids:
        if i not in allr:
            raise KeyError(f"文档引用了不存在的规则/踩坑 ID: {i}")
        out.append(f'<span class=chip title="{E(allr[i])}">{E(i)}</span>')
    return " ".join(out)


# ───────────────────────── 节点定义（与 references/universal-workflow.md 一致） ─────────────────────────
NODES = [
    dict(id="E1", name="工程保护", group="工程保护", eda="读", who="Agent + 用户",
         goal="动手前先留底：知道现在工程里有什么，之后才能对账；并约定“每轮必 save”。",
         inp="当前打开的 EDA 工程",
         act=["记录基线计数：器件 / 导线 / 网络 / 板框", "约定写入类节点结尾必须 save", "重大改动在新 Board 里做；调用 openProject() 前先 save（会丢弃未保存修改）"],
         cmd="Agent 用 bridge_client.py exec 执行只读 JS 读计数；写入后 bridge_client.py save",
         out="基线计数（对话中记录）", gate="—",
         rules=[("自动", "不 save 重启即丢整板（实测）", "ST-01"), ("自动", "PCB=1mil、原理图=10mil，放置后回读坐标对账", "UN-01")],
         pit=["ST-01", "UN-01", "BR-05"], back="—"),
    dict(id="A1", name="需求量化", group="需求架构", eda="否", who="Agent + 用户",
         goal="把口述需求变成可验收的条目；未知项显式列出，不替用户拍板。",
         inp="用户口述需求",
         act=["需求表：ID、来源、量化验收条件", "未知参数列“待确认”，不猜（不猜电流、阻抗、叠层）"],
         cmd="无脚本（对话）", out="需求表", gate="—",
         rules=[("原则", "缺规格 / 缺证据 → 保持未决，不得默认通过", "")], pit=[], back="需求变更 → 回到本节点，下游确认自动失效"),
    dict(id="A2", name="工艺声明", group="需求架构", eda="否", who="用户（Agent 协助填写）",
         goal="告诉 skill 这块板按什么工艺做。它决定后面每一条阈值取哪一档——所以必须用户声明，不能猜。",
         inp="需求表",
         act=["workflow.py init <目录> --apply 生成 process.json 模板（字段全为 null）", "必填：layers、copper_oz；其余：thickness_mm / surface / edge / mask_color / smt",
              "层别映射：1层→single，2层→double，≥3层→multi；edge 默认 routed(锣边)；smt 默认 null(不涉及贴片)"],
         cmd="python scripts/workflow.py init <工程目录> --apply；然后用户编辑 process.json", out="process.json", gate="—（后续 G1 起绑定其哈希）",
         rules=[("自动", "板厚只能取常规集合；外层铜厚、表面处理与层数的限制（process 声明值直接对照）", "PCB.BOARD.THICKNESS"),
                ("自动", "", "PCB.COPPER.OUTER_DOUBLE"), ("自动", "", "PCB.COPPER.OUTER_MULTI"), ("自动", "", "PCB.FINISH.HASL_NOT_FOR_6L"), ("自动", "", "PCB.FINISH.HASL_NOT_FOR_THIN")],
         pit=[], back="缺 layers / copper_oz → 所有复核任务 BLOCKED（退出码 2），不会默认 1oz"),
    dict(id="S1", name="选型", group="原理图", eda="可选(查库)", who="Agent（+ 用户）",
         goal="每个器件对照原厂 datasheet 核引脚、封装、关键值，避免“符号对不上实物”。",
         inp="需求表、BOM 草案",
         act=["核引脚数量与功能（实测事故：系统库 Type-C 只有 8 脚、无 D+/D−）", "核封装、焊盘、引脚 1、极性；同封装不等于兼容替代料",
              "关键值是否存在（实测：搜不到 1.66kΩ，用 2kΩ 安全替代并记录影响）", "阻容按具体型号精确搜（系统库没有通用 R/C）",
              "改“值”属性会清空“供应商编号”（官方），改后须重新分配"],
         cmd="Agent 经 exec 调 lib_Device.search / getByLcscIds（只读）", out="选型结论（对话 + 后续 BOM）", gate="并入 G2",
         rules=[("人工", "引脚 / 封装 / 关键值逐项对照 datasheet", ""), ("提示", "插件孔 / NPTH 孔径建议 ≥0.5mm（防油墨、喷锡堵孔）", "PCB.TH.DRILL_REC"),
                ("提示", "", "PCB.NPTH.DRILL_REC"), ("可选", "声明贴片(smt)时：最小 IC 脚距 / BGA 球距", "SMT.IC.PITCH_ECON"),
                ("可选", "", "SMT.IC.PITCH_STD"), ("可选", "", "SMT.BGA.PITCH_ECON"), ("可选", "", "SMT.BGA.PITCH_STD")],
         pit=["LB-01", "LB-02"], back="封装 / 引脚错 → 回本节点"),
    dict(id="S2", name="绘制", group="原理图", eda="写", who="Agent → EDA",
         goal="把选型落成原理图。重点是“别把 EDA 搞超时 / 别丢数据”。",
         inp="选型结论",
         act=["先 openDocument(pageUuid) 再放置，否则 30s 超时", "分批：器件每批 ≤12，导线每批 ≤15–20", "连线用 sch_PrimitiveWire.create(line, net)，第二参数直接给网络名，同名自动连通",
              "返回值只回原始类型，不要 return EDA 对象（循环引用→500）", "结尾 save + 回读计数对账"],
         cmd="bridge_client.py exec / save；chunks() 分批", out="原理图（EDA 内）", gate="—",
         rules=[("自动", "已固化到 bridge_client（读 500 的 body、不截断、分批、红线拦截）", "")], pit=["BR-01", "BR-02", "BR-03", "UN-01"], back="连接 / 参数错 → 回本节点"),
    dict(id="S3", name="评审", group="原理图", eda="读", who="Agent + 用户",
         goal="原理图能不能进 PCB：ERC 干净 + 逐功能读图 + 器件与原厂资料一致。",
         inp="原理图",
         act=["sch_Drc.check 做 ERC（无专用脚本，Agent 经 exec 调用）", "逐功能读图：电源、复位/启动、时钟、接口、保护、无源、未用引脚", "汇报并等用户编号答复"],
         cmd="Agent exec sch_Drc.check；workflow.py confirm --gate G1 / G2 --bind process.json", out="G1 原理图确认、G2 库/封装确认", gate="G1 + G2",
         rules=[("EDA", "ERC：未连接引脚清零", ""), ("人工", "电源 / 复位 / 时钟 / 接口电平 / 未用脚 / strapping 引脚逐项读图", ""),
                ("示例类问题", "典型“读图才能发现”的错误：模组内置 PSRAM 占用的 GPIO 不可外用；带板载天线的模组没有 RF 引出脚；LDO 压差撑不住单节锂电 3.0–4.2V；strapping 引脚被外部上下拉冲突。这类问题靠 datasheet 逐项对照，脚本不能代替", "")],
         pit=[], back="ERC 未清 / 读图有问题 → 回 S2；封装 / 引脚问题 → 回 S1"),
    dict(id="P1", name="设计规则", group="PCB", eda="读/写", who="Agent → EDA；rules_check 离线",
         goal="给 EDA 的 DRC 配一把“不低于嘉立创工艺”的尺子。DRC 只按当前规则查，规则被设松它照样放行，所以这一步是兜底。",
         inp="process.json、EDA 当前规则配置",
         act=["读官方预设：eda.pcb_Drc.getAllRuleConfigurations(true)（7 套 JLCPCB Capability，已存 data/rule-presets）", "按层数选对应预设作基线；预设 = 建议值，工艺页 = 极限值",
              "建网络类（电源 / 高速 / 普通）、差分对，线宽 ≥ 预设最小值；写回 overwriteCurrentRuleConfiguration",
              "取回当前规则 → rules_check.py 离线核对：规则里的下限当作“实测值”，按三档对照工艺"],
         cmd="rules_check.py --dump-js（打印取规则的单句 JS）→ bridge_client exec → rules_check.py --config rules.json --process process.json", out="规则快照 + 规则门禁报告", gate="—",
         rules=[("自动", "线宽下限", "PCB.TRACE.WIDTH_MIN"), ("自动", "线-线间距", "PCB.TRACE.SPACE_MIN"), ("自动", "焊盘-走线间距", "PCB.PAD.TO_TRACK"),
                ("自动", "过孔内 / 外径下限、孔到孔", "PCB.DRILL.PLATED_MIN"), ("自动", "", "PCB.VIA.OUTER_MIN"), ("自动", "", "PCB.VIA.HOLE_EDGE_GAP"),
                ("自动", "阻焊桥(焊盘-焊盘间距)、阻焊单边扩展", "PCB.MASK.BRIDGE_1OZ_COLOR"), ("自动", "", "PCB.MASK.EXPANSION_MIN"),
                ("自动", "走线 / 焊盘到板边（锣边 或 V 割）", "PCB.EDGE.ROUTED"), ("自动", "", "PCB.EDGE.VCUT")],
         pit=["PR-01"], back="规则低于极限 → 改规则（须有工艺依据并留痕）后重跑"),
    dict(id="P2", name="布局", group="PCB", eda="写", who="Agent → EDA + 用户",
         goal="分区、去耦、板边、孔位。自动布局只作候选。",
         inp="原理图→PCB（importChanges）后的飞线板",
         act=["importChanges(uuid) 把原理图导入 PCB（旧版本该接口恒 false，先 typeof 判断）", "分区；去耦就近；天线净空；板边与孔位", "autoLayout 先 typeof，仅作候选",
              "布局一动，G3 确认作废，须重审"],
         cmd="Agent exec；workflow.py confirm --gate G3 --bind <被确认文件>", out="G3 布局确认", gate="G3",
         rules=[("EDA DRC", "走线 / 焊盘距板边：锣边 / V 割（几何由 DRC 执行）", "PCB.EDGE.ROUTED"), ("EDA DRC", "", "PCB.EDGE.VCUT"),
                ("人工", "天线净空：模组天线端禁铺铜 / 走线 / 摆件（数值以模组 datasheet 为准；不是嘉立创规范）", ""),
                ("可选·手填", "声明贴片时：工艺边、Mark 点、器件间距、热阻焊盘（已入库，无自动抽取，需手动喂实测值）", "SMT.RAIL.WIDTH"),
                ("可选·手填", "", "SMT.MARK.COUNT"), ("可选·手填", "", "SMT.SPACING.PASSIVE"), ("可选·手填", "", "SMT.SPACING.IC")],
         pit=["EV-01"], back="布局错 → 在新候选修复后重审"),
    dict(id="P3", name="布线", group="PCB", eda="写", who="Agent → EDA",
         goal="把飞线布完，并保证铺铜后的最终状态被检查过。",
         inp="已确认的布局",
         act=["关键网络优先；autoRouting 先 typeof，内部有 900s 硬上限，大板分网络批次", "铺铜重建后 save → 重载 → 再 DRC（不要新旧铜并存时过检查）", "板框用 11 层 Polyline：create(net, layer, polygon, lineWidth)，net 在 layer 前"],
         cmd="Agent exec；bridge_client.py save", out="布完线的 PCB", gate="—",
         rules=[("自动", "已固化的操作规则", "")], pit=["BR-04", "EV-01", "EV-02", "EV-03"], back="走线错 → 在新候选修复"),
    dict(id="P4", name="PCB 评审", group="PCB", eda="读", who="脚本 + Agent + 用户",
         goal="DRC 清零，并确认 DRC 用的是哪套规则。",
         inp="完整 PCB",
         act=["drc_check.py：pcb_Drc.check(strict=true, ui=false, verbose=true)，整理成按网络的可读报告并记录规则预设名", "Connection Error 必须清零；几何违规（线距、焊盘距、孔环、板边等）以 DRC 结果为准",
              "AI 逐层读图", "汇报并等用户答复"],
         cmd="python scripts/drc_check.py [--json-out]；workflow.py confirm --gate G4", out="DRC 报告、G4 确认", gate="G4",
         rules=[("EDA DRC", "线距 / 焊盘距 / 孔环 / 板边 / 过孔等几何规则：由 EDA 自身 DRC 按 P1 配好的规则执行", ""), ("自动", "DRC 退出码：0 无错误 / 1 有错误 / 2 BLOCKED(通信失败、当前不是 PCB)", "")],
         pit=["DR-01", "DR-02"], back="DRC 有错 → 回 P3；规则问题 → 回 P1"),
    dict(id="M1", name="导出", group="制造", eda="读", who="脚本 → EDA",
         goal="把 Gerber、BOM、坐标从 EDA 完整取回本地，原样留证据。",
         inp="G4 通过的 PCB",
         act=["export_gerber.py：getGerberFile → base64 分块回传 → 校验字节数 → 校验 zip → 写 zip + manifest(sha256/EDA版本/工程名)；拒绝覆盖已有文件",
              "export_bom_cpl.py：getBomFile + getPickAndPlaceFile(单位传字符串 'mm') → 原生文件(UTF-16+TAB)留证 → 规范化为 UTF-8 逗号 CSV → 立即复核 → 写 manifest",
              "仅 PCB 页签下可导出，否则 BLOCKED；getPdf/Svg/PngFile 默认拦截"],
         cmd="python scripts/export_gerber.py --out <新.zip>；python scripts/export_bom_cpl.py --out-dir <目录> --prefix <名> --gerber <zip>", out="Gerber zip、BOM/CPL(原生+规范化)、manifest", gate="—",
         rules=[("自动", "导出完整性（字节数 + zip 校验）、不覆盖、不截断", "")], pit=["FL-01", "BR-06", "GB-01"], back="导出失败 → 查通信 / 当前页签；修设计后重新导出新文件"),
    dict(id="M2", name="复核", group="制造", eda="否", who="脚本（纯离线）+ 用户",
         goal="不信 EDA 的自述，直接读导出文件独立复核，并核对 BOM/坐标格式。",
         inp="Gerber zip、BOM、CPL、process.json",
         act=["gerber_guard.py：文件结构 + 格式 + 板框 + 从文件反推最小线宽 / 孔径 / 槽宽 / 板尺寸 / 丝印文字线粗 → 交 spec_check 三档判定",
              "bom_cpl_guard.py check --bom --cpl --gerber：BOM/CPL 格式硬规则、位号集合一致、坐标极差 ≤ 板尺寸（--gerber 自动取板框）",
              "汇报全量输出（含“不评估”清单、成本触发项、sha256）并等用户答复"],
         cmd="python scripts/gerber_guard.py <zip> --process process.json；python scripts/bom_cpl_guard.py check ...；workflow.py confirm --gate G5 --bind <zip/BOM/CPL>", out="复核报告、G5 确认", gate="G5",
         rules=[("自动", "Gerber 结构 / 格式 / 板框检查（见第 4 节）", ""), ("自动", "可由文件反推的工艺项", "PCB.TRACE.WIDTH_MIN"), ("自动", "", "PCB.DRILL.PLATED_MIN"),
                ("自动", "", "PCB.SILK.WIDTH_MIN"), ("自动", "", "PCB.BOARD.SIZE_MIN"), ("自动", "BOM / 坐标格式规则（条数见第 4.3 节）", "")],
         pit=["GB-02"], back="有阻断 → 回 P3 / P4，修后重新导出并重新确认（文件变化使门禁自动失效）"),
    dict(id="REL", name="封存", group="终点", eda="否", who="脚本（纯离线）",
         goal="把用户确认过的那一版冻结成带哈希清单的发布包。只在本地，不上传、不下单。",
         inp="G1–G5 全部确认的工程目录",
         act=["前置：process.json 已填；G1–G5 全 CONFIRMED（含“绑定文件未变化”）；Gerber / BOM / 坐标都在工程目录内且被 G5 绑定、哈希一致；BOM 与坐标必须成对",
              "当场重新复核 gerber_guard（+ bom_cpl_guard），任一不为 0 → 拒绝封存", "默认预览；--apply 才写 release/<版本>/（已存在则拒绝覆盖）",
              "写入：文件副本、process.json、workflow 快照、复核报告、manifest.json(sha256 + 5 道门禁留痕 + 声明)、README.txt"],
         cmd="python scripts/release.py <工程目录> --version V1.0 --gerber gerber.zip --bom bom.csv --cpl cpl.csv [--apply]", out="release/<版本>/", gate="—（终点）",
         rules=[("自动", "封存前提：门禁全确认 + 文件被绑定且未变 + 现场复核通过", "")], pit=[], back="任一前提不满足 → BLOCKED(2)，按提示补确认 / 重新导出"),
]


def node_html(n):
    ed = {"否": "t-green", "读": "t-blue", "写": "t-amber", "读/写": "t-amber", "可选(查库)": "t-blue"}.get(n["eda"], "t-gray")
    acts = "".join(f"<li>{E(a)}</li>" for a in n["act"])
    rules = ""
    for kind, desc, rr in n["rules"]:
        chip = rid(rr) if rr else ""
        kc = {"自动": "t-green", "EDA": "t-blue", "EDA DRC": "t-blue", "人工": "t-amber", "原则": "t-gray", "提示": "t-gray",
              "可选": "t-gray", "可选·手填": "t-amber", "示例类问题": "t-red"}.get(kind, "t-gray")
        rules += f'<li><span class="tag {kc}">{E(kind)}</span> {chip} {E(desc)}</li>'
    pit = "".join(f'<span class=chip>{E(p)}</span> ' for p in n["pit"]) or '<span class=mut>—</span>'
    return f'''<section class="node" id="n-{n["id"]}">
<h3><span class=nid>{E(n["id"])}</span> {E(n["name"])} <span class=grp>{E(n["group"])}</span>
 <span class="tag {ed}" title="是否连接运行中的 EDA">EDA：{E(n["eda"])}</span>{'<span class="tag t-gate">门禁 ' + E(n["gate"]) + '</span>' if n["gate"].startswith("G") else ""}</h3>
<p class=goal>{E(n["goal"])}</p>
<div class=grid>
<div><h4>输入</h4><p>{E(n["inp"])}</p><h4>执行者</h4><p>{E(n["who"])}</p><h4>产出</h4><p>{E(n["out"])}</p><h4>失败回退</h4><p>{E(n["back"])}</p></div>
<div><h4>做什么</h4><ul>{acts}</ul><h4>命令 / 入口</h4><pre>{E(n["cmd"])}</pre></div>
</div>
<h4>对应的设计规则 / 约束</h4><ul class=rl>{rules}</ul>
<h4>相关实测踩坑</h4><p>{pit}</p></section>'''


def test_counts():
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "run_tests.py")], capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
    ids, fails = [], 0
    for ln in r.stdout.splitlines():
        m = re.match(r"(PASS|FAIL)\s+(\S+)", ln)
        if m:
            ids.append(m.group(2))
            fails += m.group(1) == "FAIL"
    grp = Counter()
    for i in ids:
        k = "B" if i.startswith("B-") else re.match(r"[A-Za-z]+", i).group(0)
        grp[k] += 1
    return len(ids), fails, grp


CSS = """
:root{--bg:#fff;--fg:#1f2328;--mut:#656d76;--line:#d8dee4;--card:#f6f8fa;--acc:#07c160;--blue:#0969da;--red:#cf222e;--amber:#9a6700;--code:#eef1f4}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--mut:#8b949e;--line:#30363d;--card:#161b22;--acc:#3fb950;--blue:#58a6ff;--red:#ff7b72;--amber:#d29922;--code:#1f2630}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14.5px/1.7 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:30px 22px 90px}
h1{font-size:27px;margin:.2em 0}h2{font-size:21px;margin:2.2em 0 .6em;padding-bottom:.3em;border-bottom:2px solid var(--acc)}
h3{font-size:17px;margin:0 0 .3em;display:flex;flex-wrap:wrap;gap:8px;align-items:center}h4{font-size:13px;color:var(--mut);margin:.9em 0 .2em;font-weight:600}
p{margin:.4em 0}.sub,.mut{color:var(--mut)}.mut{font-size:12px}small{font-weight:400;color:var(--mut)}
code,pre{background:var(--code);border-radius:6px;font:12.5px Consolas,"Cascadia Mono",monospace}code{padding:1px 5px}
pre{padding:9px 12px;white-space:pre-wrap;word-break:break-all;margin:.3em 0;border:1px solid var(--line)}
table{border-collapse:collapse;width:100%;margin:.7em 0;font-size:13px}th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
th{background:var(--card);white-space:nowrap}td.id{font:12px Consolas,monospace;white-space:nowrap}td.num{font:12.5px Consolas,monospace;white-space:nowrap}
.k{color:var(--mut);font-size:11px}.q{color:var(--mut);font-size:12px;margin-top:2px}.q2{font-size:13px}.cost{color:var(--amber);font-size:12px;margin-top:2px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin:.9em 0}
.tldr{border-left:5px solid var(--acc)}.warn{border-left:5px solid var(--amber)}.bad{border-left:5px solid var(--red)}
.tag{display:inline-block;font-size:11.5px;padding:0 8px;border-radius:10px;color:#fff;line-height:20px;white-space:nowrap}
.t-green{background:var(--acc)}.t-blue{background:var(--blue)}.t-amber{background:var(--amber)}.t-red{background:var(--red)}.t-gray{background:#6e7781}.t-info{background:#8250df}.t-gate{background:#bc4c00}
.chip{display:inline-block;font:11.5px Consolas,monospace;border:1px solid var(--line);background:var(--card);border-radius:6px;padding:0 6px;margin:1px 2px}
nav.toc{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 18px;columns:3}nav.toc a{display:block;color:var(--blue);text-decoration:none;line-height:2}
.flow{display:flex;flex-wrap:wrap;gap:8px;align-items:stretch;margin:.8em 0}
.fn{flex:1 1 118px;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 9px;font-size:12.5px;text-decoration:none;color:var(--fg)}
.fn b{display:block;color:var(--acc);font-size:13px}.fn small{display:block}
.fn.g{border-color:#bc4c00;background:rgba(188,76,0,.08);flex:0 1 96px;text-align:center}.fn.g b{color:#bc4c00}
.fn.e{box-shadow:inset 0 -3px 0 var(--blue)}.fn.w{box-shadow:inset 0 -3px 0 var(--amber)}
.node{border:1px solid var(--line);border-radius:12px;padding:14px 18px;margin:1.1em 0;background:var(--bg)}
.nid{display:inline-block;background:var(--acc);color:#fff;border-radius:6px;padding:0 8px;font-size:14px}.grp{font-size:12px;color:var(--mut);font-weight:400}
.goal{font-size:14px;margin:.3em 0 .6em;padding:6px 10px;background:var(--card);border-radius:6px}
.grid{display:grid;grid-template-columns:1fr 1.6fr;gap:6px 22px}.grid p{margin:.1em 0}.grid ul{margin:.2em 0;padding-left:1.2em}
ul.rl{list-style:none;padding:0;margin:.2em 0}ul.rl li{margin:.35em 0;padding-left:0}
.lane{display:grid;grid-template-columns:90px 1fr;gap:0;border:1px solid var(--line);border-radius:8px;overflow:hidden;margin:.8em 0}
.lane div{padding:7px 10px;border-bottom:1px solid var(--line);font-size:13px}.lane div:nth-child(odd){background:var(--card);font-weight:600}
@media (max-width:820px){.grid{grid-template-columns:1fr}nav.toc{columns:1}}
"""


def build():
    _verify_key_sets()
    tot, fails, grp = test_counts()
    pcb_n, smt_n, bc_n = len(PCB["rules"]), len(SMT["rules"]), len(BC["rules"])
    flow = ""
    for n in NODES:
        cls = "fn " + ("e" if n["eda"] in ("读", "读/写", "可选(查库)") else "w" if n["eda"] == "写" else "")
        flow += f'<a class="{cls}" href="#n-{n["id"]}"><b>{E(n["id"])} {E(n["name"])}</b><small>{E(n["group"])}</small><small>EDA：{E(n["eda"])}</small></a>'
        if n["id"] == "S3":
            flow += '<span class="fn g"><b>G1 + G2</b><small>原理图 / 库封装</small></span>'
        if n["id"] == "P2":
            flow += '<span class="fn g"><b>G3</b><small>布局</small></span>'
        if n["id"] == "P4":
            flow += '<span class="fn g"><b>G4</b><small>PCB</small></span>'
        if n["id"] == "M2":
            flow += '<span class="fn g"><b>G5</b><small>导出放行</small></span>'
    gcount = ", ".join(f"{k}:{v}" for k, v in sorted(grp.items()))
    toc = "".join(f'<a href="#{i}">{t}</a>' for i, t in [("s1", "1 一图看懂"), ("s2", "2 门禁与失效机制"), ("s3", "3 逐节点详解（E1→封存）"),
                                                           ("s4", "4 规则总表（来源 / 极限 / 建议 / 谁来查）"), ("s5", "5 判定语义与退出码"),
                                                           ("s6", "6 谁连 EDA、谁离线"), ("s7", "7 实测踩坑登记簿"), ("s8", "8 边界：明确不做什么"), ("s9", "9 验证现状")])
    return f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>jlceda-pcb-ai-workflow · 运行流程与节点设计规则</title><style>{CSS}</style></head><body><div class="wrap">
<h1>jlceda-pcb-ai-workflow<br><span style="font-size:19px;font-weight:500">详细系统运行流程 · 各节点对应的专业设计规则</span></h1>
<p class=sub>依据实际代码与数据生成（<code>tools/gen_flow_doc.py</code>）｜规范数值抓取于 2026-10-30，国内站口径（jlc.com）｜范围：需求 → 导出 Gerber + BOM + 坐标 → 封存</p>

<div class="card tldr"><b>一句话</b>：Agent 负责设计与判断，<b>脚本只负责“在声明范围内独立复核”</b>，用户用编号答复过 5 道门禁，最后封存成带哈希的发布包。
全程<b>不上传、不下单</b>；缺工艺声明、缺证据一律 <b>BLOCKED</b>，不猜、不默认通过。
本文共收录 <b>{pcb_n}</b> 条 PCB 制板工艺规则、<b>{smt_n}</b> 条 SMT 设计规则（声明贴片才启用）、<b>{bc_n}</b> 条 BOM/坐标规则，每条都带官方原文片段与来源。</div>
<nav class=toc>{toc}</nav>

<h2 id="s1">1　一图看懂</h2>
<p>蓝色底边 = 会读 EDA；橙色底边 = 会写 EDA；无底边 = 纯离线。橙色方块是对话确认门禁。点击节点跳到详解。</p>
<div class=flow>{flow}</div>
<div class="card"><b>数据流</b>：<code>process.json</code>（用户声明） → 决定每条阈值取哪一档 → <code>rules_check</code>（设计规则）／<code>drc_check</code>（EDA 原生 DRC）／<code>export_*</code>（取回文件）→
<code>gerber_guard</code>／<code>bom_cpl_guard</code>（独立复核）→ <code>workflow.py confirm</code>（用户原话 + 绑定文件 sha256）→ <code>release.py</code>（重新复核 + 校验确认未过期 → 封存）。</div>

<h2 id="s2">2　门禁与失效机制（workflow.py，dialogue 模式）</h2>
<table><thead><tr><th>门禁</th><th>确认什么</th><th>汇报最低内容</th></tr></thead><tbody>
<tr><td><b>G1 原理图</b></td><td>原理图可进入 PCB</td><td>ERC 结果、未连接引脚清单、电源/复位/时钟/接口逐项观察</td></tr>
<tr><td><b>G2 库/封装</b></td><td>核心器件引脚 / 封装与 datasheet 一致</td><td>每个核心器件的对照结论、替代料说明</td></tr>
<tr><td><b>G3 布局</b></td><td>分区、关键回路、天线 / 板边 / 孔位</td><td>分区、已知例外</td></tr>
<tr><td><b>G4 PCB</b></td><td>DRC 清零、规则可信</td><td><code>drc_check</code> 结果、规则预设名、逐层读图观察</td></tr>
<tr><td><b>G5 导出放行</b></td><td>Gerber / BOM / 坐标可进入封存</td><td><code>gerber_guard</code> 全量输出（含“不评估”清单）、成本触发项、sha256</td></tr></tbody></table>
<div class=card><b>机制</b>
<ul><li><code>confirm</code> 必须带 <code>--user-reply</code>（<b>用户原话</b>），空的直接 BLOCKED——Agent 不得代答。选 2(修改后重审)/3(暂停) 会被记录，但门禁仍是 PENDING。</li>
<li>选 1(通过) 必须 <code>--bind</code> 被确认的文件，记录其 <b>sha256</b>。</li>
<li><b>按顺序</b>：前序不是 CONFIRMED，后序无法确认。</li>
<li><b>自动失效</b>：被绑定文件一变，该门禁及其后全部变 <code>STALE</code>，必须重新确认。</li>
<li>CONFIRMED 只表示“用户在对话里确认过那个版本”，<b>不是技术通过，也不是电子签名</b>。</li></ul></div>

<h2 id="s3">3　逐节点详解</h2>
{''.join(node_html(n) for n in NODES)}

<h2 id="s4">4　规则总表</h2>
<p>阈值只存在于 <code>data/*.json</code>，脚本里没有裸数字（测试 B07 检查）。“谁来查”列标签含义：
<span class="tag t-info">声明</span> process.json 声明值直接对照；<span class="tag t-blue">规则</span> rules_check 核对 EDA 设计规则里的下限；
<span class="tag t-green">文件</span> gerber_guard 从导出文件反推；<span class="tag t-gray">DRC</span> 设计实际值由 EDA 自身 DRC 负责；
<span class="tag t-amber">手填</span> 无自动抽取，需手动提供实测值。</p>

<h3 style="margin-top:1.2em">4.1　PCB 制板工艺（{pcb_n} 条｜<code>data/jlc-pcb-capabilities.json</code>）</h3>
<p class=mut>三档：低于 limit → <b>BLOCK</b>；介于 limit 与 recommended → <b>WARN</b>；达到 recommended → PASS。官方同一行常并列 mm 与 mil（如 0.10mm / 4mil=0.1016mm，四舍五入不一致），limit 取较小者，避免把常用的 0.10mm 误判阻断。</p>
{rule_table(PCB)}

<h3 style="margin-top:1.2em">4.2　SMT 可制造性设计规则（{smt_n} 条｜仅声明 <code>smt: economy|standard</code> 时启用）</h3>
<div class="card warn">现状：这些规则<b>已入库并可判定</b>（<code>spec_check --measurements</code> / <code>gerber_guard --extra-measurements</code> 手动喂实测值），但<b>没有自动抽取脚本</b>（几何类按决定交给 EDA DRC / 人工）。默认流程 <code>smt: null</code>，这一整组不参与。</div>
{smt_table()}
<p class=mut>已登记的官方口径冲突：{"；".join(E(c["id"] + " " + c["topic"] + "：" + c["resolution"]) for c in SMT["conflicts"])}</p>

<h3 style="margin-top:1.2em">4.3　BOM / 坐标文件规范（{bc_n} 条｜<code>data/jlc-bom-cpl-spec.json</code>｜bom_cpl_guard）</h3>
{bc_table()}

<h3 style="margin-top:1.2em">4.4　Gerber 导出包结构与格式检查（gerber_guard）</h3>
<p class=mut>文件清单来自官方文档 + 实测导出包（<code>data/jlc-gerber-layout.json</code>）；内层文件命名 <code>Gerber_InnerLayer&lt;n&gt;.G&lt;n&gt;</code>（信号层）/ <code>.GP&lt;n&gt;</code>（内电层）。</p>
{gb_table()}
<div class="card warn"><b>gerber_guard 明确不评估</b>（需 EDA API 或几何运算，报告每次逐项列出，不得视为通过）：线距、焊盘到线距离、阻焊桥、丝印字高、丝印到焊盘间隙、铜到板边距离、过孔外径 / 孔环 / 孔边距。这些按决定交给 <b>EDA 自身 DRC</b>。</div>

<h2 id="s5">5　判定语义与退出码</h2>
<table><thead><tr><th>状态</th><th>含义</th><th>对退出码的影响</th></tr></thead><tbody>
<tr><td><span class="tag t-red">BLOCK</span></td><td>低于官方极限 / 硬规则违反</td><td>→ 1（禁止进入下一步）</td></tr>
<tr><td><span class="tag t-amber">WARN</span></td><td>介于极限与建议之间；须写理由</td><td>不影响</td></tr>
<tr><td><span class="tag t-green">PASS</span></td><td>达到建议值</td><td>—</td></tr>
<tr><td><span class="tag t-gray">COST_TRIGGER</span></td><td>命中官方“非常规 / 费用高”（如 0.15mm 孔）</td><td>附加标记</td></tr>
<tr><td><span class="tag t-amber">NEEDS_EVIDENCE</span></td><td>适用但缺实测值</td><td>局部模式不阻断但报告声明“未覆盖项不代表通过”；<code>--strict</code> → 2</td></tr>
<tr><td><span class="tag t-gray">N/A</span></td><td>板上无此类对象（实测值 NONE_PRESENT）</td><td>—</td></tr></tbody></table>
<p><b>退出码</b>：<code>0</code> 声明范围内无阻断（<b>不代表电路正确，也不代表可生产</b>）；<code>1</code> 存在阻断；<code>2</code> BLOCKED（缺工艺声明 / 缺证据 / 无法解析 / 通信失败 / 拒绝覆盖 / 门禁未确认）。</p>

<h2 id="s6">6　谁连 EDA、谁离线</h2>
<table><thead><tr><th>脚本</th><th>连 EDA？</th><th>作用</th></tr></thead><tbody>
<tr><td><code>drc_check</code></td><td><span class="tag t-blue">读</span></td><td>原生 DRC（只读）</td></tr>
<tr><td><code>export_gerber</code></td><td><span class="tag t-blue">读</span></td><td>导出 Gerber，完整取回</td></tr>
<tr><td><code>export_bom_cpl</code></td><td><span class="tag t-blue">读</span></td><td>导出 BOM/坐标并规范化</td></tr>
<tr><td><code>bridge_client</code></td><td><span class="tag t-amber">通道</span></td><td>送 JS / save；发送前拦截下单接口与已知卡死接口</td></tr>
<tr><td><code>gerber_guard · bom_cpl_guard · rules_check · spec_check · workflow · release · spec_drift</code></td><td><span class="tag t-green">离线</span></td><td>其余全部离线；<code>spec_drift</code> 仅联网读官方页面</td></tr></tbody></table>

<h2 id="s7">7　实测踩坑登记簿（{len(PIT["pitfalls"])} 条）</h2>
<p class=mut>全部来自本项目的真实操作，不是网上抄的；每条带证据出处。</p>
{pit_table()}

<h2 id="s8">8　边界：明确不做什么</h2>
<table><thead><tr><th>事项</th><th>为什么 / 怎么办</th></tr></thead><tbody>
<tr><td>下单、上传到任何第三方</td><td>红线。<code>bridge_client</code> 发送前拦截 <code>placePcbOrder / placeSmtComponentsOrder / placeComponentsOrder</code>；<code>release</code> 只在本地封存</td></tr>
<tr><td>线距 / 焊盘距 / 阻焊桥 / 孔环 / 板边的<b>设计实际值</b>检查</td><td>按决定交给 EDA 自身 DRC；本 skill 保证“DRC 的尺子不低于嘉立创工艺”</td></tr>
<tr><td>验证 C 编号与器件是否对应</td><td>不联网无法验证；官方：填了编号以编号为准，<b>错误编号比缺少更危险</b>，以嘉立创下单页匹配结果为准</td></tr>
<tr><td>极性 / 旋转是否正确</td><td>EDA 封装 0° 与嘉立创封装 0° 可能不一致，需人工看 2D 图</td></tr>
<tr><td>电路功能、SI / EMC / 热 / 阻抗求解</td><td>无通用求解器；只作人工清单</td></tr>
<tr><td>xls / xlsx</td><td>不解析 → BLOCKED，要求另存 CSV（官方只读首个工作表前 12 列）</td></tr>
<tr><td>CAM / DFM 外部复核、样机、ECO</td><td>已取消（流程终点是封存）</td></tr>
<tr><td>能力探测 / 环境检查</td><td>已取消：用户自行配好，通道不通则 BLOCKED 并停止</td></tr></tbody></table>

<h2 id="s9">9　验证现状（实测，非宣称）</h2>
<div class="card tldr">离线测试 <b>{tot}</b> 项，<b>失败 {fails}</b>；分组：{E(gcount)}（G=Gerber 缺陷注入、K=BOM/坐标缺陷注入、S=规范判定、R=规则门禁、W=流程门禁、RL=封存、D=漂移、B=通道红线与 lint）。
随仓库提供的夹具均由 <code>tools/make_fixtures.py</code> 构造，为<b>合成测试数据</b>。历史真实 EDA 导出检查与当前离线回归是两种不同证据，真实工程文件未随仓库发布。</div>
<div class="card warn"><b>尚未验证</b>
<ul><li><b>触发率</b>：<code>tests/trigger_cases.md</code> 的 22 条（12 正例 / 6 反例 / 4 混淆例）<b>尚未在新会话里实测</b>；<code>easyeda-api</code> 的泛词可能抢触发。</li>
<li><b>在线端到端</b>：<code>export_bom_cpl</code> 一键导出、<code>rules_check</code> 取当前规则这两步，核心逻辑已用真实文件验证，但“连着 EDA 跑一遍”因 EDA 断连<b>未复测</b>。</li>
<li><b>规范漂移</b>：联网试跑 58 处数字仍在官方页面；<code>jlc-pcb.com</code> 返回 403、<code>jlc-smt.com/vtechnology</code> 一条 BGA 球距读不到（JS 渲染），<b>这两处须手动抽查</b>。</li>
<li><b>数值时效</b>：全部规范数值抓取于 2026-10-30，出厂前跑 <code>spec_drift</code> 并抽查原文片段。</li></ul></div>
</div></body></html>'''


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.write_text(build(), encoding="utf-8")
    print(f"OK {out} ({out.stat().st_size} 字节)")

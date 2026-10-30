#!/usr/bin/env python3
"""规则门禁：核对 EDA 里的**设计规则配置本身**是否低于嘉立创工艺。

为什么需要：EDA 的 DRC 只按当前规则查；规则被设松了，DRC 照样放行，板子却可能做不出来。
所以线距/焊盘距/孔环/板边这些几何检查交给 EDA 自己的 DRC，本脚本只保证"给 DRC 的尺子"不低于嘉立创工艺。

输入：规则配置 JSON（`pcb_Drc.getCurrentRuleConfiguration()` 的返回，或 getAllRuleConfigurations 里某项）。
      也可用 --preset 直接读 data/rule-presets/_all_raw.json 里的嘉立创官方预设做对照。
做法：从配置里取出"规则允许的最小值"，当作实测值交给 spec_check 的三档判定。
      注意这是规则值，不是设计实测值——报告里会明确标注。

退出码：0 规则不低于工艺极限；1 存在低于极限的规则；2 BLOCKED（缺工艺声明/读不到配置）。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_check as sc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PRESETS = ROOT / "data" / "rule-presets" / "_all_raw.json"

DUMP_JS = "return await eda.pcb_Drc.getCurrentRuleConfiguration();"


def _oz_key(oz):
    return f"copperThickness{sc._fmt_oz(oz)}oz"


def _cell(table, rows, a, b):
    """下三角矩阵取值；越界返回 None。"""
    i, j = rows.index(a), rows.index(b)
    if i < j:
        i, j = j, i
    try:
        return table[i][j]
    except (IndexError, TypeError):
        return None


def extract_measurements(cfg, oz):
    """返回 ({key: 规则值}, [说明])。取不到的键不放进去（→ NEEDS_EVIDENCE，不猜）。"""
    m, notes = {}, []
    ozk = _oz_key(oz)
    try:
        track = cfg["Physics"]["Track"].get(ozk)
        if track:
            m["min_track_width"] = track["form"]["strokeWidthMin"]
        else:
            notes.append(f"线宽规则里没有 {ozk}，未核对线宽")
    except (KeyError, TypeError):
        notes.append("读不到 Physics.Track")
    try:
        t = cfg["Spacing"]["Safe Spacing"].get(ozk)
        if t:
            rows, tab = t["row"], t["table"]
            m["min_track_space"] = _cell(tab, rows, "Track", "Track")
            pt = [_cell(tab, rows, "SMD Pad", "Track"), _cell(tab, rows, "TH Pad", "Track")]
            m["min_pad_to_track"] = min(v for v in pt if v is not None)
            m["min_mask_bridge"] = _cell(tab, rows, "SMD Pad", "SMD Pad")
            edge = [_cell(tab, rows, "Board Outline", k) for k in ("Track", "SMD Pad", "TH Pad", "Via")]
            m["min_copper_to_edge"] = min(v for v in edge if v is not None)
        else:
            notes.append(f"安全间距里没有 {ozk}，未核对间距类规则")
    except (KeyError, TypeError, ValueError):
        notes.append("读不到 Spacing.Safe Spacing")
    try:
        v = cfg["Physics"]["Via Size"]["viaSize"]["form"]
        m["min_plated_drill"] = v["viaInnerdiameterMin"]
        m["min_via_outer"] = v["viaOuterdiameterMin"]
    except (KeyError, TypeError):
        notes.append("读不到 Physics.Via Size")
    try:
        m["min_via_hole_edge_gap"] = cfg["Spacing"]["Other Spacing"]["otherClearance"]["form"]["hole2Hole"]
    except (KeyError, TypeError):
        notes.append("读不到 Other Spacing.hole2Hole")
    try:
        f = cfg["Expansion"]["Solder Mask Expansion"]["solderMaskExpansion"]["form"]
        m["min_mask_expansion"] = min(f["padToplayerExpansion"], f["padBottomlayerExpansion"])
    except (KeyError, TypeError):
        notes.append("读不到 Expansion.Solder Mask Expansion")
    return {k: v for k, v in m.items() if v is not None}, notes


def load_config(path=None, preset=None):
    if preset:
        allp = json.loads(PRESETS.read_text(encoding="utf-8"))
        if preset not in allp:
            raise KeyError(f"预设 {preset!r} 不存在。可选：{list(allp)}")
        return allp[preset], f"官方预设：{preset}"
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(d, dict) and "config" in d and "Spacing" not in d:
        d = d["config"]
    if not isinstance(d, dict) or "Spacing" not in d:
        raise KeyError("不是规则配置 JSON（缺少 Spacing 段）")
    return d, f"文件：{path}"


def run(cfg, process):
    meas, notes = extract_measurements(cfg, process["copper_oz"])
    rule_sets = [(sc.load_json(sc.DATA / "jlc-pcb-capabilities.json"), "pcb")]
    results, summary, code = sc.evaluate(process, meas, rule_sets, partial=True)
    # 只保留"规则值"能说明问题的规则；其余(如丝印高度)与设计规则无关，不在此处报告
    keep = set(meas)
    results = [r for r in results if r["key"] in keep]
    cnt = {}
    for r in results:
        cnt[r["status"]] = cnt.get(r["status"], 0) + 1
    code = 1 if cnt.get("BLOCK") else 0
    evaluated = sum(v for k, v in cnt.items() if k not in ("NEEDS_EVIDENCE", "N/A"))
    summary = {**summary, "total_applicable": len(results), "evaluated": evaluated, "counts": cnt,
               "cost_triggers": sum(1 for r in results if r["flags"])}
    return results, summary, meas, notes, code


def main(argv=None):
    sc._utf8()
    ap = argparse.ArgumentParser(description="设计规则配置 vs 嘉立创工艺 的规则门禁")
    ap.add_argument("--config", help="规则配置 JSON")
    ap.add_argument("--preset", help="用 data/rule-presets 里的官方预设，如 'JLCPCB Capability(Two Layers Board)'")
    ap.add_argument("--process", help="工艺声明 JSON（layers/copper_oz 必填；--dump-js 时可省）")
    ap.add_argument("--dump-js", action="store_true", help="只打印用于导出当前规则配置的 JS（交给 bridge_client exec）")
    a = ap.parse_args(argv)
    if a.dump_js:
        print(DUMP_JS)
        return 0
    if not (a.config or a.preset):
        ap.error("需要 --config 或 --preset")
    if not a.process:
        ap.error("需要 --process（不猜工艺）")
    try:
        process = sc.load_json(a.process)
        cfg, label = load_config(a.config, a.preset)
        for need in ("layers", "copper_oz"):
            if process.get(need) is None:
                raise ValueError(f"process 缺少必填字段 {need}（不猜工艺，请用户声明）")
        results, summary, meas, notes, code = run(cfg, process)
    except (ValueError, KeyError, OSError) as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        return 2
    print(f"规则门禁｜{label}")
    print("注意：下列“实测”是 DRC 规则里允许的最小值，不是设计实际值；DRC 通过只代表满足这些规则。")
    print(sc.render(results, summary, process, code))
    for n in notes:
        print("  注：", n)
    print("规则里没有覆盖（需人工确认或交给 DRC/Gerber 复核）：丝印字高、丝印到焊盘、孔环、插件孔间距、阻焊桥实测")
    return code


if __name__ == "__main__":
    sys.exit(main())

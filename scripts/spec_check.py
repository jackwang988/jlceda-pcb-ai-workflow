#!/usr/bin/env python3
"""规范三档判定：把设计实测值对照 data/ 里的嘉立创工艺规范库。

本脚本不含任何工艺阈值；所有数值来自 data/jlc-pcb-capabilities.json（及可选的 SMT 库）。

判定：
  BLOCK          低于 limit（官方极限/最低可行）       → 退出码 1
  WARN           介于 limit 与 recommended 之间        → 不影响退出码，须写理由
  PASS           达到 recommended
  COST_TRIGGER   命中官方标注的"非常规/费用高"区间（附加标记，不改变 PASS/WARN）
  NEEDS_EVIDENCE 规则适用但缺少实测值                   → 严格模式退出码 2（fail-closed）
  N/A            规则对当前工艺不适用

退出码：0 在已评估范围内无 BLOCK；1 存在 BLOCK；2 严格模式下存在 NEEDS_EVIDENCE（BLOCKED）。
退出 0 只代表"声明范围内通过"，不代表电路正确，也不代表可以生产。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OPS = {">=", "<=", "==", "in", "not_in"}
TIERS = {"T0", "T1", "T2"}  # T3(第三方)禁止入库
NONE_PRESENT = "NONE_PRESENT"  # 实测值：板上不存在这类对象（如没有插件孔），规则不适用


def _utf8():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


# ───────────────────────── 规范库自检 ─────────────────────────
def validate_data(data, label="data"):
    """没有来源/原文片段的条目禁止入库。返回问题列表。"""
    problems = []
    if not isinstance(data.get("tolerance_epsilon"), (int, float)):
        problems.append(f"{label}: 缺少数值型 tolerance_epsilon（比较容差必须在规范库中声明，脚本不设默认值）")
    srcs = data.get("sources", {})
    for sid, s in srcs.items():
        for f in ("tier", "url", "fetched_at"):
            if not s.get(f):
                problems.append(f"{label}: 来源 {sid} 缺少 {f}")
        if s.get("tier") not in TIERS:
            problems.append(f"{label}: 来源 {sid} tier={s.get('tier')} 不允许(只接受 T0/T1/T2，T3 第三方禁止)")
    seen = set()
    for r in data.get("rules", []):
        rid = r.get("id", "<无id>")
        if rid in seen:
            problems.append(f"{label}: 规则 id 重复 {rid}")
        seen.add(rid)
        for f in ("id", "name", "key", "op"):
            if not r.get(f):
                problems.append(f"{label}: {rid} 缺少 {f}")
        if r.get("op") not in OPS:
            problems.append(f"{label}: {rid} 非法 op={r.get('op')}")
        if not any(k in r for k in ("limit", "recommended")):
            problems.append(f"{label}: {rid} 既无 limit 也无 recommended")
        for kind in ("limit", "recommended", "cost_trigger"):
            t = r.get(kind)
            if t is None:
                continue
            if t.get("src") not in srcs:
                problems.append(f"{label}: {rid}.{kind} src={t.get('src')} 未在 sources 中登记")
            if not str(t.get("quote", "")).strip():
                problems.append(f"{label}: {rid}.{kind} 缺少 quote 原文片段")
            if kind != "cost_trigger":
                has = ("value" in t) or ("by" in t) or ("set" in t)
                if not has:
                    problems.append(f"{label}: {rid}.{kind} 缺少 value/by/set")
    return problems


# ───────────────────────── 工艺解析 ─────────────────────────
def layer_class(layers):
    return "single" if layers == 1 else ("double" if layers == 2 else "multi")


def _fmt_oz(oz):
    return format(float(oz), "g")


def resolve(spec, process):
    """从 {value|by|set} 解析出当前工艺下的取值；无匹配返回 None。"""
    if spec is None:
        return None
    if "value" in spec:
        return spec["value"]
    if "set" in spec:
        return spec["set"]
    by = spec.get("by", {})
    lc = layer_class(process["layers"])
    oz = _fmt_oz(process["copper_oz"])
    for k in (f"{lc}_{oz}oz", f"default_{oz}oz", lc, "default"):
        if k in by:
            return by[k]
    return None


def applicable(rule, process):
    a = rule.get("applies")
    if not a:
        return True
    lc = layer_class(process["layers"])
    if "layer_class" in a and lc not in a["layer_class"]:
        return False
    if "copper_oz" in a and float(process["copper_oz"]) not in [float(x) for x in a["copper_oz"]]:
        return False
    if "layers_ge" in a and process["layers"] < a["layers_ge"]:
        return False
    if "layers_lt" in a and process["layers"] >= a["layers_lt"]:
        return False
    if "thickness_le" in a:
        t = process.get("thickness_mm")
        if t is None or t > a["thickness_le"]:
            return False
    for k, vals in a.get("when", {}).items():
        # 未声明 edge 时默认 routed(锣边)
        pv = process.get(k, "routed" if k == "edge" else None)
        if pv not in vals:
            return False
    return True


# ───────────────────────── 判定 ─────────────────────────
def _num_in(v, seq, eps):
    for s in seq:
        if isinstance(s, (int, float)) and isinstance(v, (int, float)):
            if abs(v - s) <= eps:
                return True
        elif v == s:
            return True
    return False


def _src_label(sources, spec):
    if not spec:
        return None
    s = sources.get(spec["src"], {})
    return f"{s.get('tier', '?')} {s.get('title', spec['src'])} <{s.get('url', '')}> @{s.get('fetched_at', '')}"


def evaluate_rule(rule, process, measurements, eps, sources):
    key = rule["key"]
    src = process if rule.get("from") == "process" else measurements
    lim_spec, rec_spec = rule.get("limit"), rule.get("recommended")
    lim, rec = resolve(lim_spec, process), resolve(rec_spec, process)
    res = {
        "rule_id": rule["id"], "name": rule["name"], "key": key, "op": rule["op"],
        "limit": lim, "recommended": rec, "measured": None, "status": None, "flags": [],
        "source": {
            "limit": _src_label(sources, lim_spec),
            "recommended": _src_label(sources, rec_spec),
        },
        "note": rule.get("note"),
    }
    if lim is None and rec is None:
        res["status"] = "N/A"
        res["na_reason"] = "no_rule_values"
        return res
    if src.get(key) == NONE_PRESENT:
        res["status"] = "N/A"
        res["na_reason"] = "no_objects"
        return res
    if key not in src or src[key] is None:
        res["status"] = "NEEDS_EVIDENCE"
        return res
    m = src[key]
    res["measured"] = m
    op = rule["op"]

    def below(x, ref):  # 违反 ">=" 方向
        return x < ref - eps

    status = "PASS"
    if op == ">=":
        if lim is not None and below(m, lim):
            status = "BLOCK"
        elif rec is not None and below(m, rec):
            status = "WARN"
    elif op == "<=":
        if lim is not None and m > lim + eps:
            status = "BLOCK"
        elif rec is not None and m > rec + eps:
            status = "WARN"
    elif op == "==":
        if lim is not None and abs(m - lim) > eps:
            status = "BLOCK"
    elif op == "in":
        if lim is not None and not _num_in(m, lim, eps):
            status = "BLOCK"
    elif op == "not_in":
        if lim is not None and _num_in(m, lim, eps):
            status = "BLOCK"
    # 只有 recommended 的规则，违反时降级为 WARN（没有官方硬线可判 BLOCK）
    res["status"] = status
    ct = rule.get("cost_trigger")
    if ct and isinstance(m, (int, float)) and m < ct["below"] - eps:
        res["flags"].append(f"COST_TRIGGER(<{ct['below']}mm: {ct['quote']})")
    return res


def evaluate(process, measurements, rule_sets, partial=False):
    """rule_sets: [(data_dict, label), ...]；返回 (results, summary, exit_code)。"""
    # 不猜工艺：层数与铜厚必须由用户声明，缺失或为 null(模板默认) 均拒绝，不设默认值
    for need in ("layers", "copper_oz"):
        if process.get(need) is None:
            raise ValueError(f"process 缺少必填字段 {need}（不猜工艺，请用户声明）")
    results = []
    for data, label in rule_sets:
        eps = data["tolerance_epsilon"]  # 必填，由 validate_data 保证存在；脚本内不设默认值
        for rule in data["rules"]:
            if not applicable(rule, process):
                continue
            r = evaluate_rule(rule, process, measurements, eps, data["sources"])
            r["set"] = label
            results.append(r)
    results = [r for r in results if not (r["status"] == "N/A" and r.get("na_reason") == "no_rule_values")]
    cnt = {}
    for r in results:
        cnt[r["status"]] = cnt.get(r["status"], 0) + 1
    evaluated = sum(v for k, v in cnt.items() if k not in ("NEEDS_EVIDENCE", "N/A"))
    summary = {"total_applicable": len(results), "evaluated": evaluated, "counts": cnt,
               "cost_triggers": sum(1 for r in results if r["flags"]), "partial": partial}
    if cnt.get("BLOCK"):
        code = 1
    elif cnt.get("NEEDS_EVIDENCE") and not partial:
        code = 2
    else:
        code = 0
    return results, summary, code


def _mil(v):
    return f"{v / 0.0254:.2f}mil" if isinstance(v, (int, float)) else ""


def render(results, summary, process, code):
    L = []
    lc = layer_class(process["layers"])
    L.append(f"依据：嘉立创国内站规范库｜{process['layers']}层({lc})｜铜厚 {process['copper_oz']}oz｜"
             f"板厚 {process.get('thickness_mm', '未声明')}mm｜表面 {process.get('surface', '未声明')}")
    order = {"BLOCK": 0, "NEEDS_EVIDENCE": 1, "WARN": 2, "PASS": 3, "N/A": 4}
    for r in sorted(results, key=lambda x: (order.get(x["status"], 9), x["rule_id"])):
        tag = {"BLOCK": "【阻断级】", "WARN": "【中风险】", "PASS": "  PASS  ", "NEEDS_EVIDENCE": "【待证据】", "N/A": "  N/A   "}[r["status"]]
        m, lim, rec = r["measured"], r["limit"], r["recommended"]
        if r["status"] == "N/A":
            line = f"{tag} {r['rule_id']} {r['name']}：板上无此类对象，不适用"
        elif r["status"] == "NEEDS_EVIDENCE":
            line = f"{tag} {r['rule_id']} {r['name']}：缺少实测值 `{r['key']}`"
        else:
            def f(x):
                return (f"{x}({_mil(x)})" if isinstance(x, (int, float)) and r["key"] not in
                        ("copper_oz", "thickness_mm", "mark_count", "via_in_smd_pad_count") else str(x))
            line = (f"{tag} {r['rule_id']} {r['name']}：实测 {f(m)}｜极限 {f(lim) if lim is not None else '—'}"
                    f"｜建议 {f(rec) if rec is not None else '—'}")
        L.append(line)
        for fl in r["flags"]:
            L.append(f"           ⚑ {fl}")
        if r["status"] in ("BLOCK", "WARN"):
            which = "limit" if r["status"] == "BLOCK" else "recommended"
            basis = r["source"].get(which) or r["source"].get("limit")
            if basis:
                L.append(f"           依据：{basis}")
    s = summary
    L.append(f"— 汇总：适用 {s['total_applicable']} 条，已评估 {s['evaluated']} 条｜{s['counts']}｜成本触发 {s['cost_triggers']} 项"
             + ("｜【局部模式：未覆盖项不代表通过】" if s["partial"] else ""))
    L.append({0: "结论：声明范围内无阻断（不代表电路正确/可生产）", 1: "结论：存在阻断项，禁止进入下一门禁",
              2: "结论：BLOCKED——适用规则缺少实测证据，不得视为通过"}[code])
    return "\n".join(L)


def main(argv=None):
    _utf8()
    ap = argparse.ArgumentParser(description="嘉立创工艺规范三档判定")
    ap.add_argument("--process", help="工艺声明 JSON（layers/copper_oz/thickness_mm/surface/edge/mask_color/smt）")
    ap.add_argument("--measurements", help="实测值 JSON（键见 data/*.json 各规则的 key，单位mm）")
    ap.add_argument("--partial", action="store_true", help="局部模式：缺证据项不阻断，但报告会声明未覆盖")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--validate-data", action="store_true", help="只校验规范库完整性")
    a = ap.parse_args(argv)

    pcb = load_json(DATA / "jlc-pcb-capabilities.json")
    smt = load_json(DATA / "jlc-smt-capabilities.json")
    if a.validate_data:
        probs = validate_data(pcb, "pcb") + validate_data(smt, "smt")
        for p in probs:
            print("规范库问题:", p)
        print(f"规范库自检：{len(pcb['rules'])}+{len(smt['rules'])} 条规则，{len(probs)} 个问题")
        return 2 if probs else 0
    if not a.process or not a.measurements:
        ap.error("需要 --process 与 --measurements（或使用 --validate-data）")
    process, meas = load_json(a.process), load_json(a.measurements)
    sets = [(pcb, "pcb")]
    if process.get("smt") in ("economy", "standard"):
        sets.append((smt, "smt"))
    try:
        results, summary, code = evaluate(process, meas, sets, partial=a.partial)
    except ValueError as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps({"summary": summary, "results": results, "exit": code}, ensure_ascii=False, indent=2))
    else:
        print(render(results, summary, process, code))
    return code


if __name__ == "__main__":
    sys.exit(main())

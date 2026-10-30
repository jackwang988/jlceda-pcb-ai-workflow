#!/usr/bin/env python3
"""原生 DRC 包装：经 Bridge 调 pcb_Drc.check(strict=true, ui=false, verbose=true)，整理成可读报告。

这是"EDA 原生核对"。它的范围 = 当前规则管理器里已启用的规则；规则被放宽则 DRC 也会跟着放宽，
所以通过 DRC ≠ 满足嘉立创工艺（工艺复核见 gerber_guard / spec_check）。

返回结构（P0 探针实测，见 data/known-pitfalls.json DR-01/DR-02）：
  [{name:'Connection Error', count, list:[{name:<网络>, list:[{errorType, errorObjType, ruleName, net,
    obj1:{typeName,suffix}, explanation:{errData:{position:{x,y}, layerIds,...}}}]}]}]

退出码：0 无错误；1 有 DRC 错误；2 BLOCKED(通信失败/当前不是PCB)。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bridge_client as bc  # noqa: E402

DOC_TYPE_PCB = 3

JS = r"""
const d = await eda.dmt_SelectControl.getCurrentDocumentInfo();
if (!d || d.documentType !== __PCB__) { return { docType: d ? d.documentType : null }; }
const r = await eda.pcb_Drc.check(true, false, true);
const errs = [];
const walk = (n, cat) => {
  if (!n) return;
  if (n.errorType) {
    const e = n.explanation && n.explanation.errData ? n.explanation.errData : {};
    errs.push({
      category: cat, errorType: n.errorType, objType: n.errorObjType || null, rule: n.ruleName || null,
      net: n.net || null, obj: n.obj1 && n.obj1.suffix ? n.obj1.suffix : null,
      obj2: n.obj2 && n.obj2.suffix ? n.obj2.suffix : null,
      x: e.position ? e.position.x : null, y: e.position ? e.position.y : null,
      layers: e.layerIds || null
    });
  }
  if (Array.isArray(n.list)) n.list.forEach(c => walk(c, cat));
};
const cats = [];
for (const c of (r || [])) { cats.push({ name: c.name, count: c.count }); walk(c, c.name); }
let rule = null; try { rule = await eda.pcb_Drc.getCurrentRuleConfigurationName(); } catch (e) {}
return { docType: d.documentType, cats, errs, rule };
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="原生 DRC（经 Bridge）")
    ap.add_argument("--limit", type=int, default=20, help="每个类别最多展示多少条（默认20）")
    ap.add_argument("--json-out", help="完整错误列表写入 JSON")
    a = ap.parse_args(argv)
    try:
        r = bc.execute(JS.replace("__PCB__", str(DOC_TYPE_PCB)))
    except bc.BridgeError as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        return 2
    if r.get("docType") != DOC_TYPE_PCB:
        print(f"BLOCKED: 当前文档类型={r.get('docType')}，不是 PCB，无法执行 PCB DRC。", file=sys.stderr)
        return 2
    errs, cats = r["errs"], r["cats"]
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"原生 DRC（规则配置：{r.get('rule')}）｜错误 {len(errs)} 条")
    for c in cats:
        sub = [e for e in errs if e["category"] == c["name"]]
        print(f"\n【{c['name']}】{c['count']} 条")
        shown = 0
        for e in sub:
            if shown >= a.limit:
                print(f"   … 其余 {len(sub) - shown} 条见 --json-out")
                break
            pos = f"({e['x']:.1f},{e['y']:.1f})" if isinstance(e.get("x"), (int, float)) else ""
            who = " ↔ ".join(x for x in (e["obj"], e["obj2"]) if x) or (e["objType"] or "")
            print(f"   - 网络 {e['net']}｜{e['errorType']}｜{who} {pos}")
            shown += 1
    if not errs:
        print("\n  PASS  当前规则下无 DRC 错误（不代表满足嘉立创工艺，请继续 gerber_guard）")
        return 0
    print("\n结论：存在 DRC 错误，禁止进入导出放行")
    return 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())

#!/usr/bin/env python3
"""流程调度（dialogue 模式）：状态、任务清单、用户确认记录。纯本地，不连 EDA。

它不是自动设计器，也不代替任何检查：
  - plan：只打印某任务对应的命令，不执行
  - run ：按白名单调用本 skill 的脚本（无 shell），原样传播退出码；连 EDA 的任务由脚本自己负责
  - confirm：记录"用户已确认某个门禁"。**必须带用户的原话**；Agent 不得自行填写
  - status：显示各门禁的确认状态，以及确认之后被绑定文件是否又变了（STALE）

门禁按顺序：G1 原理图 → G2 库/封装 → G3 布局 → G4 PCB → G5 导出放行。
确认不等于技术通过（见 references/stage-approvals.md）。确认只对当时绑定的文件版本有效，文件变了即失效。

退出码：0 成功；1 被调用脚本报告问题；2 BLOCKED（参数/顺序/状态不合法）。
"""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
WF_NAME = "workflow.json"

GATES = [
    ("G1", "原理图"),
    ("G2", "库/封装"),
    ("G3", "布局"),
    ("G4", "PCB"),
    ("G5", "导出放行"),
]

# 任务 → (脚本, 固定前置参数, 需要 EDA, 所属门禁阶段, 说明)。仅白名单，不接受任意命令。
TASKS = {
    "spec.validate": ("spec_check.py", ["--validate-data"], False, "—", "规范库自检(来源/原文片段齐全)"),
    "rules.check": ("rules_check.py", [], False, "G4", "设计规则配置 vs 嘉立创工艺(需 --config 或 --preset)"),
    "pcb.drc": ("drc_check.py", [], True, "G4", "EDA 原生 DRC(只读)"),
    "export.gerber": ("export_gerber.py", [], True, "G5", "导出 Gerber 并完整取回(拒绝覆盖)"),
    "export.bomcpl": ("export_bom_cpl.py", [], True, "G5", "导出 BOM+坐标并规范化"),
    "gerber.guard": ("gerber_guard.py", [], False, "G5", "Gerber 包独立复核"),
    "bomcpl.check": ("bom_cpl_guard.py", ["check"], False, "G5", "BOM/坐标 格式复核"),
    "bomcpl.normalize": ("bom_cpl_guard.py", ["normalize"], False, "G5", "EDA 原生 BOM/坐标 → UTF-8 逗号 CSV"),
    "drift.check": ("spec_drift.py", [], False, "G5", "规范库数值 vs 官方页面 漂移检测(联网)"),
    "tests": ("../tests/run_tests.py", [], False, "—", "本 skill 的缺陷注入测试"),
}


def _utf8():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def wf_path(project):
    return Path(project) / WF_NAME


def load_wf(project):
    p = wf_path(project)
    if not p.exists():
        raise FileNotFoundError(f"{p} 不存在，请先 init --apply")
    return json.loads(p.read_text(encoding="utf-8"))


def save_wf(project, wf):
    wf_path(project).write_text(json.dumps(wf, ensure_ascii=False, indent=2), encoding="utf-8")


# ───────────────────────── init ─────────────────────────
def template():
    return {
        "schema_version": 1,
        "mode": "dialogue",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project": None,
        "files": {"process": "process.json", "gerber": None, "bom": None, "cpl": None},
        "confirmations": [],
        "note": "dialogue 模式：confirm 只记录用户原话与绑定文件哈希，不是技术通过，也不是电子签名。",
    }


def cmd_init(a):
    d = Path(a.project)
    if not d.is_dir():
        print(f"BLOCKED: 目录不存在 {d}", file=sys.stderr)
        return 2
    wf, pf = wf_path(d), d / "process.json"
    if wf.exists():
        print(f"BLOCKED: {wf} 已存在，拒绝覆盖", file=sys.stderr)
        return 2
    print(f"将创建：{wf}\n将创建：{pf}（工艺声明模板，layers/copper_oz 等为 null，必须由用户填写）")
    if not a.apply:
        print("（预览；加 --apply 才写入）")
        return 0
    tpl = json.loads((ROOT / "assets" / "process.template.json").read_text(encoding="utf-8"))
    if pf.exists():
        print(f"注：{pf} 已存在，保留不动")
    else:
        pf.write_text(json.dumps(tpl, ensure_ascii=False, indent=2), encoding="utf-8")
    w = template()
    w["project"] = a.name or d.name
    save_wf(d, w)
    print("OK：已创建。请先填写 process.json 的工艺声明。")
    return 0


# ───────────────────────── status ─────────────────────────
def bound_state(c, project):
    """确认时绑定的文件，现在哈希是否还一致。返回 ('OK'|'STALE'|'MISSING', [变化的文件])。"""
    changed, missing = [], []
    for rel, h in c.get("bound", {}).items():
        p = Path(project) / rel
        if not p.exists():
            missing.append(rel)
        elif sha256_file(p) != h:
            changed.append(rel)
    if missing:
        return "MISSING", missing
    return ("STALE", changed) if changed else ("OK", [])


def gate_status(wf, project):
    """每个门禁取最近一次确认；其前序门禁失效则本门禁也失效。"""
    out, prev_ok = [], True
    for gid, name in GATES:
        cs = [c for c in wf["confirmations"] if c["gate"] == gid and c["choice"] == "1"]
        if not cs:
            out.append((gid, name, "PENDING", "尚未确认", None))
            prev_ok = False
            continue
        c = cs[-1]
        st, why = bound_state(c, project)
        if st != "OK":
            out.append((gid, name, "STALE", f"绑定文件已变化/缺失：{why}，需重新确认", c))
            prev_ok = False
        elif not prev_ok:
            out.append((gid, name, "STALE", "前序门禁已失效，本门禁需重新确认", c))
        else:
            out.append((gid, name, "CONFIRMED", f"{c['at']}｜用户原话：{c['user_reply']!r}", c))
    return out


def cmd_status(a):
    try:
        wf = load_wf(a.project)
    except FileNotFoundError as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        return 2
    print(f"工程：{wf['project']}｜模式：{wf['mode']}")
    pf = Path(a.project) / wf["files"]["process"]
    if pf.exists():
        try:
            pr = json.loads(pf.read_text(encoding="utf-8"))
            miss = [k for k in ("layers", "copper_oz") if pr.get(k) is None]
            print("工艺声明：" + ("完整(必填项已填)" if not miss else f"未完成，缺 {miss}（不猜工艺，相关任务将 BLOCKED）"))
        except json.JSONDecodeError:
            print("工艺声明：process.json 不是合法 JSON")
    else:
        print("工艺声明：process.json 不存在")
    for gid, name, st, msg, _c in gate_status(wf, a.project):
        print(f"  {gid} {name:<6} {st:<10} {msg}")
    print("提示：CONFIRMED 只表示用户在对话中确认过那个版本，不代表技术通过。")
    return 0


# ───────────────────────── confirm ─────────────────────────
def cmd_confirm(a):
    try:
        wf = load_wf(a.project)
    except FileNotFoundError as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        return 2
    ids = [g for g, _ in GATES]
    if a.gate not in ids:
        print(f"BLOCKED: 未知门禁 {a.gate}，可选 {ids}", file=sys.stderr)
        return 2
    if not a.user_reply.strip():
        print("BLOCKED: 必须提供 --user-reply（用户在对话里的原话）。Agent 不得自行代答。", file=sys.stderr)
        return 2
    if a.choice not in ("1", "2", "3"):
        print("BLOCKED: --choice 只能是 1(通过) / 2(修改后重审) / 3(暂停)", file=sys.stderr)
        return 2
    sts = {g: s for g, _n, s, _m, _c in gate_status(wf, a.project)}
    if a.choice == "1":
        i = ids.index(a.gate)
        if i > 0 and sts[ids[i - 1]] != "CONFIRMED":
            print(f"BLOCKED: 前序门禁 {ids[i - 1]} 当前为 {sts[ids[i - 1]]}，不能确认 {a.gate}（按顺序推进）", file=sys.stderr)
            return 2
        if not a.bind:
            print("BLOCKED: 通过(1)必须用 --bind 指定被确认的文件（如 process.json、Gerber zip），以便变化后自动失效", file=sys.stderr)
            return 2
    bound = {}
    for rel in a.bind or []:
        p = Path(a.project) / rel
        if not p.is_file():
            print(f"BLOCKED: 绑定文件不存在 {p}", file=sys.stderr)
            return 2
        bound[Path(rel).as_posix()] = sha256_file(p)
    rec = {"gate": a.gate, "choice": a.choice, "user_reply": a.user_reply, "note": a.note or "",
           "bound": bound, "at": datetime.now().isoformat(timespec="seconds")}
    wf["confirmations"].append(rec)
    save_wf(a.project, wf)
    word = {"1": "通过", "2": "修改后重审", "3": "暂停"}[a.choice]
    print(f"OK：{a.gate} 记录为「{word}」；绑定 {len(bound)} 个文件。")
    return 0


# ───────────────────────── plan / run ─────────────────────────
def build_cmd(task, extra):
    script, pre, needs_eda, _stage, _desc = TASKS[task]
    return [sys.executable, str(SCRIPTS / script), *pre, *extra], needs_eda


def cmd_plan(a):
    if a.task == "list":
        for t, (s, _p, eda, stage, d) in TASKS.items():
            print(f"  {t:<17} {'[连EDA]' if eda else '[离线]':<8} {stage:<3} {d}")
        return 0
    if a.task not in TASKS:
        print(f"BLOCKED: 未知任务 {a.task}（plan list 查看全部）", file=sys.stderr)
        return 2
    cmd, eda = build_cmd(a.task, a.extra)
    print(("[连 EDA] " if eda else "[离线] ") + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    return 0


def cmd_run(a):
    if a.task not in TASKS:
        print(f"BLOCKED: 未知任务 {a.task}（只接受白名单任务）", file=sys.stderr)
        return 2
    cmd, eda = build_cmd(a.task, a.extra)
    if eda:
        print("注意：此任务会连接运行中的 EDA（只读操作）。", file=sys.stderr)
    r = subprocess.run(cmd, cwd=str(ROOT))  # 无 shell
    return r.returncode


def main(argv=None):
    _utf8()
    ap = argparse.ArgumentParser(description="嘉立创EDA 流程调度（dialogue）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init"); i.add_argument("project"); i.add_argument("--name"); i.add_argument("--apply", action="store_true")
    s = sub.add_parser("status"); s.add_argument("project")
    c = sub.add_parser("confirm")
    c.add_argument("project"); c.add_argument("--gate", required=True)
    c.add_argument("--choice", required=True, help="1通过 2修改后重审 3暂停")
    c.add_argument("--user-reply", required=True, help="用户在对话中的原话")
    c.add_argument("--bind", action="append", help="被确认的文件(相对工程目录)，可多次")
    c.add_argument("--note")
    for nm in ("plan", "run"):
        p = sub.add_parser(nm); p.add_argument("--task", required=True)
        p.add_argument("extra", nargs=argparse.REMAINDER, help="-- 之后的参数原样传给脚本")
    a = ap.parse_args(argv)
    if getattr(a, "extra", None) and a.extra and a.extra[0] == "--":
        a.extra = a.extra[1:]
    return {"init": cmd_init, "status": cmd_status, "confirm": cmd_confirm, "plan": cmd_plan, "run": cmd_run}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())

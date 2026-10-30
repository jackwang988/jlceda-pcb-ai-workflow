#!/usr/bin/env python3
"""封存（流程终点）：把通过全部门禁的 Gerber / BOM / 坐标连同证据冻结成一份带哈希清单的发布包。

只在本地复制文件并写清单：**不上传、不下单、不连 EDA**。
前置条件（任一不满足即 BLOCKED，不封存）：
  1. process.json 的 layers / copper_oz 已声明（不猜工艺）
  2. G1–G5 全部 CONFIRMED（含"绑定文件未变化"）
  3. 被封存的每个文件都在工程目录内，且已被 G5 确认绑定（哈希一致）——保证"封存的就是用户确认过的那一版"
  4. 现在重新复核：gerber_guard 无阻断；给了 BOM/坐标则 bom_cpl_guard 无阻断
默认只预览；--apply 才写入 <工程>/release/<版本>/（目录已存在则拒绝覆盖）。

退出码：0 成功/预览；1 复核有阻断；2 BLOCKED（前置条件不满足/参数不合法）。
"""
import argparse
import contextlib
import hashlib
import io
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bom_cpl_guard as bg  # noqa: E402
import gerber_guard as gg  # noqa: E402
import workflow as wf  # noqa: E402

VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _capture(fn, args):
    buf, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        code = fn(args)
    return code, buf.getvalue() + err.getvalue()


def _rel_in_project(project, p):
    """返回相对工程目录的 posix 路径；不在工程目录内返回 None。"""
    try:
        return Path(p).resolve().relative_to(Path(project).resolve()).as_posix()
    except ValueError:
        return None


def main(argv=None):
    wf._utf8()
    ap = argparse.ArgumentParser(description="封存发布包（不上传、不下单）")
    ap.add_argument("project")
    ap.add_argument("--version", required=True, help="版本号，如 V1.0")
    ap.add_argument("--gerber", required=True, help="Gerber zip（须在工程目录内）")
    ap.add_argument("--bom", help="规范化后的 BOM csv（须在工程目录内）")
    ap.add_argument("--cpl", help="规范化后的 坐标 csv（须在工程目录内）")
    ap.add_argument("--extra", action="append", default=[], help="其他要一并封存的文件(如需求文档/原理图PDF)，须在工程目录内，可多次")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)

    def block(msg):
        print(f"BLOCKED: {msg}", file=sys.stderr)
        return 2

    proj = Path(a.project)
    if not VERSION_RE.match(a.version):
        return block("版本号只允许字母数字及 . _ -")
    try:
        w = wf.load_wf(proj)
    except FileNotFoundError as e:
        return block(str(e))
    pf = proj / w["files"]["process"]
    try:
        process = json.loads(pf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return block(f"process.json 不可读：{e}")
    miss = [k for k in ("layers", "copper_oz") if process.get(k) is None]
    if miss:
        return block(f"工艺声明缺 {miss}（不猜工艺）")

    # 2) 门禁
    gs = wf.gate_status(w, proj)
    notok = [(g, s) for g, _n, s, _m, _c in gs if s != "CONFIRMED"]
    if notok:
        return block(f"门禁未全部确认：{notok}。封存须 G1–G5 均为 CONFIRMED（对话确认，不是技术通过）")
    g5 = [c for _g, _n, _s, _m, c in gs if c and c["gate"] == "G5"][-1]

    # 3) 文件须在工程内并被 G5 绑定
    inputs = {"gerber": a.gerber, "bom": a.bom, "cpl": a.cpl}
    items = [("gerber", a.gerber)] + [(k, v) for k, v in (("bom", a.bom), ("cpl", a.cpl)) if v] + [("extra", x) for x in a.extra]
    rels = {}
    for kind, p in items:
        pp = Path(p) if Path(p).is_absolute() else proj / p
        if not pp.is_file():
            return block(f"文件不存在：{pp}")
        rel = _rel_in_project(proj, pp)
        if rel is None:
            return block(f"{pp} 不在工程目录内，无法被确认绑定。请先把文件放进工程目录再 confirm --bind")
        if rel not in g5["bound"]:
            return block(f"G5 确认没有绑定 {rel}。请用 workflow.py confirm --gate G5 --bind {rel} 重新确认（封存的必须是用户确认过的那一版）")
        if g5["bound"][rel] != _sha(pp):
            return block(f"{rel} 在 G5 确认之后被修改过，须重新确认")
        rels[rel] = (kind, pp)
    if a.bom and not a.cpl or a.cpl and not a.bom:
        return block("BOM 与坐标需成对提供（位号一致性需要两者交叉核对）")

    # 4) 现在重新复核（不信旧报告）
    reports = {}
    gpath = [pp for r, (k, pp) in rels.items() if k == "gerber"][0]
    gargs = [str(gpath), "--process", str(pf)]
    gcode, gout = _capture(gg.main, gargs)
    reports["gerber_guard.txt"] = gout
    ccode, cout = 0, ""
    if a.bom and a.cpl:
        bpath = [pp for r, (k, pp) in rels.items() if k == "bom"][0]
        cpath = [pp for r, (k, pp) in rels.items() if k == "cpl"][0]
        ccode, cout = _capture(bg.main, ["check", "--bom", str(bpath), "--cpl", str(cpath), "--gerber", str(gpath)])
        reports["bom_cpl_guard.txt"] = cout
    if gcode != 0 or ccode != 0:
        print(f"封存被拒：复核 gerber_guard={gcode}，bom_cpl_guard={ccode}（0 才允许）。", file=sys.stderr)
        print(gout[-1500:] + cout[-1500:])
        return 2 if 2 in (gcode, ccode) else 1

    dest = proj / "release" / a.version
    print(f"复核通过。将封存到 {dest}")
    for r, (k, _pp) in rels.items():
        print(f"  [{k}] {r}")
    print("  + process.json / workflow.json 快照 / 复核报告 / manifest.json / README.txt")
    if dest.exists():
        return block(f"{dest} 已存在，拒绝覆盖。请换新版本号")
    if not a.apply:
        print("（预览；加 --apply 才写入）")
        return 0

    dest.mkdir(parents=True)
    (dest / "reports").mkdir()
    files = {}
    for r, (_k, pp) in rels.items():
        t = dest / Path(r).name
        shutil.copy2(pp, t)
        files[t.name] = {"from": r, "bytes": t.stat().st_size, "sha256": _sha(t)}
    shutil.copy2(pf, dest / "process.json")
    (dest / "workflow.snapshot.json").write_text(json.dumps(w, ensure_ascii=False, indent=2), encoding="utf-8")
    for n, txt in reports.items():
        (dest / "reports" / n).write_text(txt, encoding="utf-8")
    manifest = {
        "version": a.version, "project": w["project"], "sealed_at": datetime.now().isoformat(timespec="seconds"),
        "process": process,
        "files": files,
        "evidence": {n: {"sha256": hashlib.sha256(t.encode("utf-8")).hexdigest()} for n, t in reports.items()},
        "gates": [{"gate": g, "name": n, "state": s, "user_reply": c["user_reply"], "at": c["at"], "bound": c["bound"]}
                  for g, n, s, _m, c in gs],
        "statement": "本发布包已通过本 skill 的声明范围内复核与用户对话确认；未上传任何第三方，未下单。"
                     "复核通过不代表电路功能正确、C 编号与器件对应或可直接量产，下单前请以嘉立创下单页/DFM 结果为准。",
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (dest / "README.txt").write_text(
        f"发布包 {w['project']} {a.version}\n封存时间：{manifest['sealed_at']}\n\n"
        f"工艺声明：{process}\n\n文件（sha256 见 manifest.json）：\n"
        + "".join(f"  - {n}（{v['bytes']} 字节）\n" for n, v in files.items())
        + "\n本包做了什么：Gerber 导出包独立复核、（如提供）BOM/坐标格式复核、G1–G5 对话确认留痕。\n"
        "本包没做什么：不验证电路功能；不验证 C 编号与器件对应；线距/焊盘距/阻焊桥等几何由 EDA 自身 DRC 负责；"
        "没有上传、没有下单。\n", encoding="utf-8")
    print(f"OK：已封存 {len(files)} 个文件 → {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

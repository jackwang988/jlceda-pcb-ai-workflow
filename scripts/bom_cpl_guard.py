#!/usr/bin/env python3
"""BOM / 坐标(CPL) 文件独立复核 + 规范化。规则与参数全部来自 data/jlc-bom-cpl-spec.json。

check：逐条核对嘉立创官方格式规范（位号写法、数量一致、坐标单位、层、旋转、BOM↔CPL 位号集合一致、坐标极差≤板尺寸）。
normalize：把 EDA 原生导出（UTF-16 + 制表符 + 数值带 mm 后缀 + 空行）转成官方可接受的 UTF-8 逗号 CSV。

边界：不联网，因此**无法验证嘉立创元件编号(C编号)是否与型号/封装对应**——只检查格式并列出缺失项，
"错误编号比缺少编号更危险"这一条必须靠人工/下单页匹配结果核对。xls/xlsx 不解析（BLOCKED，不当作通过）。

退出码：0 声明范围内无阻断；1 存在阻断；2 BLOCKED(无法读取/不支持的格式)。
"""
import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "data" / "jlc-bom-cpl-spec.json").read_text(encoding="utf-8"))
P = SPEC["params"]
RULE = {r["id"]: r for r in SPEC["rules"]}
ASCII_MAX = 127  # ASCII 码上限，用于识别中文等非 ASCII 位号（语言常量，非工艺阈值）


class Unsupported(Exception):
    pass


# ───────────────────────── 读取 ─────────────────────────
def decode_bytes(b):
    """返回 (text, encoding)。UTF-16(BOM) / UTF-8(-sig) / GBK。"""
    if b[:2] in (bytes([255, 254]), bytes([254, 255])):
        return b.decode("utf-16"), "utf-16"
    if b[:3] == bytes([239, 187, 191]):
        return b.decode("utf-8-sig"), "utf-8-sig"
    try:
        return b.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return b.decode("gbk", "replace"), "gbk"


def read_table(path):
    p = Path(path)
    if p.suffix.lower() in (".xls", ".xlsx"):
        raise Unsupported("xls/xlsx 不解析：请另存为 CSV 后再检查（官方只读首个工作表前12列）")
    text, enc = decode_bytes(p.read_bytes())
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise Unsupported("文件为空")
    head = lines[0]
    delim = "\t" if head.count("\t") >= head.count(",") and "\t" in head else ","
    rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delim))
    header = [re.sub(r"\s+", " ", h.replace("\ufeff", "")).strip() for h in rows[0]]
    body = [[c.strip() for c in r] for r in rows[1:] if any(c.strip() for c in r)]
    return {"header": header, "rows": body, "encoding": enc, "delimiter": "TAB" if delim == "\t" else "COMMA",
            "blank_lines_removed": len(text.splitlines()) - len(lines)}


def col_index(header, name):
    low = [h.lower() for h in header]
    return low.index(name.lower()) if name.lower() in low else None


# ───────────────────────── 位号 ─────────────────────────
_RANGE = re.compile(r"^([A-Za-z_]+)(\d+)-(?:([A-Za-z_]+))?(\d+)$")


def expand_designators(cell):
    """返回 (位号列表, 问题列表)。"""
    probs, out = [], []
    bad_seps = [c for c in P["designator_separators_bad"] if c in cell]
    if bad_seps:
        probs.append(("BOM.DES.SEP", f"位号分隔符不合规 {bad_seps}: {cell[:40]!r}"))
    tokens = [t for t in re.split(r"[,\s" + re.escape("".join(P["designator_separators_bad"])) + r"]+", cell) if t]
    for t in tokens:
        m = _RANGE.match(t)
        if m:
            pre1, a, pre2, b = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
            if pre2 and pre2 != pre1:
                probs.append(("BOM.DES.RANGE", f"范围前缀不一致 {t}"))
                continue
            if a >= b:
                probs.append(("BOM.DES.RANGE", f"范围起始须小于结束 {t}"))
                continue
            out.extend(f"{pre1}{n}" for n in range(a, b + 1))
        else:
            out.append(t)
    return out, probs


def des_problems(d):
    p = []
    if len(d) > P["designator_max_len"]:
        p.append(("BOM.DES.LEN", f"位号超长({len(d)}): {d[:20]}…"))
    if any(ord(ch) > ASCII_MAX for ch in d):
        p.append(("BOM.DES.CHARS", f"位号含中文/非 ASCII 字符: {d}"))
    bad = [ch for ch in d if ch in P["designator_forbidden_chars"]]
    if bad:
        p.append(("BOM.DES.CHARS", f"位号含禁用字符 {bad}: {d}"))
    return p


# ───────────────────────── 坐标值 ─────────────────────────
_NUM = re.compile(r"^(-?\d+(?:\.\d+)?)\s*([A-Za-z]*)$")


def parse_coord(cell):
    m = _NUM.match(cell.strip())
    if not m:
        return None, None
    return float(m.group(1)), (m.group(2).lower() or None)


# ───────────────────────── 检查 ─────────────────────────
def check_bom(t, items):
    def add(rid, st, msg):
        items.append({"id": rid, "status": st, "msg": msg})

    h = t["header"]
    idx = {c: col_index(h, c) for c in P["bom_required_columns"]}
    miss = [c for c, i in idx.items() if i is None]
    if miss:
        add("BOM.COL.REQUIRED", "BLOCK", f"BOM 缺少必需列 {miss}（现有表头：{h}）")
        return None
    qi = col_index(h, "Quantity")
    ci = None
    for name in ("Supplier Part", "嘉立创元件编号", "LCSC Part", "LCSC"):
        ci = col_index(h, name)
        if ci is not None:
            break
    all_des, row_of, missing_lcsc, bad_lcsc, ambiguous, empties, totals = {}, {}, [], [], [], [], []
    for n, r in enumerate(t["rows"], 2):
        get = lambda i: (r[i] if i is not None and i < len(r) else "")  # noqa: E731
        cm, ds, fp = get(idx["Comment"]), get(idx["Designator"]), get(idx["Footprint"])
        if any(str(c).strip().lower() in P["total_row_markers"] for c in r[:2]) or (not ds and cm.lower() in P["total_row_markers"]):
            totals.append(n)
            continue
        for nm, v in (("Comment", cm), ("Designator", ds), ("Footprint", fp)):
            if not v:
                empties.append(f"第{n}行 {nm}")
        des, probs = expand_designators(ds)
        for rid, msg in probs:
            add(rid, "BLOCK", f"第{n}行 {msg}")
        for d in des:
            for rid, msg in des_problems(d):
                add(rid, "BLOCK", f"第{n}行 {msg}")
            key = d.upper()
            if key in all_des:
                other = all_des[key]
                rid = "BOM.DES.DUP" if other == d else "BOM.DES.CASE_DUP"
                add(rid, "BLOCK", f"位号重复/大小写冲突 {other} 与 {d}（第{row_of[key]}行、第{n}行）")
            else:
                all_des[key] = d
                row_of[key] = n
        if qi is not None and get(qi):
            try:
                q = int(float(get(qi)))
                if q != len(des):
                    add("BOM.QTY.MATCH", "BLOCK", f"第{n}行 Quantity={get(qi)} 与位号数 {len(des)} 不一致（{ds[:30]}）")
            except ValueError:
                add("BOM.QTY.MATCH", "BLOCK", f"第{n}行 Quantity 不是整数: {get(qi)!r}")
        if re.fullmatch(r"\d+", cm):
            ambiguous.append(f"第{n}行 Comment={cm!r}")
        if ci is not None:
            lc = get(ci)
            if not lc:
                missing_lcsc.append(ds[:24])
            elif not re.match(P["lcsc_part_regex"], lc):
                bad_lcsc.append(f"第{n}行 {lc!r}")
    if empties:
        add("BOM.EMPTY.FIELD", "BLOCK", "必需字段为空：" + "；".join(empties[:8]))
    if totals:
        add("BOM.TOTAL_ROW", "WARN", f"疑似合计行：第 {totals} 行，应删除")
    if ambiguous:
        add("BOM.COMMENT.AMBIG", "WARN", "；".join(ambiguous[:6]))
    if ci is None:
        add("BOM.LCSC.MISSING", "WARN", "没有嘉立创元件编号列，将仅凭 Comment/Footprint 匹配")
    else:
        if missing_lcsc:
            add("BOM.LCSC.MISSING", "WARN", f"{len(missing_lcsc)} 行缺嘉立创编号：{missing_lcsc[:6]}")
        if bad_lcsc:
            add("BOM.LCSC.FORMAT", "WARN", "编号格式不是 C+数字：" + "；".join(bad_lcsc[:6]))
        add("BOM.LCSC.FORMAT", "WARN", "本工具不联网，无法核对 C 编号与型号/封装是否对应；错误编号比缺少更危险，请以下单页匹配结果为准")
    return set(all_des.values())


def check_cpl(t, items, board):
    def add(rid, st, msg):
        items.append({"id": rid, "status": st, "msg": msg})

    unit_pat = re.compile(r"\s*\((?:mm|mil|in|inch)\)\s*$|\s+(?:mm|mil)$", re.I)
    h = []
    for c in t["header"]:
        if unit_pat.search(c) and c.lower().startswith(("mid", "ref", "pad")):
            add("CPL.HEADER.UNIT", "BLOCK", f"表头不得带单位: {c!r}（应写 {unit_pat.sub('', c)!r}）")
            c = unit_pat.sub("", c)  # 清洗后继续检查其余项，避免只报"缺列"误导
        h.append(c)
    idx = {c: col_index(h, c) for c in P["cpl_required_columns"]}
    miss = [c for c, i in idx.items() if i is None]
    if miss:
        add("CPL.COL.REQUIRED", "BLOCK", f"坐标文件缺少必需列 {miss}（现有表头：{h}）")
        return None
    seen, xs, ys, units, bad_layer, bad_rot, bad_num = {}, [], [], set(), [], [], []
    for n, r in enumerate(t["rows"], 2):
        g = lambda name: (r[idx[name]] if idx[name] < len(r) else "")  # noqa: E731
        d = g("Designator").strip('"')
        if not d:
            add("CPL.COL.REQUIRED", "BLOCK", f"第{n}行位号为空")
            continue
        for rid, msg in des_problems(d):
            add(rid.replace("BOM.", "CPL."), "BLOCK", f"第{n}行 {msg}")
        k = d.upper()
        if k in seen:
            add("CPL.DES.DUP", "BLOCK", f"位号重复 {seen[k]} / {d}")
        seen[k] = d
        for nm, acc in (("Mid X", xs), ("Mid Y", ys)):
            v, u = parse_coord(g(nm))
            if v is None:
                bad_num.append(f"第{n}行 {nm}={g(nm)!r}")
            else:
                acc.append(v)
                units.add(u or "mm")
                if u and u not in P["allowed_coord_units"]:
                    bad_num.append(f"第{n}行 {nm} 单位 {u!r} 不被接受")
        if g("Layer").upper() not in P["allowed_layers"]:
            bad_layer.append(f"第{n}行 {d}={g('Layer')!r}")
        rot = g("Rotation")
        m = re.fullmatch(r"-?\d+(?:\.(\d+))?", rot)
        if not m:
            bad_rot.append(f"第{n}行 {d}={rot!r}")
        elif m.group(1) and len(m.group(1)) > P["rotation_max_decimals"]:
            bad_rot.append(f"第{n}行 {d} 小数位 {len(m.group(1))} 位 > {P['rotation_max_decimals']}")
    if bad_num:
        add("CPL.UNIT.CONSIST", "BLOCK", "坐标无法解析或单位不被接受：" + "；".join(bad_num[:6]))
    if len(units) > 1:
        add("CPL.UNIT.CONSIST", "BLOCK", f"同一文件混用单位 {sorted(units)}")
    if bad_layer:
        add("CPL.LAYER", "BLOCK", "Layer 仅可为 T/B/Top/Bottom：" + "；".join(bad_layer[:6]))
    if bad_rot:
        add("CPL.ROT.NUMERIC", "BLOCK", "；".join(bad_rot[:6]))
    unit = (sorted(units)[0] if units else "mm")
    if unit == "mil" and any(parse_coord(r[idx["Mid X"]])[1] is None for r in t["rows"] if idx["Mid X"] < len(r)):
        add("CPL.UNIT.MIL_SUFFIX", "BLOCK", "单位为 mil 时数值后必须注明单位")
    if board and xs and ys:
        scale = {"mm": 1, "mil": 1}  # mil 文件的板尺寸需同单位输入
        rx, ry = max(xs) - min(xs), max(ys) - min(ys)
        if unit == "mil":
            rx, ry = rx * 25.4 / 1000, ry * 25.4 / 1000  # 换算常数 mil→mm
        _ = scale
        if rx > board[0] or ry > board[1]:
            add("CPL.RANGE.BOARD", "BLOCK", f"坐标极差 {rx:.3f}×{ry:.3f}mm 超过板尺寸 {board[0]}×{board[1]}mm（器件超出板外）")
        else:
            add("CPL.RANGE.BOARD", "PASS", f"坐标极差 {rx:.3f}×{ry:.3f}mm ≤ 板尺寸 {board[0]}×{board[1]}mm")
    elif not board:
        add("CPL.RANGE.BOARD", "WARN", "未提供板尺寸（--board-size 或 --gerber），未检查坐标极差")
    return set(seen.values())


def board_from_gerber(zp):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import gerber_guard as gg
    files = gg.read_package(zp)
    _items, meas, _n, _l = gg.check_package(files, None)
    if "board_w" not in meas:
        raise Unsupported("无法从 Gerber 得到板框尺寸")
    return (meas["board_w"], meas["board_h"])


def run_checks(bom_path, cpl_path, board=None):
    items, info = [], {}
    bom_set = cpl_set = None
    for label, path in (("BOM", bom_path), ("CPL", cpl_path)):
        if not path:
            continue
        t = read_table(path)
        info[label] = {"file": str(path), "encoding": t["encoding"], "delimiter": t["delimiter"], "rows": len(t["rows"])}
        if t["encoding"] == "utf-16" or t["delimiter"] == "TAB":
            items.append({"id": "FILE.ENC.NATIVE", "status": "WARN",
                          "msg": f"{label} 为 EDA 原生格式（{t['encoding']} + {t['delimiter']}）：上传嘉立创前请先 normalize 转 UTF-8 逗号 CSV"})
        if label == "BOM":
            bom_set = check_bom(t, items)
        else:
            cpl_set = check_cpl(t, items, board)
    if bom_set is not None and cpl_set is not None:
        only_b, only_c = sorted(bom_set - cpl_set), sorted(cpl_set - bom_set)
        if only_b or only_c:
            items.append({"id": "X.BOM_CPL.SET", "status": "BLOCK",
                          "msg": f"BOM 与坐标位号不一致：仅 BOM 有 {only_b[:10]}；仅坐标有 {only_c[:10]}"})
        else:
            items.append({"id": "X.BOM_CPL.SET", "status": "PASS", "msg": f"BOM 与坐标位号集合一致（{len(bom_set)} 个）"})
    return items, info


# ───────────────────────── 规范化 ─────────────────────────
def normalize(src, dst, kind):
    t = read_table(src)
    h, rows = t["header"], t["rows"]
    out = []
    if kind == "cpl":
        coord_cols = [i for i, c in enumerate(h) if c.lower() in ("mid x", "mid y", "ref x", "ref y", "pad x", "pad y")]
        units = set()
        for r in rows:
            for i in coord_cols:
                if i < len(r):
                    v, u = parse_coord(r[i])
                    if v is not None:
                        units.add(u or "mm")
        keep = len(units) == 1 and "mil" in units  # mil 文件必须保留单位后缀
        for r in rows:
            nr = list(r)
            for i in coord_cols:
                if i < len(nr):
                    v, u = parse_coord(nr[i])
                    if v is not None:
                        nr[i] = f"{nr[i].split(u)[0] if u else nr[i]}" if not keep else (nr[i] if u else f"{nr[i]}mil")
                        nr[i] = nr[i].strip()
            out.append(nr)
    else:
        out = [list(r) for r in rows]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(h)
    w.writerows(out)
    Path(dst).write_text(buf.getvalue(), encoding="utf-8", newline="")
    return {"from": t["encoding"] + "/" + t["delimiter"], "to": "utf-8/COMMA", "rows": len(out),
            "blank_lines_removed": t["blank_lines_removed"]}


# ───────────────────────── CLI ─────────────────────────
def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="嘉立创 BOM/坐标 文件复核与规范化")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--bom")
    c.add_argument("--cpl")
    c.add_argument("--board-size", help="板尺寸 WxH(mm)，如 60x40")
    c.add_argument("--gerber", help="Gerber zip，自动取板框尺寸")
    c.add_argument("--json", action="store_true")
    n = sub.add_parser("normalize")
    n.add_argument("--bom")
    n.add_argument("--cpl")
    n.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "normalize":
            od = Path(a.out_dir)
            if not od.is_dir():
                print(f"BLOCKED: 目录不存在 {od}", file=sys.stderr)
                return 2
            for kind, src in (("bom", a.bom), ("cpl", a.cpl)):
                if not src:
                    continue
                dst = od / f"{Path(src).stem}.normalized.csv"
                if dst.exists():
                    print(f"BLOCKED: {dst} 已存在，拒绝覆盖", file=sys.stderr)
                    return 2
                print(f"{kind.upper()} → {dst}  {normalize(src, dst, kind)}")
            return 0
        if not (a.bom or a.cpl):
            ap.error("至少提供 --bom 或 --cpl")
        board = None
        if a.board_size:
            m = re.fullmatch(r"(\d+(?:\.\d+)?)[xX](\d+(?:\.\d+)?)", a.board_size)
            if not m:
                ap.error("--board-size 形如 60x40")
            board = (float(m.group(1)), float(m.group(2)))
        elif a.gerber:
            board = board_from_gerber(a.gerber)
        items, info = run_checks(a.bom, a.cpl, board)
    except (Unsupported, OSError) as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        return 2
    blocks = sum(1 for i in items if i["status"] == "BLOCK")
    if a.json:
        print(json.dumps({"info": info, "items": items, "exit": 1 if blocks else 0}, ensure_ascii=False, indent=2))
        return 1 if blocks else 0
    for k, v in info.items():
        print(f"{k}：{v['file']}｜{v['encoding']}/{v['delimiter']}｜{v['rows']} 行")
    tag = {"BLOCK": "【阻断级】", "WARN": "【中风险】", "PASS": "  PASS  "}
    for i in sorted(items, key=lambda x: {"BLOCK": 0, "WARN": 1, "PASS": 2}[x["status"]]):
        print(f"{tag[i['status']]} {i['id']}：{i['msg']}")
    print("\n结论：" + ("存在阻断项，禁止用于下单上传" if blocks else "声明范围内无阻断（不代表 C 编号与器件对应，也不代表可贴装）"))
    return 1 if blocks else 0


if __name__ == "__main__":
    sys.exit(main())

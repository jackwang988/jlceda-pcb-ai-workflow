#!/usr/bin/env python3
"""Gerber 导出包独立复核：直接读文件，不依赖 EDA 的 DRC 自述。

做三件事：
  1) 文件结构：必需/应有层文件齐全(清单见 data/jlc-gerber-layout.json)，内层数与层数一致
  2) 格式与内容：单位/格式一致、以 M02/M30 收尾、板框闭合、铜层非空
  3) 从文件反推实测值(最小线宽/最小孔径/槽宽/板尺寸)，交给 spec_check 与嘉立创规范库对照

能反推 / 不能反推：
  能：圆形光圈的走线宽度(以 D01 画线、非铺铜区域)、Excellon 刀具直径、板框外接尺寸
  不能：线距、焊盘到线距离、阻焊桥、丝印到焊盘间隙、丝印字高（需几何运算或 EDA API）
        → 这些不在本脚本评估，报告会明确列出"未覆盖"，不会被当成通过

退出码：0 声明范围内无阻断；1 存在阻断；2 BLOCKED(无法解析/缺工艺声明/严格模式缺证据)。
退出 0 不代表板子能生产，也不代表电路正确。
"""
import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_check as sc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LAYOUT = sc.load_json(ROOT / "data" / "jlc-gerber-layout.json")
MM_PER_INCH = 25.4  # 物理换算常数，非工艺阈值


class Unsupported(Exception):
    pass


# ───────────────────────── 读取包 ─────────────────────────
def read_package(path):
    """返回 {文件名: bytes}。支持 zip 或目录。"""
    p = Path(path)
    files = {}
    if p.is_dir():
        for f in p.iterdir():
            if f.is_file():
                files[f.name] = f.read_bytes()
    else:
        with zipfile.ZipFile(p) as z:
            for i in z.infolist():
                if not i.is_dir():
                    files[Path(i.filename).name] = z.read(i)
    return files


# ───────────────────────── Gerber 解析 ─────────────────────────
_RE_FS = re.compile(r"%FS([LT])([AI])X(\d)(\d)Y(\d)(\d)\*%")
_RE_MO = re.compile(r"%MO(MM|IN)\*%")
_RE_AD = re.compile(r"%ADD(\d+)([^,*%]+),?([^*%]*)\*%")
_RE_COORD = re.compile(r"^(?:G0?([123]))?(?:X(-?\d+))?(?:Y(-?\d+))?(?:I(-?\d+))?(?:J(-?\d+))?D0?([123])$")


def parse_gerber(text):
    fs, mo = _RE_FS.search(text), _RE_MO.search(text)
    if not fs or not mo:
        raise Unsupported("缺少 %FS 或 %MO 头")
    if fs.group(1) != "L" or fs.group(2) != "A":
        raise Unsupported(f"仅支持 前导零省略+绝对坐标(FSLA)，实际 FS{fs.group(1)}{fs.group(2)}")
    dec = int(fs.group(4))
    unit = "mm" if mo.group(1) == "MM" else "in"
    scale = 1.0 if unit == "mm" else MM_PER_INCH
    aps = {}
    for m in _RE_AD.finditer(text):
        shape, params = m.group(2), m.group(3)
        dia = None
        if shape == "C" and params:
            try:
                dia = float(params.split("X")[0]) * scale
            except ValueError:
                dia = None
        aps[int(m.group(1))] = {"shape": shape, "dia": dia}
    body = re.sub(r"%[^%]*%", "", text, flags=re.S).replace("\n", "").replace("\r", "")
    info = {"unit": unit, "fmt": f"{fs.group(3)}:{fs.group(4)}", "apertures": aps, "draw_dia": [], "by_section": {},
            "draws": 0, "flashes": 0, "regions": 0, "arcs": 0, "segments": [], "points": [], "ends_m02": False}
    cur, mode, in_region, section = None, 1, False, ""
    pos = (0.0, 0.0)
    for raw in body.split("*"):
        c = raw.strip()
        if not c:
            continue
        if c.startswith("G04"):
            ms = re.match(r"G04 (\w[\w ]*?) Start$", c)  # EDA 段落标记：Text/Pad/Track/Circle/PolygonModel…
            if ms:
                section = ms.group(1)
            continue
        if c == "M02":
            info["ends_m02"] = True
            continue
        if c in ("G36", "G37"):
            in_region = c == "G36"
            if in_region:
                info["regions"] += 1
            continue
        m = re.fullmatch(r"(?:G54)?D(\d{2,})", c)  # EDA 导出为旧式 G54Dnn
        if m:
            cur = int(m.group(1))
            continue
        m = re.fullmatch(r"G0?([123])", c)
        if m:
            mode = int(m.group(1))
            continue
        m = _RE_COORD.match(c)
        if not m:
            continue
        g, x, y, _i, _j, d = m.groups()
        if g:
            mode = int(g)
        nx = int(x) / 10 ** dec * scale if x is not None else pos[0]
        ny = int(y) / 10 ** dec * scale if y is not None else pos[1]
        d = int(d)
        if d == 2:
            pass
        elif d == 1:
            if not in_region:
                info["draws"] += 1
                ap = aps.get(cur)
                if ap and ap["dia"] is not None:
                    info["draw_dia"].append(ap["dia"])
                    info["by_section"].setdefault(section, []).append(ap["dia"])
                info["segments"].append((pos, (nx, ny)))
                if mode in (2, 3):
                    info["arcs"] += 1
        elif d == 3:
            info["flashes"] += 1
        pos = (nx, ny)
        info["points"].append(pos)
    return info


def parse_drill(text):
    unit = "mm" if "METRIC" in text else ("in" if "INCH" in text else None)
    if unit is None:
        raise Unsupported("钻孔文件缺少 METRIC/INCH")
    scale = 1.0 if unit == "mm" else MM_PER_INCH
    ptype = "plated" if "TYPE=PLATED" in text else ("nonplated" if "TYPE=NON_PLATED" in text else "unknown")
    tools, hits, slots, cur, ended = {}, {}, {}, None, False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(";") or not s:
            continue
        if s == "M30":
            ended = True
            continue
        m = re.match(r"^T(\d+)C([\d.]+)", s)
        if m:
            tools[int(m.group(1))] = float(m.group(2)) * scale
            continue
        m = re.fullmatch(r"T(\d+)", s)
        if m:
            cur = int(m.group(1))
            continue
        if s.startswith(("X", "Y")) and cur is not None:
            tgt = slots if "G85" in s else hits
            tgt[cur] = tgt.get(cur, 0) + 1
    used = lambda d: sorted({tools[t] for t in d if t in tools})  # noqa: E731

    def hist(d):  # 孔径(保畝4位) -> 个数
        h = {}
        for t, c in d.items():
            if t in tools:
                k = round(tools[t], 4)
                h[k] = h.get(k, 0) + c
        return h
    return {"unit": unit, "type": ptype, "tools": tools, "hole_dias": used(hits), "slot_dias": used(slots),
            "hole_hist": hist(hits), "slot_hist": hist(slots),
            "ends_m30": ended, "hole_count": sum(hits.values()), "slot_count": sum(slots.values())}


# ───────────────────────── 分类 / 工具 ─────────────────────────
def classify(name):
    ext = name.rsplit(".", 1)[-1].upper() if "." in name else ""
    if re.match(LAYOUT["inner_layer_pattern"]["regex"], name):
        return "inner"
    if ext in ("GTL", "GBL"):
        return "copper"
    if ext in ("GTO", "GBO"):
        return "silk"
    if ext in ("GTS", "GBS"):
        return "mask"
    if ext in ("GTP", "GBP"):
        return "paste"
    if ext == "GKO":
        return "outline"
    if ext == "DRL":
        return "drill"
    if ext == "GDL":
        return "document"
    return "other"


def outline_closed(segments, ndig=3):
    """线段端点度数全为偶数 ⇒ 闭合(弧也按端点算)。"""
    deg = {}
    for a, b in segments:
        for p in (a, b):
            k = (round(p[0], ndig), round(p[1], ndig))
            deg[k] = deg.get(k, 0) + 1
    odd = [k for k, v in deg.items() if v % 2]
    return (len(segments) > 0 and not odd), odd


def decode(b):
    return b.decode("utf-8", "replace")


# ───────────────────────── 主检查 ─────────────────────────
def check_package(files, process):
    items = []  # {id,status,msg}
    meas = {}
    notes = []

    def add(i, status, msg):
        items.append({"id": i, "status": status, "msg": msg})

    names = set(files)
    inner = sorted(n for n in names if classify(n) == "inner")
    inferred_layers = 2 + len(inner)
    layers = process.get("layers") if process else None
    if layers is not None and layers != inferred_layers and layers > 2:
        add("GB.LAYERS.MATCH", "BLOCK", f"声明 {layers} 层，但包内内层文件 {len(inner)} 个(推断 {inferred_layers} 层)")
    elif layers is not None and layers == 2 and inner:
        add("GB.LAYERS.MATCH", "BLOCK", f"声明 2 层，但包内出现内层文件 {inner}")

    # 1) 文件结构
    for req in LAYOUT["required"]:
        if req["name"] not in names:
            add("GB.FILE.REQUIRED", "BLOCK", f"缺少必需文件 {req['name']}（{req['role']}）" + (f"：{req['why']}" if req.get("why") else ""))
    for exp in LAYOUT["expected"]:
        if exp["name"] not in names:
            add("GB.FILE.EXPECTED", "WARN", f"缺少通常应有的文件 {exp['name']}（{exp['role']}）" + (f"：{exp['why']}" if exp.get("why") else ""))
    for n, b in files.items():
        if len(b) == 0:
            add("GB.FILE.EMPTY", "BLOCK", f"{n} 是 0 字节空文件")

    # 2) 解析各文件
    parsed, fmts, units, copper_ops = {}, set(), set(), {}
    for n, b in sorted(files.items()):
        kind = classify(n)
        if kind in ("copper", "inner", "silk", "mask", "paste", "outline", "document"):
            try:
                g = parse_gerber(decode(b))
            except Unsupported as e:
                add("GB.PARSE", "BLOCK", f"{n} 无法解析：{e}（BLOCKED，不得视为通过）")
                continue
            parsed[n] = (kind, g)
            fmts.add(g["fmt"])
            units.add(g["unit"])
            if not g["ends_m02"]:
                add("GB.END.M02", "BLOCK", f"{n} 未以 M02* 结束（文件可能被截断）")
            if kind in ("copper", "inner"):
                copper_ops[n] = g["draws"] + g["flashes"] + g["regions"]
        elif kind == "drill":
            try:
                d = parse_drill(decode(b))
            except Unsupported as e:
                add("GB.PARSE", "BLOCK", f"{n} 无法解析：{e}")
                continue
            parsed[n] = ("drill", d)
            units.add(d["unit"])
            if not d["ends_m30"]:
                add("GB.END.M30", "BLOCK", f"{n} 未以 M30 结束（钻孔文件可能被截断）")
    if len(fmts) > 1:
        add("GB.FMT.CONSIST", "BLOCK", f"各层坐标格式不一致 {sorted(fmts)}")
    if len(units) > 1:
        add("GB.UNIT.CONSIST", "BLOCK", f"各文件单位不一致 {sorted(units)}")

    # 铜层是否近乎为空（启发式）
    h = LAYOUT["heuristics"]
    for n, ops in copper_ops.items():
        if ops < h["copper_layer_min_ops"]:
            add("GB.COPPER.EMPTY", "WARN", f"{n} 仅有 {ops} 个图形操作，几乎为空：{h['copper_layer_min_ops_why']}")

    # 3) 板框
    for n, (kind, g) in parsed.items():
        if kind != "outline":
            continue
        closed, odd = outline_closed(g["segments"])
        if not g["segments"]:
            add("GB.OUTLINE.EMPTY", "BLOCK", f"{n} 没有任何板框线段")
        elif not closed:
            add("GB.OUTLINE.CLOSED", "BLOCK", f"板框未闭合：{len(odd)} 个端点度数为奇数（例 {odd[:3]}）")
        else:
            pts = g["points"]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            w, hh = max(xs) - min(xs), max(ys) - min(ys)
            meas["board_w"], meas["board_h"] = round(w, 4), round(hh, 4)
            meas["min_board_dim"] = round(min(w, hh), 4)
            tag = "（含圆弧，外接尺寸为近似）" if g["arcs"] else ""
            add("GB.OUTLINE.CLOSED", "PASS", f"板框闭合，外接尺寸 {w:.3f} × {hh:.3f} mm{tag}")

    # 4) 实测值反推
    cu_w = [d for n, (k, g) in parsed.items() if k in ("copper", "inner") for d in g["draw_dia"]]
    if cu_w:
        meas["min_track_width"] = round(min(cu_w), 4)
    elif copper_ops and any(copper_ops.values()):
        add("GB.TRACK.NONE", "WARN", "所有铜层都没有走线(只有焊盘/铺铜区域)：板子可能尚未布线或导出遗漏；未反推线宽，不得视为线宽合格")
    # 官方规范原文是“字符粗细”，只用 Text 段的画线宽度；非文字图形(元件轮廓等)单独给提示，避免误报
    silk_text = [d for n, (k, g) in parsed.items() if k == "silk" for d in g["by_section"].get("Text", [])]
    silk_gfx = [d for n, (k, g) in parsed.items() if k == "silk" for s, v in g["by_section"].items() if s != "Text" for d in v]
    if silk_text:
        meas["min_silk_width"] = round(min(silk_text), 4)
    elif any(k == "silk" for k, _ in parsed.values()):
        notes.append("丝印层没有文字画线段，未反推字符线宽")
    if silk_gfx and (not silk_text or min(silk_gfx) < min(silk_text)):
        notes.append(f"丝印非文字图形(元件轮廓/标记等)最细线宽 {min(silk_gfx):.4f}mm：不属于官方“字符粗细”规范，仅提示可能印不清晰")
    # 4.1.93 起额外导出 *_Via.DRL：它是 PTH_Through.DRL(全部金属化孔) 的过孔子集，不是“另一半”。
    # 插件孔 = PTH_Through 按孔径的个数 - Via 按孔径的个数（GB-01，已用实测包验证：过孔 51 个 == EDA API 过孔数）。
    via_hist, pth_hist = None, None
    for n, (k, d) in parsed.items():
        if k == "drill" and d["type"] == "plated":
            if n.upper().endswith("_VIA.DRL"):
                via_hist = d["hole_hist"]
            else:
                pth_hist = d["hole_hist"] if pth_hist is None else {**pth_hist, **d["hole_hist"]}
    has_via_file = via_hist is not None
    if has_via_file and pth_hist is not None:
        meas["via_count"] = sum(via_hist.values())
        th = {dia: c - via_hist.get(dia, 0) for dia, c in pth_hist.items() if c - via_hist.get(dia, 0) > 0}
        if th:
            meas["min_th_drill"] = min(th)
        bad = [dia for dia, c in via_hist.items() if c > pth_hist.get(dia, 0)]
        if bad:
            add("GB.DRILL.VIA_SUBSET", "BLOCK", f"_Via.DRL 中的孔径 {bad} 个数超过 PTH_Through.DRL，两文件不一致")
    for n, (k, d) in parsed.items():
        if k != "drill":
            continue
        if d["type"] == "plated" and d["hole_dias"]:
            meas["min_plated_drill"] = round(min(meas.get("min_plated_drill", 1e9), min(d["hole_dias"])), 4)
        if d["type"] == "nonplated" and d["hole_dias"]:
            meas["min_npth_drill"] = round(min(meas.get("min_npth_drill", 1e9), min(d["hole_dias"])), 4)
        if d["slot_dias"]:
            key = "min_slot_plated_width" if d["type"] == "plated" else "min_slot_npth_width"
            meas[key] = round(min(meas.get(key, 1e9), min(d["slot_dias"])), 4)
    if not any(classify(n) == "drill" for n in names):
        notes.append("包内无钻孔文件，未反推孔径（若板上有孔应已在 GB.FILE.EXPECTED 告警）")
    elif not has_via_file:
        notes.append("该包没有 *_Via.DRL（旧版导出）：过孔与插件孔合并，未反推 min_th_drill")

    # 来源信息(便于判断是否陈旧)
    for n, b in files.items():
        m = re.search(r"G04 (EasyEDA Pro v[^,]+), ([\d-]+ [\d:]+)\*", decode(b)[:600])
        if m:
            notes.append(f"导出自 {m.group(1)}，时间 {m.group(2)}（请确认与当前设计版本一致）")
            break
    return items, meas, notes, inferred_layers


UNCOVERED = ["线距(min_track_space)", "焊盘到线距离(min_pad_to_track)", "阻焊桥(min_mask_bridge)",
             "丝印字高(min_silk_height)", "丝印到焊盘间隙(min_silk_to_pad)", "铜到板边距离(min_copper_to_edge)",
             "过孔外径/孔环/孔边距(需EDA API)"]


def main(argv=None):
    sc._utf8()
    ap = argparse.ArgumentParser(description="Gerber 导出包独立复核")
    ap.add_argument("package", help="Gerber zip 或已解压目录")
    ap.add_argument("--process", help="工艺声明 JSON；不提供则规范复核无法进行(BLOCKED)")
    ap.add_argument("--extra-measurements", help="补充实测值 JSON（如来自 EDA API 的线距/过孔等），用于补全覆盖")
    ap.add_argument("--structure-only", action="store_true", help="显式只做结构与格式检查，跳过规范复核")
    ap.add_argument("--strict", action="store_true", help="规范复核用严格模式：任何适用规则缺证据即 BLOCKED")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    try:
        files = read_package(a.package)
    except Exception as e:
        print(f"BLOCKED: 无法读取 {a.package}: {e}", file=sys.stderr)
        return 2
    process = sc.load_json(a.process) if a.process else None
    items, meas, notes, inferred = check_package(files, process)
    if a.extra_measurements:
        meas.update(sc.load_json(a.extra_measurements))

    spec_out, spec_code, spec_summary = None, 0, None
    if a.structure_only:
        notes.append("已指定 --structure-only：未做规范复核")
    elif not process:
        spec_code = 2
        notes.append("BLOCKED：未提供 --process，无法选择适用的工艺规则（不猜工艺）。请声明 layers/copper_oz/thickness_mm/surface 等。")
    else:
        sets = [(sc.load_json(sc.DATA / "jlc-pcb-capabilities.json"), "pcb")]
        if process.get("smt") in ("economy", "standard"):
            sets.append((sc.load_json(sc.DATA / "jlc-smt-capabilities.json"), "smt"))
        try:
            results, spec_summary, spec_code = sc.evaluate(process, meas, sets, partial=not a.strict)
            spec_out = sc.render(results, spec_summary, process, spec_code)
        except ValueError as e:
            spec_code = 2
            notes.append(f"BLOCKED：{e}")

    blocks = sum(1 for i in items if i["status"] == "BLOCK")
    code = 1 if (blocks or spec_code == 1) else (2 if spec_code == 2 else 0)

    if a.json:
        print(json.dumps({"structure": items, "measurements": meas, "notes": notes, "spec_summary": spec_summary,
                          "uncovered": UNCOVERED, "exit": code}, ensure_ascii=False, indent=2))
        return code
    print(f"包：{a.package}｜文件 {len(files)} 个｜推断层数 {inferred}")
    tagmap = {"BLOCK": "【阻断级】", "WARN": "【中风险】", "PASS": "  PASS  "}
    for i in sorted(items, key=lambda x: {"BLOCK": 0, "WARN": 1, "PASS": 2}[x["status"]]):
        print(f"{tagmap[i['status']]} {i['id']}：{i['msg']}")
    if not items:
        print("  PASS   文件结构与格式未发现问题")
    print("— 从文件反推的实测值：", json.dumps(meas, ensure_ascii=False))
    for n in notes:
        print("  注：", n)
    if spec_out:
        print("\n— 规范复核（嘉立创工艺库，仅覆盖可由文件反推的项）")
        print(spec_out)
    print("\n— 本脚本不评估（需 EDA API 或几何运算，不得视为通过）：" + "；".join(UNCOVERED))
    print({0: "结论：声明范围内无阻断（不代表可生产）", 1: "结论：存在阻断项，禁止导出放行",
           2: "结论：BLOCKED——缺工艺声明/无法解析/缺证据，不得视为通过"}[code])
    return code


if __name__ == "__main__":
    sys.exit(main())

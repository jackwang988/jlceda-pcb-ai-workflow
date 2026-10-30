#!/usr/bin/env python3
"""缺陷注入 + 单元 + 规范库完整性测试。

核心原则：拿夹具包当基线，故意植入缺陷，每一种缺陷都必须被对应门禁抓到；漏报 = 不合格。
默认离线运行；加 --live 额外测试对运行中 EDA 的 DRC 与导出（需 Bridge 在线且当前是 PCB）。
退出码：0 全部通过；1 有失败。

环境变量 JLCEDA_REAL_FIXTURES=<目录>（可选）：追加“真实导出文件回归”。目录里按以下名字放你自己的文件即可，缺哪个就跳过哪个：
  real_new_export.zip   real_old_unrouted.zip   real_bom_utf16.csv   real_cpl_utf16.csv   process_2layer_1oz.json
这些文件不随 skill 分发（含真实设计）；它们只在你本机参与回归，断言是“不应误报阻断”这类与具体设计无关的性质。
"""
import contextlib
import io
import json
import os
import re
import sys
sys.dont_write_bytecode = True
import tempfile
import zipfile
from pathlib import Path

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"  # prevent test subprocesses from creating caches
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))
import bom_cpl_guard as bg  # noqa: E402
import bridge_client as bc  # noqa: E402
import gerber_guard as gg  # noqa: E402
import release as rel  # noqa: E402
import rules_check as rc  # noqa: E402
import spec_drift as sd  # noqa: E402
import workflow as wfm  # noqa: E402
import spec_check as sc  # noqa: E402

FIX = HERE / "fixtures"
BASE = FIX / "synthetic_2layer_fs45.zip"
OLD = FIX / "synthetic_2layer_fs26_unrouted.zip"
PROC = FIX / "process_2layer_1oz.json"
NBOM = FIX / "synthetic_native_bom_utf16.csv"
NCPL = FIX / "synthetic_native_cpl_utf16.csv"

RESULTS = []


def load(zp):
    with zipfile.ZipFile(zp) as z:
        return {Path(i.filename).name: z.read(i) for i in z.infolist() if not i.is_dir()}


def dump(files, path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(n, b)


def run_guard(files, process=PROC, extra=()):
    """返回 (退出码, 输出文本)。"""
    with tempfile.TemporaryDirectory() as td:
        zp = Path(td) / "t.zip"
        dump(files, zp)
        args = [str(zp)]
        if process:
            args += ["--process", str(process)]
        args += list(extra)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gg.main(args)
        return code, buf.getvalue()


import hashlib as _hl


def hashlib_sha(p):
    return _hl.sha256(Path(p).read_bytes()).hexdigest()


def record(tid, name, ok, detail=""):
    RESULTS.append((tid, name, ok, detail))


def expect(tid, name, code, out, want_code, *want_in, not_in=()):
    miss = [w for w in want_in if w not in out]
    bad = [w for w in not_in if w in out]
    ok = (code == want_code) and not miss and not bad
    detail = ""
    if not ok:
        detail = f"退出码={code}(期望{want_code}) 缺失={miss} 不应出现={bad}"
    record(tid, name, ok, detail)


def sub(b, old, new, count=0):
    t = b.decode("utf-8")
    assert old in t, f"夹具中未找到 {old!r}，测试需要更新"
    return (t.replace(old, new) if count == 0 else t.replace(old, new, count)).encode("utf-8")


def section_aperture(b, section):
    """找到某段落(Track/Text…)之后第一个 G54Dnn 选用的光圈编号。"""
    t = b.decode("utf-8")
    i = t.find(f"G04 {section} Start*")
    assert i >= 0, f"没有 {section} 段"
    return int(re.search(r"G54D(\d+)\*", t[i:]).group(1))


def set_aperture_dia(b, apno, dia):
    t = b.decode("utf-8")
    new, n = re.subn(rf"%ADD{apno}C,[\d.]+\*%", f"%ADD{apno}C,{dia}*%", t)
    assert n == 1, f"光圈 D{apno} 不是圆形或不唯一"
    return new.encode("utf-8")


# ───────────────────────── Gerber 包缺陷注入 ─────────────────────────
def test_gerber():
    base = load(BASE)

    c, o = run_guard(base)
    expect("G00", "合成基线包：无阻断、板框闭合", c, o, 0, "GB.OUTLINE.CLOSED", "60.000", not_in=("【阻断级】",))

    f = dict(base); f.pop("Gerber_BoardOutlineLayer.GKO")
    c, o = run_guard(f); expect("G01", "缺板框文件 GKO", c, o, 1, "GB.FILE.REQUIRED")

    f = dict(base); f["Gerber_TopLayer.GTL"] = sub(f["Gerber_TopLayer.GTL"], "M02*", "")
    c, o = run_guard(f); expect("G02", "铜层被截断(无 M02)", c, o, 1, "GB.END.M02")

    f = dict(base)
    t = f["Gerber_BoardOutlineLayer.GKO"].decode()
    lines = t.splitlines()
    idx = max(i for i, l in enumerate(lines) if "D01*" in l)
    del lines[idx]
    f["Gerber_BoardOutlineLayer.GKO"] = "\n".join(lines).encode()
    c, o = run_guard(f); expect("G03", "板框缺一条边(不闭合)", c, o, 1, "GB.OUTLINE.CLOSED", "未闭合")

    f = dict(base); f["Gerber_BottomSolderMaskLayer.GBS"] = b""
    c, o = run_guard(f); expect("G04", "0 字节空文件", c, o, 1, "GB.FILE.EMPTY")

    f = dict(base); f["Gerber_TopSolderMaskLayer.GTS"] = sub(f["Gerber_TopSolderMaskLayer.GTS"], "%MOMM*%", "%MOIN*%")
    c, o = run_guard(f); expect("G05", "单位不一致(mm/in 混用)", c, o, 1, "GB.UNIT.CONSIST")

    f = dict(base)
    ap = section_aperture(f["Gerber_TopLayer.GTL"], "Track")
    f["Gerber_TopLayer.GTL"] = set_aperture_dia(f["Gerber_TopLayer.GTL"], ap, 0.05)
    c, o = run_guard(f); expect("G06", "植入 0.05mm 细走线", c, o, 1, "PCB.TRACE.WIDTH_MIN", "【阻断级】")

    f = dict(base)
    for n in ("Drill_PTH_Through.DRL", "Drill_PTH_Through_Via.DRL"):
        f[n] = sub(f[n], "T01C0.30505", "T01C0.10000")
    c, o = run_guard(f); expect("G07", "植入 0.1mm 过孔(双层板极限 0.15)", c, o, 1, "PCB.DRILL.PLATED_MIN", "【阻断级】")

    c, o = run_guard(base, process=_tmp_process({"layers": 4, "copper_oz": 1, "thickness_mm": 1.6, "surface": "ENIG"}))
    expect("G08", "声明 4 层但包是 2 层", c, o, 1, "GB.LAYERS.MATCH")

    f = dict(base); f["Gerber_InnerLayer1.G1"] = base["Gerber_TopLayer.GTL"]
    c, o = run_guard(f); expect("G09", "声明 2 层但包里有内层文件", c, o, 1, "GB.LAYERS.MATCH")

    f = dict(base)
    head = "\n".join(l for l in f["Gerber_BottomLayer.GBL"].decode().splitlines() if l.startswith(("G04", "%")))
    f["Gerber_BottomLayer.GBL"] = (head + "\nM02*\n").encode()
    c, o = run_guard(f); expect("G10", "底层铜被清空(几乎为空)", c, o, 0, "GB.COPPER.EMPTY", "【中风险】")

    f = dict(base); f["Drill_PTH_Through_Via.DRL"] = sub(f["Drill_PTH_Through_Via.DRL"], "T01C0.30505", "T01C0.35000")
    c, o = run_guard(f); expect("G11", "Via 钻孔与 PTH 钻孔不一致", c, o, 1, "GB.DRILL.VIA_SUBSET")

    f = dict(base)
    ap = section_aperture(f["Gerber_TopSilkscreenLayer.GTO"], "Text")
    f["Gerber_TopSilkscreenLayer.GTO"] = set_aperture_dia(f["Gerber_TopSilkscreenLayer.GTO"], ap, 0.05)
    c, o = run_guard(f); expect("G12", "丝印文字线粗 0.05mm", c, o, 1, "PCB.SILK.WIDTH_MIN", "【阻断级】")

    f = dict(base)
    # 不依赖具体格式(旧版 2:6 / 新版 4:5)：把"前导零省略 L"改成"尾随零省略 T"
    f["Gerber_TopLayer.GTL"] = re.sub(r"%FSLA", "%FSTA", f["Gerber_TopLayer.GTL"].decode(), count=1).encode()
    c, o = run_guard(f); expect("G13", "不支持的坐标格式(FST)不得当作通过", c, o, 1, "GB.PARSE", "BLOCKED")

    c, o = run_guard(base, process=None)
    expect("G14", "不给工艺声明 → BLOCKED，不猜工艺", c, o, 2, "未提供 --process")

    c, o = run_guard(base, process=_tmp_process({"layers": 2}))
    expect("G14b", "工艺声明缺铜厚 → BLOCKED(不猜 1oz)，且不崩溃", c, o, 2, "copper_oz")

    c, o = run_guard(base, process=None, extra=["--structure-only"])
    expect("G15", "显式 --structure-only 允许跳过规范复核", c, o, 0, "未做规范复核")

    f = dict(base); f.pop("Drill_PTH_Through.DRL"); f.pop("Drill_PTH_Through_Via.DRL")
    c, o = run_guard(f); expect("G16", "缺钻孔文件(应告警)", c, o, 0, "GB.FILE.EXPECTED", "Drill_PTH_Through.DRL")

    f = dict(base); f["Drill_NPTH_Through.DRL"] = sub(f["Drill_NPTH_Through.DRL"], "M30", "")
    c, o = run_guard(f); expect("G17", "钻孔文件被截断(无 M30)", c, o, 1, "GB.END.M30")

    c, o = run_guard(base, extra=["--strict"])
    expect("G18", "严格模式：未覆盖项 → BLOCKED", c, o, 2, "待证据")

    c, o = run_guard(base)
    expect("G19", "基线：NPTH 0.25mm 触发防堵孔提醒(WARN)", c, o, 0, "PCB.NPTH.DRILL_REC", "【中风险】")

    c, o = run_guard(load(OLD))
    expect("G20", "旧版未布线真实包：告警走线缺失/底层近空，不误报阻断", c, o, 0, "GB.TRACK.NONE", "GB.COPPER.EMPTY", not_in=("【阻断级】",))

    # 丝印文字与图形必须分开：把"非文字图形"细线植入后，不应触发字符线粗阻断
    f = dict(base)
    gto = f["Gerber_TopSilkscreenLayer.GTO"].decode()
    m = re.search(r"%ADD(\d+)C,0\.0762\*%", gto)  # 元件轮廓(PolygonModel 段)用的细线光圈
    assert m, "夹具中没有 0.0762 的轮廓光圈，测试需要更新"
    f["Gerber_TopSilkscreenLayer.GTO"] = set_aperture_dia(f["Gerber_TopSilkscreenLayer.GTO"], int(m.group(1)), 0.03)
    c, o = run_guard(f)
    expect("G21", "仅元件轮廓图形变细：不属于'字符粗细'，不得误判阻断", c, o, 0, "非文字图形", not_in=("【阻断级】 PCB.SILK",))


_TMP = []


def _tmp_process(d):
    td = tempfile.mkdtemp()
    p = Path(td) / "p.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    _TMP.append(p)
    return p



# ───────────────────────── BOM / 坐标 缺陷注入 ─────────────────────────
def _norm_texts():
    """把真实原生文件规范化，返回 (bom_text, cpl_text)。"""
    with tempfile.TemporaryDirectory() as td:
        outs = []
        for src, kind in ((NBOM, "bom"), (NCPL, "cpl")):
            dst = Path(td) / f"{kind}.csv"
            bg.normalize(src, dst, kind)
            outs.append(dst.read_text(encoding="utf-8"))
    return outs[0], outs[1]


def run_bc(bom=None, cpl=None, extra=(), suffix=".csv"):
    with tempfile.TemporaryDirectory() as td:
        args = ["check"]
        for k, txt in (("--bom", bom), ("--cpl", cpl)):
            if txt is not None:
                f = Path(td) / (k[2:] + suffix)
                f.write_text(txt, encoding="utf-8", newline="")
                args += [k, str(f)]
        args += list(extra)
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = bg.main(args)
        return code, buf.getvalue() + err.getvalue()


def _rewrite(txt, fn):
    """用 csv 解析后对 (header, rows) 做变换再写回，避免手工拼接出错。"""
    import csv as _csv
    rows = list(_csv.reader(io.StringIO(txt)))
    rows = fn(rows)
    o = io.StringIO()
    _csv.writer(o, lineterminator="\n").writerows(rows)
    return o.getvalue()


def test_bomcpl():
    bom, cpl = _norm_texts()
    BOARD = ["--board-size", "60x40"]
    c, o = run_bc(bom, cpl, BOARD)
    expect("K00", "基线(规范化后的原生形态BOM+CPL)：无阻断、位号集合一致", c, o, 0, "X.BOM_CPL.SET", "20 个", not_in=("【阻断级】",))

    # 原生(UTF-16 + 制表符 + mm 后缀)直接检查：不阻断，但提示转换
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = bg.main(["check", "--bom", str(NBOM), "--cpl", str(NCPL), *BOARD])
    expect("K01", "真实原生文件：不阻断，提示先规范化", code, buf.getvalue(), 0, "FILE.ENC.NATIVE", "utf-16")

    def drop_col(name):
        def f(rows):
            i = [h.lower() for h in rows[0]].index(name.lower())
            return [[c for j, c in enumerate(r) if j != i] for r in rows]
        return f

    c, o = run_bc(_rewrite(bom, drop_col("Footprint")), None); expect("K02", "BOM 缺 Footprint 列", c, o, 1, "BOM.COL.REQUIRED")
    c, o = run_bc(None, _rewrite(cpl, drop_col("Rotation"))); expect("K03", "CPL 缺 Rotation 列", c, o, 1, "CPL.COL.REQUIRED")

    def set_cell(rowi, col, val):
        def f(rows):
            ci = [h.lower() for h in rows[0]].index(col.lower())
            rows[rowi][ci] = val
            return rows
        return f

    # rows[0]=表头；rows[1]=BUZZER1；rows[2]=C1,C2,C3；rows[3]=C4..C8
    c, o = run_bc(_rewrite(bom, set_cell(2, "Designator", "C1，C2，C3")), None)
    expect("K04", "中文逗号分隔位号", c, o, 1, "BOM.DES.SEP")
    c, o = run_bc(_rewrite(bom, set_cell(2, "Designator", "C1,c1,C3")), None)
    expect("K05", "C1 与 c1 大小写冲突", c, o, 1, "BOM.DES.CASE_DUP")
    c, o = run_bc(_rewrite(bom, set_cell(2, "Quantity", "2")), None)
    expect("K06", "Quantity 与位号数不一致", c, o, 1, "BOM.QTY.MATCH")
    c, o = run_bc(_rewrite(bom, set_cell(2, "Designator", "C#1,C2,C3")), None)
    expect("K07", "位号含 # 禁用字符", c, o, 1, "BOM.DES.CHARS")
    c, o = run_bc(_rewrite(bom, set_cell(2, "Designator", "电容1,C2,C3")), None)
    expect("K08", "中文位号", c, o, 1, "BOM.DES.CHARS")
    c, o = run_bc(_rewrite(bom, set_cell(2, "Designator", "C" + "1" * 70 + ",C2,C3")), None)
    expect("K09", "位号超过 64 字符", c, o, 1, "BOM.DES.LEN")
    c, o = run_bc(_rewrite(bom, set_cell(2, "Designator", "C3-1")), None)
    expect("K10", "范围起始大于结束 (C3-1)", c, o, 1, "BOM.DES.RANGE")
    c, o = run_bc(_rewrite(bom, lambda r: set_cell(2, "Designator", "C1-3")(set_cell(2, "Quantity", "3")(r))), None)
    expect("K11", "合法范围写法 C1-3 展开后数量一致(不得误报)", c, o, 0, not_in=("BOM.DES.RANGE", "BOM.QTY.MATCH", "【阻断级】"))
    c, o = run_bc(_rewrite(bom, set_cell(2, "Comment", "")), None)
    expect("K12", "Comment 为空", c, o, 1, "BOM.EMPTY.FIELD")
    c, o = run_bc(_rewrite(bom, lambda r: r + [["", "", "合计", "", ""] + [""] * (len(r[0]) - 5)]), None)
    expect("K13", "BOM 含合计行(应告警，且不被当器件)", c, o, 0, "BOM.TOTAL_ROW", not_in=("【阻断级】",))
    c, o = run_bc(_rewrite(bom, set_cell(2, "Supplier Part", "X123")), None)
    expect("K14", "C 编号格式错误(告警)", c, o, 0, "BOM.LCSC.FORMAT", "X123")
    c, o = run_bc(_rewrite(bom, set_cell(2, "Supplier Part", "")), None)
    expect("K15", "缺 C 编号(告警)", c, o, 0, "BOM.LCSC.MISSING")
    c, o = run_bc(_rewrite(bom, set_cell(2, "Comment", "100")), None)
    expect("K16", "Comment 只有数字 100 有歧义(告警)", c, o, 0, "BOM.COMMENT.AMBIG")

    # ── 坐标 ──
    c, o = run_bc(None, _rewrite(cpl, lambda r: [[h + "(mm)" if h in ("Mid X", "Mid Y") else h for h in r[0]]] + r[1:]))
    expect("K17", "CPL 表头带单位 Mid X(mm)", c, o, 1, "CPL.HEADER.UNIT")
    c, o = run_bc(None, _rewrite(cpl, set_cell(1, "Layer", "Middle"))); expect("K18", "Layer 非 T/B", c, o, 1, "CPL.LAYER")
    c, o = run_bc(None, _rewrite(cpl, set_cell(1, "Rotation", "86.4571"))); expect("K19", "旋转角 4 位小数", c, o, 1, "CPL.ROT.NUMERIC")
    c, o = run_bc(None, _rewrite(cpl, set_cell(1, "Rotation", "九十"))); expect("K20", "旋转角非数字", c, o, 1, "CPL.ROT.NUMERIC")
    c, o = run_bc(None, _rewrite(cpl, set_cell(1, "Mid X", "500")), BOARD)
    expect("K21", "器件坐标超出板尺寸(极差>板)", c, o, 1, "CPL.RANGE.BOARD")
    c, o = run_bc(None, _rewrite(cpl, set_cell(1, "Mid X", "abc"))); expect("K22", "坐标不是数字", c, o, 1, "CPL.UNIT.CONSIST")
    c, o = run_bc(None, _rewrite(cpl, lambda r: set_cell(1, "Mid X", "10mil")(r)))
    expect("K23", "mm 与 mil 混用", c, o, 1, "CPL.UNIT.CONSIST", "混用")
    c, o = run_bc(None, _rewrite(cpl, lambda r: r + [r[1]])); expect("K24", "CPL 位号重复", c, o, 1, "CPL.DES.DUP")
    c, o = run_bc(None, cpl, ["--board-size", "50x30"]); expect("K25", "板尺寸给小了 → 极差超板", c, o, 1, "CPL.RANGE.BOARD")
    c, o = run_bc(None, cpl); expect("K26", "未给板尺寸 → 告警未检查极差(不静默通过)", c, o, 0, "未提供板尺寸")

    # ── 交叉 ──
    c, o = run_bc(_rewrite(bom, lambda r: r + [["99", "1", "X", "U99", "SOT-23"] + [""] * (len(r[0]) - 5)]), cpl, BOARD)
    expect("K27", "BOM 多出 U99，坐标里没有", c, o, 1, "X.BOM_CPL.SET", "U99")
    c, o = run_bc(bom, _rewrite(cpl, lambda r: r[:-1]), BOARD)
    expect("K28", "坐标缺一个位号", c, o, 1, "X.BOM_CPL.SET")

    # ── 格式 ──
    with tempfile.TemporaryDirectory() as td:
        x = Path(td) / "a.xlsx"; x.write_bytes(b"PK\x03\x04")
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = bg.main(["check", "--bom", str(x)])
        record("K29", "xlsx 不解析 → BLOCKED(2)，不当作通过", code == 2 and "xls" in err.getvalue())
    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "o.csv"; info = bg.normalize(NCPL, dst, "cpl")
        t = dst.read_text(encoding="utf-8")
        ok = "mm" not in t.split("\n")[1] and "\t" not in t and t.startswith("Designator,") and info["to"] == "utf-8/COMMA"
        record("K30", "normalize：UTF-8+逗号、坐标去 mm 后缀、无制表符", ok)
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = bg.main(["normalize", "--cpl", str(NCPL), "--out-dir", td])
        code2 = None
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code2 = bg.main(["normalize", "--cpl", str(NCPL), "--out-dir", td])
        record("K31", "normalize 拒绝覆盖已存在文件", code == 0 and code2 == 2)
    # mil 文件规范化后必须保留单位后缀
    mil = "Designator,Mid X,Mid Y,Layer,Rotation\nR1,1000mil,2000mil,T,0\nR2,1500mil,2000mil,T,90\n"
    with tempfile.TemporaryDirectory() as td:
        a = Path(td) / "m.csv"; a.write_text(mil, encoding="utf-8"); b = Path(td) / "m.out.csv"
        bg.normalize(a, b, "cpl")
        record("K32", "mil 文件规范化后保留 mil 后缀(官方要求)", "mil" in b.read_text(encoding="utf-8"))

# ───────────────────────── spec_check 单元 ─────────────────────────
def ev(process, meas, smt=False, partial=True):
    sets = [(sc.load_json(sc.DATA / "jlc-pcb-capabilities.json"), "pcb")]
    if smt:
        sets.append((sc.load_json(sc.DATA / "jlc-smt-capabilities.json"), "smt"))
    res, summ, code = sc.evaluate(process, meas, sets, partial=partial)
    return {r["rule_id"]: r for r in res}, summ, code


P2 = {"layers": 2, "copper_oz": 1, "thickness_mm": 1.6, "surface": "ENIG", "edge": "routed", "mask_color": "green"}


def test_spec():
    st = lambda rid, process, meas, **k: ev(process, meas, **k)[0][rid]["status"]  # noqa: E731

    record("S01", "线宽 0.098 < 极限 → BLOCK", st("PCB.TRACE.WIDTH_MIN", P2, {"min_track_width": 0.098}) == "BLOCK")
    record("S02", "线宽 0.10(常用值) → WARN 不是 BLOCK", st("PCB.TRACE.WIDTH_MIN", P2, {"min_track_width": 0.10}) == "WARN")
    record("S03", "线宽 0.127(达到建议) → PASS", st("PCB.TRACE.WIDTH_MIN", P2, {"min_track_width": 0.127}) == "PASS")
    P4 = {**P2, "layers": 4}
    record("S04", "多层 1oz 3.5mil(0.0889) → 不 BLOCK", st("PCB.TRACE.WIDTH_MIN", P4, {"min_track_width": 0.0889}) == "WARN")
    record("S05", "多层 1oz 0.08 → BLOCK", st("PCB.TRACE.WIDTH_MIN", P4, {"min_track_width": 0.08}) == "BLOCK")
    P1 = {**P2, "layers": 1}
    record("S06", "单层 0.2mm 孔 < 单层极限 0.3 → BLOCK", st("PCB.DRILL.PLATED_MIN", P1, {"min_plated_drill": 0.2}) == "BLOCK")
    record("S07", "双层 0.2mm 孔 → 不 BLOCK(层别正确选取)", st("PCB.DRILL.PLATED_MIN", P2, {"min_plated_drill": 0.2}) != "BLOCK")
    r = ev(P2, {"min_plated_drill": 0.15})[0]["PCB.DRILL.PLATED_MIN"]
    record("S08", "0.15mm 孔 → 命中官方'非常规费用高'标记", any("COST_TRIGGER" in f for f in r["flags"]))
    record("S09", "板厚 1.5 不在常规集合 → BLOCK", st("PCB.BOARD.THICKNESS", {**P2, "thickness_mm": 1.5}, {}) == "BLOCK")
    record("S10", "板厚 1.6 → PASS", st("PCB.BOARD.THICKNESS", P2, {}) == "PASS")
    P6 = {**P2, "layers": 6, "surface": "HASL_LEADFREE"}
    record("S11", "6 层 + 喷锡 → BLOCK", st("PCB.FINISH.HASL_NOT_FOR_6L", P6, {}) == "BLOCK")
    record("S12", "6 层 + 沉金 → PASS", st("PCB.FINISH.HASL_NOT_FOR_6L", {**P6, "surface": "ENIG"}, {}) == "PASS")
    record("S13", "V割距边 0.3 < 0.4 → BLOCK", st("PCB.EDGE.VCUT", {**P2, "edge": "vcut"}, {"min_copper_to_edge": 0.3}) == "BLOCK")
    rs = ev({**P2, "edge": "routed"}, {"min_copper_to_edge": 0.3})[0]
    record("S14", "锣边 0.3 ≥ 0.2 → PASS，且不触发V割规则", rs["PCB.EDGE.ROUTED"]["status"] == "PASS" and "PCB.EDGE.VCUT" not in rs)
    record("S15", "黑色阻焊桥 0.11 < 0.13 → WARN", st("PCB.MASK.BRIDGE_1OZ_DARK", {**P2, "mask_color": "black"}, {"min_mask_bridge": 0.11}) == "WARN")
    record("S16", "绿色阻焊桥 0.11 ≥ 0.10 → PASS", st("PCB.MASK.BRIDGE_1OZ_COLOR", P2, {"min_mask_bridge": 0.11}) == "PASS")
    _, _, c1 = ev(P2, {"min_track_width": 0.2}, partial=False)
    _, _, c2 = ev(P2, {"min_track_width": 0.2}, partial=True)
    record("S17", "严格模式缺证据→2；局部模式→0", c1 == 2 and c2 == 0)
    rr, _, _ = ev({**P2}, {})
    record("S18", "不声明 smt 时 SMT 规则不参与", not any(k.startswith("SMT.") for k in rr))
    rr, _, _ = ev({**P2, "smt": "standard"}, {"mark_count": 2}, smt=True)
    record("S19", "标准型 SMT：Mark 点只有 2 个 → BLOCK", rr["SMT.MARK.COUNT"]["status"] == "BLOCK")
    record("S20", "规范库自检通过(来源/原文片段齐全)", not (sc.validate_data(sc.load_json(sc.DATA / "jlc-pcb-capabilities.json"), "pcb")
                                                          + sc.validate_data(sc.load_json(sc.DATA / "jlc-smt-capabilities.json"), "smt")))
    bad = {"sources": {"X": {"tier": "T3", "url": "u", "fetched_at": "d"}},
           "rules": [{"id": "A", "name": "n", "key": "k", "op": ">=", "limit": {"value": 1, "src": "X", "quote": ""}},
                     {"id": "B", "name": "n", "key": "k", "op": ">=", "limit": {"value": 1, "src": "NOPE", "quote": "q"}}]}
    pr = " ".join(sc.validate_data(bad))
    record("S21", "规范库自检能拒绝：T3 来源 / 空原文片段 / 未登记来源", "T3" in pr and "quote" in pr and "未在 sources" in pr)
    for tid, proc, name in (
        ("S22", {"copper_oz": 1}, "process 缺 layers → 拒绝(不猜工艺)"),
        ("S23", {"layers": 2}, "process 缺 copper_oz → 拒绝(不再默认 1oz)"),
        ("S24", {"layers": 2, "copper_oz": None}, "copper_oz=null(模板未填) → 拒绝"),
    ):
        try:
            sc.evaluate(proc, {}, [(sc.load_json(sc.DATA / "jlc-pcb-capabilities.json"), "pcb")])
            record(tid, name, False)
        except ValueError:
            record(tid, name, True)



# ───────────────────────── 规则门禁(设计规则配置 vs 工艺) ─────────────────────────
def _rc(cfg, process):
    res, summ, meas, notes, code = rc.run(cfg, process)
    return {r["rule_id"]: r["status"] for r in res}, code, meas, notes, summ


def test_rules_check():
    import copy
    presets = json.loads((ROOT / "data" / "rule-presets" / "_all_raw.json").read_text(encoding="utf-8"))
    P_DBL = {"layers": 2, "copper_oz": 1, "thickness_mm": 1.6, "surface": "ENIG", "edge": "routed", "mask_color": "green"}
    two = presets["JLCPCB Capability(Two Layers Board)"]
    st, code, meas, notes, summ = _rc(two, P_DBL)
    record("R01", "官方双层预设对照双层 1oz：全部 PASS、无阻断", code == 0 and set(st.values()) == {"PASS"}, str(st))
    record("R02", "汇总口径自洽：已评估数 == 适用数", summ["evaluated"] == summ["total_applicable"], str(summ))
    for nm, lay in (("JLCPCB Capability(Single Layer Board)", 1), ("JLCPCB Capability(Multiple Layers Board)", 4)):
        s2, c2, *_ = _rc(presets[nm], {**P_DBL, "layers": lay})
        record(f"R03-{lay}", f"官方预设 {nm[-20:-1]} 对照其层别：无阻断", c2 == 0, str(s2))

    def mut(path, val):
        c = copy.deepcopy(two)
        o = c
        for k in path[:-1]:
            o = o[k]
        o[path[-1]] = val
        return c

    tr = ["Physics", "Track", "copperThickness1oz", "form", "strokeWidthMin"]
    st, code, *_ = _rc(mut(tr, 0.05), P_DBL)
    record("R04", "规则线宽下限 0.05mm 低于工艺极限 → BLOCK", code == 1 and st["PCB.TRACE.WIDTH_MIN"] == "BLOCK")
    st, code, *_ = _rc(mut(tr, 0.11), P_DBL)
    record("R05", "规则线宽下限 0.11mm(介于极限与建议) → WARN 不阻断", code == 0 and st["PCB.TRACE.WIDTH_MIN"] == "WARN")
    c = copy.deepcopy(two); c["Spacing"]["Safe Spacing"]["copperThickness1oz"]["table"][0][0] = 0.05
    st, code, *_ = _rc(c, P_DBL)
    record("R06", "规则线-线间距 0.05mm → BLOCK", code == 1 and st["PCB.TRACE.SPACE_MIN"] == "BLOCK")
    c = copy.deepcopy(two); c["Spacing"]["Safe Spacing"]["copperThickness1oz"]["table"][1][0] = 0.05
    st, code, *_ = _rc(c, P_DBL)
    record("R07", "规则焊盘-走线间距 0.05mm → BLOCK", code == 1 and st["PCB.PAD.TO_TRACK"] == "BLOCK")
    c = copy.deepcopy(two); c["Spacing"]["Safe Spacing"]["copperThickness1oz"]["table"][11][0] = 0.1
    st, code, *_ = _rc(c, P_DBL)
    record("R08", "规则走线-板框间距 0.1mm 低于锣边 0.2 → BLOCK", code == 1 and st["PCB.EDGE.ROUTED"] == "BLOCK")
    st, code, *_ = _rc(mut(["Physics", "Via Size", "viaSize", "form", "viaInnerdiameterMin"], 0.1), P_DBL)
    record("R09", "规则最小过孔内径 0.1mm 低于双层极限 0.15 → BLOCK", code == 1 and st["PCB.DRILL.PLATED_MIN"] == "BLOCK")
    st, code, *_ = _rc(mut(["Physics", "Via Size", "viaSize", "form", "viaOuterdiameterMin"], 0.2), P_DBL)
    record("R10", "规则最小过孔外径 0.2mm 低于极限 0.25 → BLOCK", code == 1 and st["PCB.VIA.OUTER_MIN"] == "BLOCK")
    st, code, *_ = _rc(mut(["Spacing", "Other Spacing", "otherClearance", "form", "hole2Hole"], 0.1), P_DBL)
    record("R11", "规则孔到孔 0.1mm 低于 0.2 → BLOCK", code == 1 and st["PCB.VIA.HOLE_EDGE_GAP"] == "BLOCK")
    c = copy.deepcopy(two); f = c["Expansion"]["Solder Mask Expansion"]["solderMaskExpansion"]["form"]
    f["padToplayerExpansion"] = -0.01
    st, code, *_ = _rc(c, P_DBL)
    record("R12", "规则阻焊单边扩展为负 → BLOCK", code == 1 and st["PCB.MASK.EXPANSION_MIN"] == "BLOCK")
    c = copy.deepcopy(two); del c["Physics"]["Track"]["copperThickness1oz"]
    st, code, meas, notes, _ = _rc(c, P_DBL)
    record("R13", "规则里缺 1oz 线宽段 → 不猜：不出线宽结论并给出说明", "PCB.TRACE.WIDTH_MIN" not in st and any("线宽" in n for n in notes))
    st, code, meas, notes, _ = _rc(two, {**P_DBL, "copper_oz": 2})
    record("R14", "2oz 取 2oz 段规则：线宽下限 0.203 达到 2oz 建议值", code == 0 and st["PCB.TRACE.WIDTH_MIN"] == "PASS", str(st))
    buf, err = io.StringIO(), io.StringIO()
    with tempfile.TemporaryDirectory() as td:
        pf = Path(td) / "p.json"; pf.write_text(json.dumps({"layers": 2, "copper_oz": None}), encoding="utf-8")
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            code = rc.main(["--preset", "JLCPCB Capability(Two Layers Board)", "--process", str(pf)])
    record("R15", "copper_oz 未声明 → BLOCKED(2)，不猜工艺", code == 2 and "copper_oz" in err.getvalue())
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        code = rc.main(["--preset", "不存在的预设", "--process", str(PROC)])
    record("R16", "预设名不存在 → BLOCKED(2) 并列出可选项", code == 2)
    # 两种输入形态：{name,config} 与直接 config
    with tempfile.TemporaryDirectory() as td:
        f1, f2 = Path(td) / "a.json", Path(td) / "b.json"
        f1.write_text(json.dumps({"name": "x", "config": two}), encoding="utf-8")
        f2.write_text(json.dumps(two), encoding="utf-8")
        ok = True
        for f in (f1, f2):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                ok = ok and rc.main(["--config", str(f), "--process", str(PROC)]) == 0
    record("R17", "--config 同时支持 {name,config} 与裸 config 两种形态", ok)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cdump = rc.main(["--dump-js"])
    record("R19", "--dump-js 不需要工艺声明，输出可交给 bridge 执行的单句 JS", cdump == 0 and "getCurrentRuleConfiguration" in buf.getvalue())
    # N/A：板上没有某类对象
    rr, _, _ = ev(P2, {"min_th_annular": sc.NONE_PRESENT, "min_track_width": 0.2})
    record("R18", "实测值 NONE_PRESENT → N/A(板上无此类对象)，不当缺证据", rr["PCB.TH.ANNULAR_MIN"]["status"] == "N/A")


# ───────────────────────── workflow / release / drift ─────────────────────────
def _cap(fn, args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = fn(args)
    return code, out.getvalue() + err.getvalue()


def _proj(td, process=None, gerber=BASE):
    """建一个工程目录：workflow + process + 基线 Gerber + 规范化 BOM/CPL。"""
    d = Path(td) / "proj"; d.mkdir()
    _cap(wfm.main, ["init", str(d), "--name", "demo", "--apply"])
    (d / "process.json").write_text(json.dumps(process or {"layers": 2, "copper_oz": 1, "thickness_mm": 1.6,
                                                         "surface": "ENIG", "edge": "routed", "mask_color": "green"}), encoding="utf-8")
    import shutil as _sh
    _sh.copy2(gerber, d / "gerber.zip")
    bom, cpl = _norm_texts()
    (d / "bom.csv").write_text(bom, encoding="utf-8", newline=""); (d / "cpl.csv").write_text(cpl, encoding="utf-8", newline="")
    return d


def _confirm_all(d, bind, upto=5):
    for i, (g, _n) in enumerate(wfm.GATES[:upto]):
        c, o = _cap(wfm.main, ["confirm", str(d), "--gate", g, "--choice", "1", "--user-reply", f"{i + 1} 通过", *sum([["--bind", b] for b in bind], [])])
        if c != 0:
            return c, o
    return 0, ""


def test_workflow_release_drift():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "p"; d.mkdir()
        c, o = _cap(wfm.main, ["init", str(d)])
        record("W01", "init 默认只预览，不写文件", c == 0 and not (d / "workflow.json").exists())
        c, o = _cap(wfm.main, ["init", str(d), "--apply"])
        record("W02", "init --apply 创建 workflow.json 与 process.json(模板 null)", c == 0 and (d / "workflow.json").exists()
               and json.loads((d / "process.json").read_text(encoding="utf-8"))["layers"] is None)
        c, o = _cap(wfm.main, ["init", str(d), "--apply"])
        record("W03", "init 拒绝覆盖已有 workflow.json", c == 2)
        c, o = _cap(wfm.main, ["status", str(d)])
        record("W04", "未填工艺声明 → status 明确提示缺 layers/copper_oz", c == 0 and "layers" in o and "copper_oz" in o)
    with tempfile.TemporaryDirectory() as td:
        d = _proj(td)
        c, o = _cap(wfm.main, ["confirm", str(d), "--gate", "G1", "--choice", "1", "--user-reply", "  ", "--bind", "process.json"])
        record("W05", "用户原话为空 → BLOCKED（Agent 不得代答）", c == 2)
        c, o = _cap(wfm.main, ["confirm", str(d), "--gate", "G2", "--choice", "1", "--user-reply", "1", "--bind", "process.json"])
        record("W06", "越序确认 G2(G1 未确认) → BLOCKED", c == 2 and "前序" in o)
        c, o = _cap(wfm.main, ["confirm", str(d), "--gate", "G1", "--choice", "1", "--user-reply", "1"])
        record("W07", "通过(1)但不绑定文件 → BLOCKED", c == 2 and "--bind" in o)
        c, o = _cap(wfm.main, ["confirm", str(d), "--gate", "G1", "--choice", "2", "--user-reply", "2 改一下"])
        _c2, so = _cap(wfm.main, ["status", str(d)])
        record("W08", "选 2(修改后重审)被记录，但 G1 仍是 PENDING", c == 0 and "G1 原理图" in so and "PENDING" in so.split("G1")[1].split("\n")[0])
        c, o = _cap(wfm.main, ["confirm", str(d), "--gate", "G9", "--choice", "1", "--user-reply", "1", "--bind", "process.json"])
        record("W09", "未知门禁 → BLOCKED", c == 2)
        c, o = _cap(wfm.main, ["confirm", str(d), "--gate", "G1", "--choice", "1", "--user-reply", "1", "--bind", "nope.txt"])
        record("W10", "绑定的文件不存在 → BLOCKED", c == 2)
        _confirm_all(d, ["process.json"], upto=3)
        (d / "process.json").write_text(json.dumps({"layers": 4, "copper_oz": 1}), encoding="utf-8")
        _c, so = _cap(wfm.main, ["status", str(d)])
        lines = {l.split()[0]: l for l in so.splitlines() if l.strip().startswith("G")}
        record("W11", "被绑定文件变化 → G1 STALE，后续 G2/G3 连带 STALE", all("STALE" in lines[g] for g in ("G1", "G2", "G3")), so)
        c, o = _cap(wfm.main, ["plan", "--task", "rm -rf"]); record("W12", "plan 拒绝非白名单任务", c == 2)
        c, o = _cap(wfm.main, ["run", "--task", "bash"]); record("W13", "run 拒绝非白名单任务(无 shell)", c == 2)
        c, o = _cap(wfm.main, ["plan", "--task", "gerber.guard", "--", "x.zip"]); record("W14", "plan 只打印命令不执行", c == 0 and "gerber_guard.py" in o and "x.zip" in o)
        c, o = _cap(wfm.main, ["run", "--task", "spec.validate"]); record("W15", "run 调用白名单脚本并传播退出码(规范库自检=0)", c == 0)
        c, o = _cap(wfm.main, ["run", "--task", "gerber.guard", "--", str(BASE)]); record("W16", "run 传播子脚本的非 0 退出码(缺工艺声明→2)", c == 2)

    # release
    with tempfile.TemporaryDirectory() as td:
        d = _proj(td)
        c, o = _cap(rel.main, [str(d), "--version", "V1.0", "--gerber", "gerber.zip"])
        record("RL01", "门禁未确认 → 拒绝封存", c == 2 and "门禁未全部确认" in o)
        _confirm_all(d, ["process.json", "gerber.zip"], upto=4)
        _cap(wfm.main, ["confirm", str(d), "--gate", "G5", "--choice", "1", "--user-reply", "5 通过", "--bind", "process.json"])
        c, o = _cap(rel.main, [str(d), "--version", "V1.0", "--gerber", "gerber.zip"])
        record("RL02", "G5 没有绑定 Gerber 文件 → 拒绝（封存的必须是确认过的版本）", c == 2 and "没有绑定" in o)
    with tempfile.TemporaryDirectory() as td:
        d = _proj(td)
        _confirm_all(d, ["process.json", "gerber.zip", "bom.csv", "cpl.csv"])
        c, o = _cap(rel.main, [str(d), "--version", "V1.0", "--gerber", "gerber.zip", "--bom", "bom.csv"])
        record("RL03", "只给 BOM 不给坐标 → 拒绝（需成对交叉核对）", c == 2 and "成对" in o)
        c, o = _cap(rel.main, [str(d), "--version", "V1.0", "--gerber", "gerber.zip", "--bom", "bom.csv", "--cpl", "cpl.csv"])
        record("RL04", "完整齐备：默认预览，不写发布目录", c == 0 and "预览" in o and not (d / "release").exists())
        c, o = _cap(rel.main, [str(d), "--version", "V1.0", "--gerber", "gerber.zip", "--bom", "bom.csv", "--cpl", "cpl.csv", "--apply"])
        r = d / "release" / "V1.0"
        ok = c == 0 and (r / "manifest.json").exists() and (r / "README.txt").exists() and (r / "gerber.zip").exists()
        record("RL05", "--apply：封存成功，含 manifest/README/文件/复核报告", ok, o)
        if ok:
            man = json.loads((r / "manifest.json").read_text(encoding="utf-8"))
            hashes_ok = all(hashlib_sha(r / n) == v["sha256"] for n, v in man["files"].items())
            record("RL06", "manifest 的 sha256 与封存文件一致，含 5 道门禁留痕，声明未上传/未下单",
                   hashes_ok and len(man["gates"]) == 5 and "未上传" in man["statement"] and "未下单" in man["statement"])
            record("RL07", "复核报告随包保存", (r / "reports" / "gerber_guard.txt").exists() and (r / "reports" / "bom_cpl_guard.txt").exists())
        c, o = _cap(rel.main, [str(d), "--version", "V1.0", "--gerber", "gerber.zip", "--bom", "bom.csv", "--cpl", "cpl.csv", "--apply"])
        record("RL08", "同版本号再封存 → 拒绝覆盖", c == 2 and "拒绝覆盖" in o)
        c, o = _cap(rel.main, [str(d), "--version", "bad version!", "--gerber", "gerber.zip"])
        record("RL09", "非法版本号 → 拒绝", c == 2)
        (d / "gerber.zip").write_bytes((d / "gerber.zip").read_bytes() + b"x")
        c, o = _cap(rel.main, [str(d), "--version", "V1.1", "--gerber", "gerber.zip", "--bom", "bom.csv", "--cpl", "cpl.csv"])
        record("RL10", "确认之后 Gerber 被改动 → 拒绝（门禁连带 STALE）", c == 2 and ("STALE" in o or "修改过" in o))
    with tempfile.TemporaryDirectory() as td:
        files = load(BASE); files.pop("Gerber_BoardOutlineLayer.GKO")
        bad = Path(td) / "bad.zip"; dump(files, bad)
        d = _proj(td, gerber=bad)
        _confirm_all(d, ["process.json", "gerber.zip", "bom.csv", "cpl.csv"])
        c, o = _cap(rel.main, [str(d), "--version", "V1.0", "--gerber", "gerber.zip", "--bom", "bom.csv", "--cpl", "cpl.csv", "--apply"])
        record("RL11", "用户已确认但 Gerber 缺板框 → 封存时重新复核，仍拒绝", c != 0 and not (d / "release").exists())
    with tempfile.TemporaryDirectory() as td:
        d = _proj(td)
        outside = Path(td) / "outside.zip"; outside.write_bytes(b"x")
        _confirm_all(d, ["process.json", "gerber.zip"])
        c, o = _cap(rel.main, [str(d), "--version", "V1.0", "--gerber", str(outside)])
        record("RL12", "文件不在工程目录内 → 拒绝(无法被确认绑定)", c == 2 and "不在工程目录内" in o)
    with tempfile.TemporaryDirectory() as td:
        d = _proj(td, process={"layers": 2, "copper_oz": None})
        c, o = _cap(rel.main, [str(d), "--version", "V1.0", "--gerber", "gerber.zip"])
        record("RL13", "工艺声明 copper_oz=null → 拒绝(不猜工艺)", c == 2 and "copper_oz" in o)

    # drift
    by = sd.collect()
    pages = {}
    for (url, tier), items in by.items():
        if url.startswith("http") and tier in ("T1", "T2"):
            pages[url] = "<html><body>" + " ".join(q for _r, _k, q in items) + "</body></html>"
    def boom(u):
        raise RuntimeError("offline")
    out = sd.run(pages, fetcher=boom); cnt, code = sd.summarize(out)
    record("D01", "页面包含全部原文片段 → 无漂移，退出 0", code == 0 and cnt.get("OK", 0) > 0 and not cnt.get("DRIFT_SUSPECT"), str(cnt))
    items = [("X.RULE", "limit", "最小线宽 0.1234mm 共 5 档")]
    ok_ = sd.check_source("u", items, "<p>最小线宽 0.1234mm 共 5 档</p>")[0][2]
    drift = sd.check_source("u", items, "<p>最小线宽 0.2468mm 共 5 档</p>")[0][2]
    shell = sd.check_source("u", items, "<p>nothing here</p>")[0][2]
    record("D02", "单条规则：数值在→OK；数值被改(5 还在、0.1234 没了)→DRIFT_SUSPECT；全不在→UNREADABLE",
           (ok_, drift, shell) == ("OK", "DRIFT_SUSPECT", "UNREADABLE"), str((ok_, drift, shell)))
    _o, code2 = sd.summarize([("u", "FETCHED", [("X", "limit", "DRIFT_SUSPECT", ["0.1234"])])])
    record("D02b", "存在 DRIFT_SUSPECT → 退出码 1（提示人工核对，不自动改库）", code2 == 1)
    p3 = {u: "<html><body>JS rendering shell</body></html>" for u in pages}
    out = sd.run(p3, fetcher=boom); cnt, code = sd.summarize(out)
    record("D03", "页面是空壳(JS渲染) → UNREADABLE，退出 2，不得报'无漂移'", code == 2 and cnt.get("UNREADABLE", 0) > 0, str(cnt))
    out = sd.run({}, fetcher=boom); cnt, code = sd.summarize(out)
    record("D04", "抓取失败 → UNREACHABLE，退出 2", code == 2 and cnt.get("UNREACHABLE", 0) > 0, str(cnt))
    record("D05", "数值归一化：0.10 与 0.1 视为同一数", "0.1" in sd.number_set("线宽 0.10mm") and "0.1" in sd.number_set("0.1mm"))
    record("D06", "HTML 标签/脚本被剔除，仅比对可见文本", "secret" not in sd.html_to_text("<script>var a='secret'</script><p>0.1mm</p>"))
    record("D07", "T0 来源(本机API)不联网，不出现在检测清单里", all(u.startswith("http") for u, _s, _r in sd.run(pages, fetcher=boom)))


# ───────────────────────── 防泄露 / 夹具可复现 / 真实文件回归(可选) ─────────────────────────
# Use generic leak signatures: never include real-person names, private paths or IDs in public tests.
def test_privacy_and_fixtures():
    sys.path.insert(0, str(ROOT / "tools"))
    import privacy_scan
    hits = privacy_scan.scan_tree(ROOT)
    record("B08", "防泄露：全包（含 HTML / ZIP / UTF-16 CSV）无常见密钥、邮箱、内网地址与个人绝对路径", not hits,
           "; ".join(f"{name}: {rule}" for name, rule in hits[:6]))
    # 夹具必须由生成器逐字节复现
    sys.path.insert(0, str(ROOT / "tools"))
    import make_fixtures as mf
    bad = [n for n, fn in mf.FIXTURES.items() if not (FIX / n).exists() or (FIX / n).read_bytes() != fn()]
    record("B09", "夹具可复现：磁盘文件与 tools/make_fixtures.py 生成结果逐字节一致", not bad, str(bad))
    # 合成夹具必须自称合成（防止有人把真实文件塞回 fixtures）
    man = json.loads((FIX / "MANIFEST.json").read_text(encoding="utf-8"))
    extra = sorted(p.name for p in FIX.iterdir() if p.name != "MANIFEST.json" and p.name not in man["files"])
    record("B10", "fixtures 目录里没有清单之外的文件", not extra, str(extra))


def test_real_fixtures():
    d = os.environ.get("JLCEDA_REAL_FIXTURES")
    if not d:
        return
    d = Path(d)
    g = lambda n: (d / n) if (d / n).exists() else None  # noqa: E731
    proc = g("process_2layer_1oz.json") or PROC
    new, old, rb, rc_ = g("real_new_export.zip"), g("real_old_unrouted.zip"), g("real_bom_utf16.csv"), g("real_cpl_utf16.csv")
    if new:
        c, o = run_guard(load(new), process=proc)
        record("X01", "[真实] 新导出包：无阻断，板框闭合", c == 0 and "GB.OUTLINE.CLOSED" in o and "【阻断级】" not in o, o[-200:])
        f = dict(load(new)); f.pop("Gerber_BoardOutlineLayer.GKO")
        c, o = run_guard(f, process=proc)
        record("X02", "[真实] 删板框 → 阻断（缺陷注入对真实文件同样有效）", c == 1 and "GB.FILE.REQUIRED" in o)
    if old:
        c, o = run_guard(load(old), process=proc)
        record("X03", "[真实] 旧版未布线包：不误报阻断，且提示走线缺失", c == 0 and "【阻断级】" not in o and "GB.TRACK.NONE" in o, o[-200:])
    if rb and rc_ and new:
        c, o = _cap(bg.main, ["check", "--bom", str(rb), "--cpl", str(rc_), "--gerber", str(new)])
        record("X04", "[真实] 原生 BOM+坐标：无阻断、位号集合一致、坐标不超板", c == 0 and "X.BOM_CPL.SET" in o and "【阻断级】" not in o, o[-200:])
        with tempfile.TemporaryDirectory() as td:
            for src, kind in ((rb, "bom"), (rc_, "cpl")):
                bg.normalize(src, Path(td) / f"{kind}.csv", kind)
            c, o = _cap(bg.main, ["check", "--bom", str(Path(td) / "bom.csv"), "--cpl", str(Path(td) / "cpl.csv"), "--gerber", str(new)])
        record("X05", "[真实] 规范化后的 BOM+坐标：仍无阻断", c == 0 and "【阻断级】" not in o)


def test_skill_spec():
    """对照公开 Agent Skills 规范校验本包结构（tools/validate_skill.py）。"""
    sys.path.insert(0, str(ROOT / "tools"))
    import validate_skill as vs
    R, code = vs.validate(ROOT)
    bad = [f"{r} [{d}]" for r, ok, d in R if not ok]
    record("V01", f"符合 Agent Skills 规范（{len(R)} 项检查）", code == 0, "; ".join(bad[:4]))
    # 校验器自身可靠性：几类典型违规必须被抓到（防止校验器退化成永远通过）
    import shutil as _sh
    def mutate(f):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / ROOT.name
            _sh.copytree(ROOT, d, ignore=_sh.ignore_patterns("__pycache__", "out"))
            p = d / "SKILL.md"
            p.write_bytes(f(p.read_bytes().decode("utf-8")).encode("utf-8"))
            return vs.validate(d)[1]
    nl, sl = chr(10), chr(0x2f)
    record("V02", "校验器能抓到：frontmatter 里混入字面量 /n（本包曾真实出现）", mutate(lambda s: s.replace("metadata:" + nl, "metadata:" + sl + "n")) != 0)
    record("V03", "校验器能抓到：name 含大写", mutate(lambda s: s.replace("name: jlceda-pcb-ai-workflow", "name: Bad-Name")) != 0)
    record("V04", "校验器能抓到：description 超 1024 字符", mutate(lambda s: re.sub(r"(description: .+)", lambda m: m.group(1) + "x" * 900, s, count=1)) != 0)
    record("V05", "校验器能抓到：规范外的顶层字段", mutate(lambda s: s.replace("license: MIT", "license: MIT" + nl + "version: 1")) != 0)
    record("V06", "校验器能抓到：SKILL.md 含 CRLF", mutate(lambda s: s.replace(nl, chr(13) + nl)) != 0)

# ───────────────────────── Bridge 红线 / 无裸阈值 ─────────────────────────
def test_guard_and_lint():
    for api in ("placePcbOrder", "placeSmtComponentsOrder", "placeComponentsOrder"):
        try:
            bc.guard(f"return await eda.pcb_ManufactureData.{api}(false,true);")
            record(f"B-{api[:9]}", f"红线：拦截 {api}", False)
        except bc.BridgeError:
            record(f"B-{api[:9]}", f"红线：拦截 {api}", True)
    try:
        bc.guard("return await eda.pcb_Drc.check(true,false,true);")
        record("B04", "红线不误伤正常代码(DRC)", True)
    except bc.BridgeError:
        record("B04", "红线不误伤正常代码(DRC)", False)
    for api in ("getPdfFile", "getSvgFile", "getPngFile"):
        try:
            bc.guard(f"return await eda.x.{api}('a');")
            record(f"B-{api[:7]}", f"防卡死：默认拦截 {api}", False)
        except bc.BridgeError:
            try:
                bc.guard(f"return await eda.x.{api}('a');", allow_hang=True)
                record(f"B-{api[:7]}", f"防卡死：默认拦截 {api}，显式 allow_hang 可放行", True)
            except bc.BridgeError:
                record(f"B-{api[:7]}", f"防卡死：默认拦截 {api}，显式 allow_hang 可放行", False)
    record("B05", "分批：25 个对象按 12 一批 → 3 批", [len(x) for x in bc.chunks(list(range(25)), 12)] == [12, 12, 1])
    # export_gerber 拒绝覆盖（不需要 Bridge 在线）
    import export_gerber as eg
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.zip"; p.write_bytes(b"x")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = eg.main(["--out", str(p)])
        record("B06", "export_gerber 拒绝覆盖已有文件", code == 2 and "拒绝覆盖" in err.getvalue())
    # 无裸阈值 lint：脚本内不允许出现带小数点的数字字面量（物理换算常数除外）
    allow = {"25.4", "0.0254", "1.0", "0.0", "1.5"}
    offenders = []
    for py in sorted((ROOT / "scripts").glob("*.py")):
        for ln, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            code_part = line.split("#")[0]
            if code_part.strip().startswith(('"""', "'''", '"', "'")) or "timeout" in code_part or "'''" in code_part:
                continue
            for m in re.finditer(r"(?<![\w.\"'])(\d+\.\d+)(?![\w.\"'])", re.sub(r"\"[^\"]*\"|'[^']*'", "", code_part)):
                if m.group(1) not in allow:
                    offenders.append(f"{py.name}:{ln}:{m.group(1)}")
    record("B07", "scripts/ 内无裸工艺阈值", not offenders, "; ".join(offenders[:6]))


# ───────────────────────── 在线(可选) ─────────────────────────
def test_live():
    import drc_check as dc
    import export_gerber as eg
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = dc.main(["--limit", "1"])
    record("L01", "在线：原生 DRC 可执行(返回 0/1)", code in (0, 1), f"exit={code}")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "live.zip"
        with contextlib.redirect_stdout(io.StringIO()):
            code = eg.main(["--out", str(out), "--name", "T"])
        ok = code == 0 and out.exists() and zipfile.is_zipfile(out)
        record("L02", "在线：导出 Gerber 完整取回且为有效 zip", ok, f"exit={code}")
        if ok:
            c, o = run_guard(load(out))
            record("L03", "在线：新导出包通过 gerber_guard(无阻断)", c in (0, 1) and "GB.FILE.REQUIRED" not in o, f"exit={c}")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    test_gerber(); test_bomcpl(); test_spec(); test_rules_check(); test_workflow_release_drift(); test_privacy_and_fixtures(); test_real_fixtures(); test_skill_spec(); test_guard_and_lint()
    if "--live" in sys.argv:
        test_live()
    fails = [r for r in RESULTS if not r[2]]
    for tid, name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {tid:<10} {name}" + (f"  ← {detail}" if (not ok and detail) else ""))
    print(f"\n共 {len(RESULTS)} 项，通过 {len(RESULTS) - len(fails)}，失败 {len(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

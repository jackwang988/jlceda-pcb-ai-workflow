#!/usr/bin/env python3
"""M2 导出：经 Bridge 让 EDA 生成 Gerber，并完整取回到本地 zip（不截断）。

只读操作：getGerberFile 在 EDA 内存中生成文件，不修改工程、不上传、不下单。
默认参数 = 编辑器"导出PCB制版文件"一键导出（单位 mm、格式 4:5、按嘉立创生产要求选层）。

约定（来自 data/known-pitfalls.json）：
  FL-01  File 对象必须读成 base64 分块回传；通用脚本的 [:8000] 会切坏数据 → 本脚本不截断
  P4     只写新文件，不覆盖已存在的导出（防止旧包被悄悄替换）
  非PCB  当前文档不是 PCB 时拒绝导出（BLOCKED）

产物：<out>.zip 与 <out>.manifest.json（sha256、文件清单、EDA 版本、导出时间、工程名）。
退出码：0 成功；2 BLOCKED(通信/文档类型/空文件/拒绝覆盖)。
"""
import argparse
import base64
import hashlib
import io
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bridge_client as bc  # noqa: E402

DOC_TYPE_PCB = 3  # EDMT_EditorDocumentType.PCB 的运行时数值（运行时枚举对象不可用，见 EV-02）

JS = r"""
const out = {};
const d = await eda.dmt_SelectControl.getCurrentDocumentInfo();
out.docType = d ? d.documentType : null;
if (out.docType !== __PCB__) { return out; }
try { out.version = await eda.sys_Environment.getEditorCurrentVersion(); } catch (e) {}
try { const p = await eda.dmt_Project.getCurrentProjectInfo(); out.project = p ? (p.friendlyName || p.name) : null; } catch (e) {}
const g = await eda.pcb_ManufactureData.getGerberFile(__NAME__);
if (!g) { out.empty = true; return out; }
const buf = await g.arrayBuffer();
const bytes = new Uint8Array(buf);
let bin = ''; const chunk = 8192;
for (let i = 0; i < bytes.length; i += chunk) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
out.name = g.name; out.size = g.size; out.b64 = btoa(bin);
return out;
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="经 Bridge 导出嘉立创EDA Gerber 到本地")
    ap.add_argument("--out", required=True, help="本地输出 zip 路径（已存在则拒绝覆盖）")
    ap.add_argument("--name", default="Gerber", help="EDA 内的导出文件名（不含扩展名）")
    a = ap.parse_args(argv)
    out = Path(a.out)
    if out.exists():
        print(f"BLOCKED: {out} 已存在，拒绝覆盖。请换新文件名（每次导出保留独立版本）。", file=sys.stderr)
        return 2
    if not out.parent.exists():
        print(f"BLOCKED: 目录不存在 {out.parent}", file=sys.stderr)
        return 2
    code = JS.replace("__PCB__", str(DOC_TYPE_PCB)).replace("__NAME__", json.dumps(a.name))
    try:
        r = bc.execute(code)
    except bc.BridgeError as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        return 2
    if r.get("docType") != DOC_TYPE_PCB:
        print(f"BLOCKED: 当前文档类型={r.get('docType')}，不是 PCB。请先在 EDA 里打开 PCB 页面。", file=sys.stderr)
        return 2
    if r.get("empty") or not r.get("b64"):
        print("BLOCKED: getGerberFile 返回空（板子可能为空，或缺少板框）。", file=sys.stderr)
        return 2
    raw = base64.b64decode(r["b64"])
    if len(raw) != r.get("size"):
        print(f"BLOCKED: 完整性校验失败：EDA 报告 {r.get('size')} 字节，解码得 {len(raw)} 字节。", file=sys.stderr)
        return 2
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = z.namelist()
            bad = z.testzip()
    except zipfile.BadZipFile:
        print("BLOCKED: 取回的数据不是有效 zip。", file=sys.stderr)
        return 2
    if bad:
        print(f"BLOCKED: zip 内文件损坏：{bad}", file=sys.stderr)
        return 2
    out.write_bytes(raw)
    manifest = {
        "file": out.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        "files": names, "eda_version": r.get("version"), "project": r.get("project"),
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "note": "导出成功≠制造内容正确；请先过 gerber_guard.py。",
    }
    mp = out.with_suffix(".manifest.json")
    mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: {out} ({len(raw)} 字节, {len(names)} 个文件)｜EDA {r.get('version')}｜工程 {r.get('project')}")
    print(f"    sha256 {manifest['sha256'][:16]}…｜清单 {mp}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())

#!/usr/bin/env python3
"""经 Bridge 导出 BOM + 坐标(CPL)，并生成可直接上传的规范化版本，再跑 bom_cpl_guard。

只读操作：getBomFile / getPickAndPlaceFile 在 EDA 内存生成文件，不改工程、不上传、不下单。
产物（目录需已存在，已存在的同名文件拒绝覆盖）：
  <prefix>_BOM.native.csv   EDA 原生(UTF-16+TAB)，原样保存，作证据
  <prefix>_CPL.native.csv
  <prefix>_BOM.csv          规范化：UTF-8 + 逗号 + 去空行
  <prefix>_CPL.csv          规范化：同上，且坐标去掉 mm 后缀
  <prefix>_bom_cpl.manifest.json  sha256、EDA 版本、导出时间、复核结论

约定：getPickAndPlaceFile 的单位参数传字符串 'mm'（运行时 ESYS_Unit 枚举不可用，EV-02）。
退出码：0 无阻断；1 复核有阻断；2 BLOCKED(通信/文档类型/空文件/拒绝覆盖)。
"""
import argparse
import base64
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bom_cpl_guard as bg  # noqa: E402
import bridge_client as bc  # noqa: E402

DOC_TYPE_PCB = 3

JS = r"""
const out = {};
const d = await eda.dmt_SelectControl.getCurrentDocumentInfo();
out.docType = d ? d.documentType : null;
if (out.docType !== __PCB__) { return out; }
try { out.version = await eda.sys_Environment.getEditorCurrentVersion(); } catch (e) {}
try { const p = await eda.dmt_Project.getCurrentProjectInfo(); out.project = p ? (p.friendlyName || p.name) : null; } catch (e) {}
const enc = async (f) => {
  if (!f) return null;
  const bytes = new Uint8Array(await f.arrayBuffer());
  let bin = ''; const chunk = 8192;
  for (let i = 0; i < bytes.length; i += chunk) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  return { size: f.size, b64: btoa(bin) };
};
try { out.bom = await enc(await eda.pcb_ManufactureData.getBomFile('BOM', 'csv')); } catch (e) { out.bomErr = String(e).slice(0, 160); }
try { out.cpl = await enc(await eda.pcb_ManufactureData.getPickAndPlaceFile('CPL', 'csv', 'mm')); } catch (e) { out.cplErr = String(e).slice(0, 160); }
return out;
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="导出并规范化 BOM/坐标")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--prefix", required=True, help="文件名前缀，如 MyBoard_V1.0")
    ap.add_argument("--gerber", help="Gerber zip，用于核对坐标极差≤板尺寸")
    a = ap.parse_args(argv)
    od = Path(a.out_dir)
    if not od.is_dir():
        print(f"BLOCKED: 目录不存在 {od}", file=sys.stderr)
        return 2
    names = {k: od / f"{a.prefix}_{v}" for k, v in (("bom_n", "BOM.native.csv"), ("cpl_n", "CPL.native.csv"),
                                                    ("bom", "BOM.csv"), ("cpl", "CPL.csv"),
                                                    ("man", "bom_cpl.manifest.json"))}
    exist = [str(p) for p in names.values() if p.exists()]
    if exist:
        print(f"BLOCKED: 拒绝覆盖已有文件 {exist}", file=sys.stderr)
        return 2
    try:
        r = bc.execute(JS.replace("__PCB__", str(DOC_TYPE_PCB)))
    except bc.BridgeError as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        return 2
    if r.get("docType") != DOC_TYPE_PCB:
        print(f"BLOCKED: 当前文档类型={r.get('docType')}，不是 PCB。", file=sys.stderr)
        return 2
    for k in ("bom", "cpl"):
        if r.get(f"{k}Err") or not r.get(k):
            print(f"BLOCKED: {k.upper()} 导出失败：{r.get(f'{k}Err') or '返回空'}", file=sys.stderr)
            return 2
    raws = {}
    for k in ("bom", "cpl"):
        raw = base64.b64decode(r[k]["b64"])
        if len(raw) != r[k]["size"]:
            print(f"BLOCKED: {k.upper()} 完整性校验失败（{r[k]['size']} vs {len(raw)}）", file=sys.stderr)
            return 2
        raws[k] = raw
        names[f"{k}_n"].write_bytes(raw)
    summary = {}
    for k in ("bom", "cpl"):
        summary[k] = bg.normalize(names[f"{k}_n"], names[k], k)
    board = bg.board_from_gerber(a.gerber) if a.gerber else None
    items, info = bg.run_checks(names["bom"], names["cpl"], board)
    blocks = sum(1 for i in items if i["status"] == "BLOCK")
    manifest = {
        "prefix": a.prefix, "eda_version": r.get("version"), "project": r.get("project"),
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "files": {n.name: {"bytes": n.stat().st_size, "sha256": hashlib.sha256(n.read_bytes()).hexdigest()}
                  for k, n in names.items() if k != "man"},
        "normalize": summary, "check": {"blocks": blocks, "items": items},
        "note": "复核通过≠C编号与器件对应，也不代表可贴装；请以嘉立创下单页匹配结果为准。本工具不上传、不下单。",
    }
    names["man"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: BOM {summary['bom']['rows']} 行 / CPL {summary['cpl']['rows']} 行｜EDA {r.get('version')}｜工程 {r.get('project')}")
    tag = {"BLOCK": "【阻断级】", "WARN": "【中风险】", "PASS": "  PASS  "}
    for i in sorted(items, key=lambda x: {"BLOCK": 0, "WARN": 1, "PASS": 2}[x["status"]]):
        print(f"{tag[i['status']]} {i['id']}：{i['msg']}")
    print(f"清单：{names['man']}")
    return 1 if blocks else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())

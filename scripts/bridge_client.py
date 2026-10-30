#!/usr/bin/env python3
"""Bridge 客户端：把一段 JS 送进运行中的嘉立创EDA 执行，并把结果完整带回。

固化的是本项目实测踩过的坑（见 data/known-pitfalls.json）：
  BR-01/BR-02  HTTP 500 时必须读 body；返回值必须是可 JSON 序列化的原始类型
  BR-03        批量操作要分批，单次 execute 不能过重
  FL-01        取回结果绝不截断（通用脚本的 [:8000] 会切坏 base64）
  红线         永不执行会真实下单/开订单页的接口（place*Order）

退出码：0 成功；2 失败/被拦截（BLOCKED）。本脚本只负责"送代码、取结果"，不判断设计是否合格。
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

PORT_START, PORT_END = 49620, 49629
SERVICE_ID = "easyeda-bridge"
DEFAULT_TIMEOUT = 900  # 秒；EDA 侧 autoRouting 内部另有 900s 硬上限

# 红线：这些接口会真实打开订单页并产生订单数据，Skill 层面永远不允许
FORBIDDEN_CALLS = re.compile(
    r"\b(placePcbOrder|placeSmtComponentsOrder|placeComponentsOrder)\b"
)


# 已知会让 EDA 卡死/不返回的接口（实测 2026-10-30，见 pitfalls BR-06）。默认拦截，需显式 allow_hang=True 才放行。
HANG_PRONE_CALLS = re.compile(
    r"\b(getPdfFile|getSvgFile|getPngFile|getDxfFile|getExportDocumentFile)\b"
)


class BridgeError(RuntimeError):
    pass


def _utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def discover(host="127.0.0.1"):
    """扫描端口并验证握手，返回 (port, health_json)；找不到则抛 BridgeError。"""
    for port in range(PORT_START, PORT_END + 1):
        try:
            with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=1.5) as r:
                data = json.loads(r.read().decode("utf-8"))
            if data.get("service") == SERVICE_ID:
                return port, data
        except Exception:
            continue
    raise BridgeError(
        "未发现 Bridge。请先启动：node <easyeda-api>/scripts/bridge-server.mjs（后台运行）"
    )


def guard(code: str, allow_hang=False):
    """执行前拦截。红线直接抛错；已知会卡死 EDA 的接口默认也拦截。"""
    m = FORBIDDEN_CALLS.search(code)
    if m:
        raise BridgeError(
            f"BLOCKED: 代码含 {m.group(1)}，会真实下单/开订单页，Skill 不允许调用。"
            "请由用户在 EDA 界面自行操作。"
        )
    h = HANG_PRONE_CALLS.search(code)
    if h and not allow_hang:
        raise BridgeError(
            f"BLOCKED: 代码含 {h.group(1)}，实测会让 EDA 卡死/断开 Bridge（BR-06），默认拒绝。"
            "本流程用不到它；确需使用请在 EDA 界面手动导出。"
        )


def execute(code: str, window_id=None, timeout=DEFAULT_TIMEOUT, port=None, allow_hang=False):
    """执行 JS 并返回 result 字段。失败抛 BridgeError，信息含 EDA 侧真实错误。"""
    guard(code, allow_hang=allow_hang)
    if port is None:
        port, health = discover()
        if not health.get("edaConnected"):
            raise BridgeError("Bridge 在线，但没有 EDA 窗口连接（需在嘉立创EDA 里加载 run-api-gateway 扩展）。")
    payload = {"code": code}
    if window_id:
        payload["windowId"] = window_id
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/execute",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        # BR-01：状态码不等于真相，真正的错误在 body 里（常见是 timed out / 参数错误）
        body = e.read().decode("utf-8", errors="replace")
        try:
            msg = json.loads(body).get("error", body)
        except Exception:
            msg = body
        raise BridgeError(f"EDA 侧报错 (HTTP {e.code}): {msg}")
    except Exception as e:
        raise BridgeError(f"通信失败: {e}")
    try:
        parsed = json.loads(body)
    except Exception:
        raise BridgeError(f"返回不是 JSON: {body[:300]}")
    if not parsed.get("success", True):
        raise BridgeError(parsed.get("error", "未知错误"))
    return parsed.get("result")


def chunks(seq, n):
    """BR-03：分批。器件建议 n<=12，导线 n<=15。"""
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# 常用的"收尾"片段：写入类节点结束时必须 save（ST-01 实测丢过整板）
SAVE_SNIPPET = (
    "const o={};"
    "try{ if(eda.sch_Document&&eda.sch_Document.save){await eda.sch_Document.save();o.sch='ok';} }catch(e){o.schErr=String(e).slice(0,80);}"
    "try{ if(eda.pcb_Document&&eda.pcb_Document.save){await eda.pcb_Document.save();o.pcb='ok';} }catch(e){o.pcbErr=String(e).slice(0,80);}"
    "return o;"
)


def main(argv=None):
    _utf8_stdout()
    ap = argparse.ArgumentParser(description="嘉立创EDA Bridge 客户端")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health", help="探活并列出 EDA 窗口")
    ex = sub.add_parser("exec", help="执行 JS 文件")
    ex.add_argument("file")
    ex.add_argument("--out", help="结果写入该 JSON 文件（不截断）")
    ex.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    sub.add_parser("save", help="保存当前原理图与PCB")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "health":
            port, h = discover()
            print(json.dumps({"port": port, **h}, ensure_ascii=False, indent=2))
            return 0 if h.get("edaConnected") else 2
        if a.cmd == "save":
            print(json.dumps(execute(SAVE_SNIPPET), ensure_ascii=False))
            return 0
        code = Path(a.file).read_text(encoding="utf-8")
        res = execute(code, timeout=a.timeout)
        text = json.dumps(res, ensure_ascii=False, indent=2)
        if a.out:
            Path(a.out).write_text(text, encoding="utf-8")
            print(f"OK: 已写入 {a.out} ({len(text)} 字符)")
        else:
            print(text)  # 不截断
        return 0
    except BridgeError as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

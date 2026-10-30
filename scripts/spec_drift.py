#!/usr/bin/env python3
"""规范漂移检测：把 data/*.json 里每条规则的原文片段(quote)与官方页面当前内容比对。

做法：从每条 quote 里抽出所有数字记号，检查它们是否仍出现在官方页面文本里。
  OK              quote 的数字都还在页面里
  DRIFT_SUSPECT   有数字不在页面里 → 官方可能改了数值，须人工核对（报告列出缺失的数字）
  UNREADABLE      页面里一个 quote 数字都找不到 → 多半是页面由 JS 渲染，抓到的是空壳，**不能据此说"没漂移"**
  UNREACHABLE     抓取失败
  NO_NUMBERS      quote 里没有数字，本检测覆盖不了
只报告，不改库。T0 来源(客户端实测)不联网，跳过。

页面内容可用 --page URL=本地文件 提供（离线测试，或你手动另存了网页）；否则联网抓取。
退出码：0 无可疑；1 有 DRIFT_SUSPECT；2 有 UNREACHABLE/UNREADABLE（无法下结论，BLOCKED）。
"""
import argparse
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA_FILES = ("jlc-pcb-capabilities.json", "jlc-smt-capabilities.json", "jlc-bom-cpl-spec.json")
UA = "Mozilla/5.0 (jlceda-pcb-ai-workflow spec_drift)"
FETCH_TIMEOUT = 20  # 秒，网络参数
NUM = re.compile(r"\d+(?:\.\d+)?")
# 官方页面里同一数值可能写成 0.10 / 0.1，比较时按数值归一化
PUNCT_TO_SPACE = re.compile(r"[\s\u00a0]+")


def _utf8():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def html_to_text(raw):
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return PUNCT_TO_SPACE.sub(" ", html.unescape(raw))


def number_set(text):
    out = set()
    for m in NUM.findall(text):
        out.add(m)
        try:
            out.add(format(float(m), "g"))
        except ValueError:
            pass
    return out


def collect(data_files=DATA_FILES):
    """返回 [(来源id, url, tier, [(rule_id, kind, quote)])]。"""
    by_url = {}
    for fn in data_files:
        d = json.loads((DATA / fn).read_text(encoding="utf-8"))
        for r in d.get("rules", []):
            for kind in ("limit", "recommended", "cost_trigger"):
                t = r.get(kind)
                if isinstance(t, dict) and t.get("src") in d["sources"]:
                    s = d["sources"][t["src"]]
                    by_url.setdefault((s["url"], s["tier"]), []).append((r["id"], kind, t.get("quote", "")))
            if "quote" in r and r.get("src") in d["sources"]:  # bom-cpl-spec 的规则形态
                s = d["sources"][r["src"]]
                by_url.setdefault((s["url"], s["tier"]), []).append((r["id"], "rule", r["quote"]))
    return by_url


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        b = resp.read()
    for enc in ("utf-8", "gb18030"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


def check_source(url, items, content):
    page_nums = number_set(html_to_text(content))
    res = []
    for rid, kind, quote in items:
        q = number_set(quote)
        if not q:
            res.append((rid, kind, "NO_NUMBERS", []))
            continue
        present = {n for n in q if n in page_nums}
        if not present:
            res.append((rid, kind, "UNREADABLE", sorted(q)))
        elif present != q:
            res.append((rid, kind, "DRIFT_SUSPECT", sorted(q - present)))
        else:
            res.append((rid, kind, "OK", []))
    return res


def run(pages=None, only_t1=True, fetcher=fetch):
    pages = pages or {}
    out = []  # (url, status_for_source, [(rid, kind, st, detail)])
    for (url, tier), items in sorted(collect().items()):
        if not url.startswith("http"):
            continue  # T0：本机 API，不联网
        if only_t1 and tier not in ("T1", "T2"):
            continue
        try:
            content = pages[url] if url in pages else fetcher(url)
        except Exception as e:  # noqa: BLE001
            out.append((url, "UNREACHABLE", [(None, None, "UNREACHABLE", [str(e)[:80]])]))
            continue
        out.append((url, "FETCHED", check_source(url, items, content)))
    return out


def summarize(out):
    cnt = {}
    for _u, _s, rs in out:
        for _rid, _k, st, _d in rs:
            cnt[st] = cnt.get(st, 0) + 1
    code = 1 if cnt.get("DRIFT_SUSPECT") else (2 if (cnt.get("UNREACHABLE") or cnt.get("UNREADABLE")) else 0)
    return cnt, code


def main(argv=None):
    _utf8()
    ap = argparse.ArgumentParser(description="规范漂移检测（只报告，不改库）")
    ap.add_argument("--page", action="append", default=[], help="URL=本地文件，用本地内容代替联网抓取，可多次")
    ap.add_argument("--no-network", action="store_true", help="禁止联网：未用 --page 提供的来源一律 UNREACHABLE")
    a = ap.parse_args(argv)
    pages = {}
    for kv in a.page:
        u, _, f = kv.partition("=")
        pages[u] = Path(f).read_text(encoding="utf-8", errors="replace")

    def fetcher(url):
        if a.no_network:
            raise RuntimeError("--no-network 且未提供该页面")
        return fetch(url)

    out = run(pages, fetcher=fetcher)
    cnt, code = summarize(out)
    for url, st, rs in out:
        bad = [r for r in rs if r[2] not in ("OK", "NO_NUMBERS")]
        print(f"{'⚠' if bad else '·'} {url}｜{st}｜规则引用 {len(rs)} 处")
        for rid, kind, s, detail in bad:
            print(f"     {s:<14} {rid or '(整页)'} [{kind or ''}] {('缺失数字: ' + ', '.join(detail)) if detail else ''}")
    print(f"\n汇总：{cnt}")
    if code == 1:
        print("结论：存在可疑漂移——请人工打开对应官方页核对，确认后再改 data/*.json（本工具不会自动改库）")
    elif code == 2:
        print("结论：BLOCKED——有来源抓取失败或页面不可读（多为 JS 渲染），无法据此判断没有漂移；请用 --page 提供另存的页面，或人工抽查")
    else:
        print("结论：所有可比对的数字仍出现在官方页面中（只证明数字还在，不证明语义没变）")
    return code


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""按公开 Agent Skills 规范（https://agentskills.io/specification ，2026-10-30 核对）校验本 skill 的结构。

只依赖标准库，因此带一个**最小 YAML 子集解析器**（足够解析规范允许的 frontmatter：顶层标量 + 一层 metadata 映射）。
解析器遇到不认识的语法（列表、嵌套更深、多行块）会明确报错而不是猜，避免“解析器宽松 → 校验假通过”。

用法：python tools/validate_skill.py [skill目录]      退出码 0 全部通过；1 有违规；2 无法解析
"""
import os
import re
import sys
from pathlib import Path

NAME_MAX, DESC_MAX, COMPAT_MAX = 64, 1024, 500
BODY_LINES_MAX = 500
BODY_TOKENS_MAX = 5000
ALLOWED = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}


class YamlSubsetError(Exception):
    pass


def parse_frontmatter(text):
    """返回 (dict, 正文)。只支持：'key: value' 与一层 'key:' + 缩进的 'k: v' 子映射。"""
    if "\r" in text:
        raise YamlSubsetError("SKILL.md 含 CR 字符（应统一为 LF 换行）")
    if not text.startswith("---\n"):
        raise YamlSubsetError("SKILL.md 必须以 '---' 开头的 frontmatter 起始")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise YamlSubsetError("frontmatter 没有闭合的 '---'")
    block, body = text[4:end], text[end + 5:]
    out, cur = {}, None
    for n, ln in enumerate(block.split("\n"), 2):
        if not ln.strip():
            continue
        if ln.startswith((" ", "\t")):
            if cur is None or not isinstance(out.get(cur), dict):
                raise YamlSubsetError(f"第{n}行：缩进行没有对应的父映射")
            if ln.startswith("\t"):
                raise YamlSubsetError(f"第{n}行：YAML 不允许用 Tab 缩进")
            k, sep, v = ln.strip().partition(":")
            if not sep:
                raise YamlSubsetError(f"第{n}行：子映射行缺少冒号")
            if v.strip().startswith(("-", "[", "{", "|", ">")) or ln.strip().startswith("-"):
                raise YamlSubsetError(f"第{n}行：本解析器不支持列表/块语法，请改成简单的 key: value")
            out[cur][k.strip()] = _scalar(v)
        else:
            k, sep, v = ln.partition(":")
            if not sep:
                raise YamlSubsetError(f"第{n}行：缺少冒号：{ln[:40]!r}")
            k = k.strip()
            if k in out:
                raise YamlSubsetError(f"第{n}行：重复的键 {k}")
            if v.strip() == "":
                out[k] = {}
                cur = k
            else:
                out[k] = _scalar(v)
                cur = k
    return out, body


def _scalar(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    if v.startswith(("[", "{", "|", ">", "&", "*", "!")):
        raise YamlSubsetError(f"不支持的 YAML 值写法：{v[:30]!r}")
    if ": " in v or v.endswith(":") or " #" in v:
        raise YamlSubsetError(f"值里含 ': ' 或 ' #'，YAML 会误解析，请加引号：{v[:40]!r}")
    return v


def est_tokens(s):
    return int(len(re.findall(r"[\u4e00-\u9fff]", s)) + len(re.findall(r"[A-Za-z0-9_]+", s)) * 1.3)


def validate(root):
    root = Path(root).resolve()
    R = []

    def chk(rule, ok, detail=""):
        R.append((rule, bool(ok), detail))

    sk = root / "SKILL.md"
    if not sk.exists():
        return [("SKILL.md 存在", False, "缺失")], 2
    try:
        fm, body = parse_frontmatter(sk.read_text(encoding="utf-8"))
    except YamlSubsetError as e:
        return [("frontmatter 可解析", False, str(e))], 2
    name, desc = fm.get("name", ""), fm.get("description", "")
    chk("name 必填且为字符串", isinstance(name, str) and name != "")
    chk(f"name ≤{NAME_MAX} 字符", len(name) <= NAME_MAX, f"{len(name)}")
    chk("name 仅含小写字母/数字/连字符", re.fullmatch(r"[a-z0-9-]+", name or "") is not None, name)
    chk("name 不以连字符开头或结尾", bool(name) and not name.startswith("-") and not name.endswith("-"))
    chk("name 不含连续连字符", "--" not in name)
    chk("name 与目录名一致", name == root.name, f"name={name} dir={root.name}")
    chk("description 必填、非空", isinstance(desc, str) and desc.strip() != "")
    chk(f"description ≤{DESC_MAX} 字符", len(desc) <= DESC_MAX, f"{len(desc)}")
    chk("description 含“何时使用”场景句（当…时使用 / Use when）", bool(re.search(r"当[^。]{4,}时使用|[Uu]se when", desc)), "规范建议同时写清做什么与何时用")
    chk("description 含具体关键词（≥6 个英文或专有词）", len(set(re.findall(r"[A-Za-z][\w-]{2,}", desc))) >= 6)
    comp = fm.get("compatibility")
    chk(f"compatibility 若提供则 1–{COMPAT_MAX} 字符", comp is None or (isinstance(comp, str) and 1 <= len(comp) <= COMPAT_MAX))
    md = fm.get("metadata")
    chk("metadata 若提供则为 字符串→字符串 映射", md is None or (isinstance(md, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in md.items())),
        str(md))
    chk("frontmatter 无规范之外的顶层字段", set(fm) <= ALLOWED, str(sorted(set(fm) - ALLOWED)))
    lic = fm.get("license")
    chk("license 已声明", bool(lic), str(lic))
    chk("随包 LICENSE 文件存在", (root / "LICENSE").exists() or (root / "LICENSE.txt").exists())
    lines = sk.read_text(encoding="utf-8").count("\n") + 1
    chk(f"SKILL.md < {BODY_LINES_MAX} 行", lines < BODY_LINES_MAX, f"{lines}")
    tk = est_tokens(body)
    chk(f"SKILL.md 正文 < {BODY_TOKENS_MAX} tokens（粗估）", tk < BODY_TOKENS_MAX, f"≈{tk}")
    chk("正文有标题结构", bool(re.search(r"^#{1,3} ", body, re.M)))

    links = sorted(set(re.findall(r"\]\(((?!https?:)[^)#\s]+)\)", body)))
    dead = [l for l in links if not (root / l).exists()]
    chk("SKILL.md 内相对链接均存在", not dead, str(dead))
    scripts_ref = sorted(set(re.findall(r"scripts/([\w.-]+\.py)", body)))
    chk("SKILL.md 提到的脚本均存在", all((root / "scripts" / s).exists() for s in scripts_ref),
        str([s for s in scripts_ref if not (root / 'scripts' / s).exists()]))
    nested = []
    for l in links:
        p = root / l
        if p.suffix == ".md" and p.exists():
            for inner in re.findall(r"\]\(((?!https?:)[^)#\s]+\.md)\)", p.read_text(encoding="utf-8")):
                tgt = (p.parent / inner).resolve()
                if tgt.exists() and tgt != sk.resolve() and tgt.parent == (root / "references").resolve():
                    nested.append((l, inner))
    chk("引用链保持一层深（被引用文件不再链向其他 references）", len(nested) <= 2, str(nested[:4]))

    for d in ("scripts", "references", "assets"):
        chk(f"约定目录 {d}/ 存在", (root / d).is_dir())
    big = [(p.name, p.stat().st_size // 1024) for p in (root / "references").glob("*.md") if p.stat().st_size > 20 * 1024]
    chk("单个 reference < 20KB（按需加载，越小越省上下文）", not big, str(big))
    lng = [p.name for p in (root / "references").glob("*.md")
           if p.read_text(encoding="utf-8").count("\n") > 100 and not re.search(r"^#{1,3} .*(目录|Contents)", p.read_text(encoding="utf-8"), re.M)]
    chk("超过 100 行的 reference 带目录", not lng, str(lng))

    py = sorted((root / "scripts").glob("*.py"))
    chk("scripts 均有 shebang", all(p.read_text(encoding="utf-8").startswith("#!") for p in py))
    chk("scripts 均有模块文档字符串（说明用途与退出码）", all(re.match(r'#!.*\n"""', p.read_text(encoding="utf-8")) for p in py),
        str([p.name for p in py if not re.match(r'#!.*\n"""', p.read_text(encoding="utf-8"))]))
    chk("scripts 均提供 --help（argparse）", all("argparse" in p.read_text(encoding="utf-8") for p in py),
        str([p.name for p in py if "argparse" not in p.read_text(encoding="utf-8")]))
    chk("scripts 只用标准库（无第三方 import）", not _third_party(py), str(_third_party(py)))
    crlf = [p.relative_to(root).as_posix() for p in root.rglob("*")
            if p.is_file() and p.suffix in (".md", ".py", ".json", ".js", ".txt") and "__pycache__" not in p.parts and b"\r\n" in p.read_bytes()]
    chk("文本文件统一 LF 换行", not crlf, str(crlf[:5]))
    chk("无遗留缓存目录 __pycache__", not any(root.rglob("__pycache__")))
    return R, (0 if all(ok for _r, ok, _d in R) else 1)


def _third_party(py):
    std = set(getattr(sys, "stdlib_module_names", ())) or {
        "argparse", "base64", "contextlib", "copy", "csv", "datetime", "hashlib", "html", "io", "json", "os", "re", "shutil", "subprocess",
        "sys", "tempfile", "urllib", "zipfile", "collections", "pathlib", "math"}
    local = {p.stem for p in py} | {"make_fixtures"}
    out = []
    for p in py:
        for m in re.finditer(r"^(?:import|from)\s+([A-Za-z_]\w*)", p.read_text(encoding="utf-8"), re.M):
            if m.group(1) not in std and m.group(1) not in local:
                out.append((p.name, m.group(1)))
    return out


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    root = (argv or sys.argv[1:] or [str(Path(__file__).resolve().parents[1])])[0]
    R, code = validate(root)
    for rule, ok, det in R:
        print(("PASS  " if ok else "FAIL  ") + rule + (f"  [{det}]" if det and not ok else ""))
    print(f"\n汇总：{sum(ok for _r, ok, _d in R)}/{len(R)} 通过")
    return code


if __name__ == "__main__":
    sys.exit(main())

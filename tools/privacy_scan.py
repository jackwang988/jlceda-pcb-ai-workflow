#!/usr/bin/env python3
"""Scan a public skill for common secrets, personal addresses and private network identifiers.

Pure standard library; inspects UTF-8/UTF-16, HTML and nested ZIPs (recursively).
Exit 0 when no matching signatures, 1 when findings exist; a clean scan is NOT a security guarantee.
"""
import argparse
import re
import sys
import zipfile
from io import BytesIO
from pathlib import Path

PATTERNS = {
    "email": re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    "home_absolute_path": re.compile(r"(?i)(?:/(?:home|Users)/[A-Za-z0-9._-]+(?:/|\b)|[A-Z]:[\\/](?:Users|Documents|Projects)[\\/][A-Za-z0-9._-]+)"),
    "private_ipv4": re.compile(r"\b(?:10\.(?:\d{1,3}\.){2}\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"),
    "private_or_internal_domain": re.compile(r"(?i)\b[a-z0-9_-]+(?:\.[a-z0-9_-]+)*\.(?:internal|corp|lan|local)\b"),
    "embedded_url_password": re.compile(r"(?i)https?://[^\s/:@<>]+:[^\s/@<>]+@"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "token_literal": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,})\b"),
    "credential_assignment": re.compile(r"(?i)\b(?:api[_-]?key|api[_-]?secret|client[_-]?secret|access[_-]?token|password)\b\s*[=:\"]\s*['\"]?[a-z0-9_/-]{12,}"),
}
SCAN_SUFFIXES = {".py", ".js", ".ts", ".json", ".jsonl", ".md", ".html", ".txt", ".csv", ".yaml", ".yml", ".toml", ".sh", ".ps1", ".xml", ".env"}


def decode_text(data):
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8", errors="replace")


def scan_blob(name, data, depth=0):
    found = []
    if name.lower().endswith(".zip"):
        if depth > 3:
            return [(name, "nested_zip_depth_exceeded")]
        try:
            with zipfile.ZipFile(BytesIO(data)) as z:
                for item in z.infolist():
                    if item.is_dir():
                        continue
                    if item.file_size > 20 * 1024 * 1024:
                        found.append((name + "!" + item.filename, "oversized_archive_entry"))
                        continue
                    found.extend(scan_blob(name + "!" + item.filename, z.read(item), depth + 1))
        except (zipfile.BadZipFile, RuntimeError, ValueError):
            found.append((name, "unreadable_zip"))
        return found
    if Path(name).suffix.lower() not in SCAN_SUFFIXES and Path(name).name != "LICENSE":
        return found
    content = decode_text(data)
    for label, pattern in PATTERNS.items():
        if pattern.search(content):
            found.append((name, label))
    return found


def scan_tree(root):
    root = Path(root)
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(x in (".git", "__pycache__", ".pytest_cache") for x in path.parts):
            continue
        found.extend(scan_blob(path.relative_to(root).as_posix(), path.read_bytes()))
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args(argv)
    found = scan_tree(args.directory)
    for path, rule in found:
        print("FINDING", path, rule)
    print("privacy scan:", "PASS" if not found else "FAIL", "findings:", len(found))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())

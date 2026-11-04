#!/usr/bin/env python3
"""Read-only schematic project-spec checks on normalized EDA evidence (stdlib).

Exit 0: declared scope has no blocker/unknown; 1: design conflict;
2: missing/invalid evidence or I/O failure. Never writes to EDA or approves G1/G2.
"""
import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

from geometry_audit import box, overlap, within

KINDS = {"component", "label", "wire", "stub", "port", "section", "annotation"}
SCOPES = {"page", "project"}


def text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("需要非空字符串")
    return value


def records(values, key="id", nonempty=False):
    if not isinstance(values, list) or (nonempty and not values):
        raise ValueError("清单必须为数组，必需清单不得为空")
    result = {}
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("清单成员必须为对象")
        ident = text(value.get(key))
        if ident in result:
            raise ValueError("重复标识：" + ident)
        result[ident] = value
    return result


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("间距必须为非负有限数字，单位沿用项目声明")
    return value


def component_key(item):
    ref = text(item.get("ref"))
    part = item.get("subpart", "")
    if not isinstance(part, str):
        raise ValueError("subpart 必须为字符串")
    return ref + ("." + part if part else "")


def component_map(items):
    result = {}
    for item in items:
        key = component_key(item)
        if key in result:
            raise ValueError("重复器件单元：" + key)
        result[key] = item
    return result


def finish(issues, metrics=None):
    counts = {s: sum(i["severity"] == s for i in issues) for s in ("BLOCK", "NEEDS_EVIDENCE", "WARN")}
    overall = ("BLOCKED" if counts["BLOCK"] else "NEEDS_EVIDENCE" if counts["NEEDS_EVIDENCE"]
               else "PASS_WITH_WARN" if counts["WARN"] else "PASS_SCOPE_ONLY")
    return {"domain": "schematic", "overall": overall, "counts": counts, "metrics": metrics or {},
            "issues": issues, "limitations": [
                "仅检查提供的项目规格与归一化证据；来源/完整性声明不等于真实性、时效性或采集证明",
                "不运行 ERC、不读图、不验证器件手册或电路功能；ERC/读图记录须在 G1/G2 绑定实际证据",
                "不求解布局或连线；导线/实体碰撞另用 geometry_audit，原生 ERC 与工程评审仍必需",
                "不修改原理图、PCB、门禁或共享规则，不上传、不下单"]}


def audit(spec, evidence):
    try:
        return _audit(spec, evidence)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return finish([{"severity": "NEEDS_EVIDENCE", "code": "INPUT.INVALID", "objects": [], "detail": str(exc)}])


def _audit(spec, evidence):
    for doc in (spec, evidence):
        if (not isinstance(doc, dict) or type(doc.get("schema_version")) is not int or
                doc.get("schema_version") != 1 or doc.get("domain") != "schematic"):
            raise ValueError("仅支持 schema_version=1、domain=schematic")
        if doc.get("unit") != "sch_api_10mil":
            raise ValueError("unit 必须为 sch_api_10mil，不接受 raw 或隐式换算")
    issues = []

    def issue(severity, code, objects, detail):
        issues.append({"severity": severity, "code": code, "objects": list(objects), "detail": detail})

    for key in ("project_id", "schematic_id"):
        if text(spec.get(key)) != evidence.get(key):
            issue("BLOCK", "SCOPE.MISMATCH", [key], "证据不属于规格指定的工程/原理图")
    text(evidence.get("revision"))
    if evidence.get("capture_source") != "eda_readback":
        issue("NEEDS_EVIDENCE", "CAPTURE.UNVERIFIED", [], "需要归一化的实际 EDA 回读及外部原始证据")
    pages = records(spec.get("pages"), nonempty=True)
    actual_pages = records(evidence.get("pages"), nonempty=True)
    modules = records(spec.get("modules"), nonempty=True)
    expected = component_map(spec.get("components", []))
    if not expected:
        raise ValueError("必须声明正式器件及其完整引脚状态")
    interfaces = records(spec.get("interfaces", []))
    required = spec.get("required_geometry")
    if not isinstance(required, list) or not required or len(set(required)) != len(required) or not set(required) <= KINDS:
        raise ValueError("required_geometry 必须为不重复的已知图元类型")
    if not {"component", "label"} <= set(required):
        raise ValueError("至少声明 component 与 label 的完整采集")
    layout = spec["layout"]
    padding, gap = number(layout["module_padding"]), number(layout["label_gap"])
    for ident, module in modules.items():
        text(module.get("title"))
        if module.get("page_id") not in pages:
            raise ValueError("模块没有合法 page_id：" + ident)
        for flag in ("frame_required", "title_required"):
            if not isinstance(module.get(flag), bool):
                raise ValueError("模块须明确声明 " + flag)
        parent = module.get("parent_id")
        seen = {ident}
        while parent is not None:
            if parent not in modules or parent in seen or modules[parent]["page_id"] != module["page_id"]:
                raise ValueError("模块父子关系不存在、跨页或成环：" + ident)
            seen.add(parent)
            parent = modules[parent].get("parent_id")
    for key, comp in expected.items():
        if comp.get("module_id") not in modules:
            raise ValueError("器件没有合法模块归属：" + key)
        pins = records(comp.get("pins"), "number", nonempty=True)
        for pin in pins.values():
            if pin.get("state") not in ("connected", "nc", "unresolved"):
                raise ValueError("引脚 state 必须为 connected/nc/unresolved")
            if pin["state"] == "connected":
                text(pin.get("net"))
                if pin.get("net_scope") not in SCOPES:
                    raise ValueError("引脚需要明确网络作用域")
            if pin["state"] == "nc":
                text(pin.get("reason"))
                if pin.get("net") or pin.get("net_scope"):
                    raise ValueError("NC 规格不能同时声明网络")
    if set(pages) != set(actual_pages):
        issue("BLOCK", "PAGES.SET", [], "正式页集合与规格不一致；测量页需从正式范围排除")
    items, actual, frames, titles, stubs = {}, {}, {}, {}, {}
    for page_id, page in actual_pages.items():
        if page_id not in pages:
            continue
        drawable = box(pages[page_id]["drawable_bbox"])
        forbidden = [box(b) for b in pages[page_id].get("forbidden_bboxes", [])]
        page_items = records(page.get("items"))
        coverage = page.get("coverage", {})
        counts = Counter(item.get("kind") for item in page_items.values())
        for kind in set(required) | set(counts):
            entry = coverage.get(kind, {})
            count = entry.get("count")
            if (entry.get("complete") is not True or isinstance(count, bool) or not isinstance(count, int)
                    or count != counts[kind]):
                issue("NEEDS_EVIDENCE", "COVERAGE.INCOMPLETE", [page_id, str(kind)], "缺完整采集声明或数量不符；零对象也须明确说明")
        labels = []
        for ident, item in page_items.items():
            kind = item.get("kind")
            if kind not in KINDS:
                raise ValueError("未知图元类型：" + str(kind))
            rect = box(item["bbox"])
            if item.get("bbox_source") != "eda_measured":
                issue("NEEDS_EVIDENCE", "BBOX.UNVERIFIED", [page_id, ident], "缺逐图元实测 BBox")
            if not within(rect, drawable) or any(overlap(rect, b) for b in forbidden):
                issue("BLOCK", "PAGE.BOUNDS", [page_id, ident], "图元越出绘图区或侵入标题栏/禁入区")
            mid = item.get("module_id")
            interface_wire = kind == "wire" and item.get("interface_id") in interfaces
            if item.get("interface_id") and not interface_wire:
                raise ValueError("仅登记接口的 wire 可声明 interface_id")
            if interface_wire:
                link = interfaces[item["interface_id"]]
                ends = {e["module_id"] for e in link["endpoints"]}
                if (mid is not None and mid not in ends) or not any(
                        m in modules and modules[m]["page_id"] == page_id for m in ends):
                    issue("BLOCK", "INTERFACE.WIRE_SCOPE", [page_id, ident], "接口越框例外不属于该模块/页面")
                if item.get("net") != link.get("net") or item.get("net_scope") != link.get("net_scope"):
                    issue("BLOCK", "INTERFACE.WIRE", [page_id, ident], "跨模块导线的网络语义与登记接口不同")
            page_note = kind == "annotation" and item.get("role") == "page_note"
            if not page_note and not interface_wire and mid not in modules:
                issue("NEEDS_EVIDENCE", "MODULE.MISSING", [page_id, ident], "图元缺少明确模块归属")
            elif mid in modules and modules[mid]["page_id"] != page_id:
                issue("BLOCK", "MODULE.PAGE", [page_id, ident], "图元位于所属模块以外的页面")
            if kind == "component":
                key = component_key(item)
                if key in actual:
                    raise ValueError("实际器件单元重复：" + key)
                actual[key] = (page_id, item)
                if key in expected and mid != expected[key]["module_id"]:
                    issue("BLOCK", "COMPONENT.OWNER", [key], "实际模块归属与项目规格不一致")
            if kind == "section" or (kind == "annotation" and item.get("role") == "module_title"):
                target = frames if kind == "section" else titles
                if mid in target:
                    issue("BLOCK", "MODULE.DUPLICATE", [str(mid)], "模块存在重复边框或标题")
                target[mid] = (page_id, item)
            if kind == "stub":
                pair = (text(item.get("component_key")), text(item.get("pin_number")))
                if pair in stubs:
                    raise ValueError("每个引脚声明一条引出 Stub，后续路径记录为 wire")
                stubs[pair] = (page_id, item)
            if kind == "label":
                labels.append(item)
            if item.get("parent_id"):
                parent = page_items.get(item["parent_id"])
                if parent is None or parent.get("module_id") != mid:
                    issue("BLOCK", "LABEL.PARENT", [page_id, ident], "标签父对象缺失或模块归属不同")
            items[(page_id, ident)] = item
        for i, a in enumerate(labels):
            aa = a["bbox"]
            expanded = [aa[0]-gap, aa[1]-gap, aa[2]+gap, aa[3]+gap]
            for b in labels[i+1:]:
                if overlap(expanded, b["bbox"]):
                    issue("BLOCK", "LABEL.GAP", [page_id, a["id"], b["id"]], "标签 BBox 间隔低于项目要求（保守矩形筛查）")
        _erc(page.get("erc"), [page_id], issue)
        review = page.get("visual_review", {})
        if (review.get("status") != "reviewed" or any(
                not isinstance(review.get(k), list) or not review[k] or
                any(not isinstance(v, str) or not v.strip() for v in review[k])
                for k in ("capture_refs", "observations"))):
            issue("NEEDS_EVIDENCE", "VISUAL.MISSING", [page_id], "需要总览/局部图的目视记录；本工具不验证图像内容")
    for mid, module in modules.items():
        if module["frame_required"] and mid not in frames:
            issue("NEEDS_EVIDENCE", "MODULE.FRAME", [mid], "缺模块边框实测")
        if module["title_required"] and mid not in titles:
            issue("NEEDS_EVIDENCE", "MODULE.TITLE", [mid], "缺模块标题实测")
        elif mid in titles and titles[mid][1].get("content") != module["title"]:
            issue("BLOCK", "MODULE.TITLE_TEXT", [mid], "实际模块标题与项目规格不一致")
        if mid not in frames:
            continue
        frame = frames[mid][1]["bbox"]
        inset = [frame[0]+padding, frame[1]+padding, frame[2]-padding, frame[3]-padding]
        if inset[0] >= inset[2] or inset[1] >= inset[3]:
            issue("BLOCK", "MODULE.CAPACITY", [mid], "模块尺寸容纳不了声明的内边距")
        for (page_id, ident), item in items.items():
            if item.get("module_id") == mid and item["kind"] != "section" and not (
                    item["kind"] == "wire" and item.get("interface_id") in interfaces):
                if not within(item["bbox"], inset):
                    issue("BLOCK", "MODULE.CONTAINMENT", [mid, ident], "成员/标签/标题侵入模块边距或越框")
        parent = module.get("parent_id")
        if parent in frames and not within(frame, frames[parent][1]["bbox"]):
            issue("BLOCK", "MODULE.PARENT", [mid, parent], "子模块边框越出父模块")
        for other, other_module in modules.items():
            if other > mid and other in frames and module["page_id"] == other_module["page_id"]:
                if parent == other_module.get("parent_id") and overlap(frame, frames[other][1]["bbox"]):
                    issue("BLOCK", "MODULE.OVERLAP", [mid, other], "同级模块边框非法重叠")
    if set(expected) != set(actual):
        issue("BLOCK", "COMPONENT.SET", [], "实际器件单元集合与规格不一致")
    pin_count = 0
    for key in set(expected) & set(actual):
        page_id, item = actual[key]
        planned = records(expected[key]["pins"], "number", nonempty=True)
        got = records(item.get("pins"), "number", nonempty=True)
        if set(planned) != set(got):
            issue("BLOCK", "PIN.SET", [key], "实际引脚清单与规格不一致，不能只验证已列连接点")
        for pin_no, wanted in planned.items():
            pin_count += 1
            if wanted["state"] == "unresolved":
                issue("NEEDS_EVIDENCE", "PIN.UNRESOLVED", [key, pin_no], "引脚用途未决定，禁止自动转成 NC")
                continue
            if pin_no not in got:
                continue
            pin = got[pin_no]
            if not isinstance(pin.get("no_connect"), bool):
                issue("NEEDS_EVIDENCE", "PIN.NC_UNKNOWN", [key, pin_no], "缺原生 NC 状态")
            elif wanted["state"] == "nc":
                if pin.get("net") or pin["no_connect"] is not True:
                    issue("BLOCK", "PIN.NC", [key, pin_no], "主动悬空状态与实际网络/NC 不一致")
            elif (pin.get("net") != wanted["net"] or pin.get("net_scope") != wanted["net_scope"] or pin["no_connect"]):
                issue("BLOCK", "PIN.NET", [key, pin_no], "网络名、作用域或 NC 状态不符合规格")
            if wanted["state"] == "connected" and "stub" in required and (key, pin_no) not in stubs:
                issue("NEEDS_EVIDENCE", "STUB.MISSING", [key, pin_no], "缺该引脚的通道证据，零 Stub 对象不等于零冲突")
            elif wanted["state"] == "connected" and (key, pin_no) in stubs:
                stub_page, stub = stubs[(key, pin_no)]
                segment = stub.get("segment")
                if (not isinstance(segment, list) or len(segment) != 4 or any(
                        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in segment)):
                    issue("NEEDS_EVIDENCE", "STUB.SEGMENT", [key, pin_no], "缺 Stub 实际线段")
                elif segment[:2] == segment[2:] or not all(
                        stub["bbox"][0] <= segment[i] <= stub["bbox"][2] and
                        stub["bbox"][1] <= segment[i+1] <= stub["bbox"][3] for i in (0, 2)):
                    issue("NEEDS_EVIDENCE", "STUB.GEOMETRY", [key, pin_no], "Stub 退化或端点不在其实测 BBox 内")
                elif (stub_page != page_id or stub.get("module_id") != item.get("module_id") or
                      stub.get("net") != wanted["net"] or stub.get("net_scope") != wanted["net_scope"]):
                    issue("BLOCK", "STUB.OWNER", [key, pin_no], "Stub 的页、模块或网络不符")
                elif any(isinstance(pin.get(k), bool) or not isinstance(pin.get(k), (int, float)) or
                         not math.isfinite(pin[k]) for k in ("x", "y")):
                    issue("NEEDS_EVIDENCE", "STUB.PIN_POSITION", [key, pin_no], "缺实际引脚坐标，无法验证 Stub 接触")
                elif not any(all(math.isclose(v, pin[k], rel_tol=0, abs_tol=1e-7)
                                 for v, k in zip(segment[offset:offset+2], ("x", "y"))) for offset in (0, 2)):
                    issue("BLOCK", "STUB.CONTACT", [key, pin_no], "Stub 端点不在实际引脚上")
        for stub_key, stub_pin in stubs:
            if stub_key == key and (stub_pin not in planned or planned[stub_pin]["state"] != "connected"):
                issue("BLOCK", "STUB.PIN", [key, stub_pin], "Stub 指向未登记或非连接引脚")
    for key, pin_no in stubs:
        if key not in actual:
            issue("BLOCK", "STUB.COMPONENT", [key, pin_no], "Stub 指向不存在的器件单元")
    registered = set()
    for ident, interface in interfaces.items():
        text(interface.get("net"))
        scope = interface.get("net_scope")
        if scope not in SCOPES:
            raise ValueError("接口需要明确网络作用域")
        endpoints = interface.get("endpoints")
        if not isinstance(endpoints, list) or len(endpoints) < 2:
            raise ValueError("模块接口至少两个端点，可为多点网络")
        endpoint_pages = set()
        for endpoint in endpoints:
            mid = endpoint.get("module_id")
            if mid not in modules:
                raise ValueError("接口模块不存在")
            page_id = modules[mid]["page_id"]
            pair = (page_id, text(endpoint.get("port_id")))
            if pair in registered:
                issue("BLOCK", "INTERFACE.DUPLICATE", [ident], "同一端口重复登记")
            registered.add(pair)
            port = items.get(pair)
            if not port or port.get("kind") != "port":
                issue("NEEDS_EVIDENCE", "INTERFACE.PORT", [ident, pair[1]], "接口端口缺实际回读")
            elif (port.get("module_id") != mid or port.get("net") != interface["net"] or port.get("net_scope") != scope):
                issue("BLOCK", "INTERFACE.NET", [ident, pair[1]], "端口归属、网络或作用域不一致")
            if port and (not endpoint.get("native_type") or not port.get("native_type")):
                issue("NEEDS_EVIDENCE", "INTERFACE.TYPE", [ident, pair[1]], "需记录真实端口类型，不能由图形外观推断")
            elif port and endpoint["native_type"] != port["native_type"]:
                issue("BLOCK", "INTERFACE.TYPE", [ident, pair[1]], "端口类型不符合项目声明")
            endpoint_pages.add(page_id)
        if len(endpoint_pages) > 1 and scope != "project":
            issue("BLOCK", "INTERFACE.SCOPE", [ident], "跨页同名局部网络不能视作连通")
    for pair, item in items.items():
        if item["kind"] == "port" and pair not in registered:
            issue("NEEDS_EVIDENCE", "INTERFACE.UNREGISTERED", [pair[0], pair[1]], "原生端口没有接口登记")
    _erc(evidence.get("project_erc"), ["project"], issue)
    return finish(issues, {"pages": len(actual_pages), "modules": len(modules), "components": len(actual), "pins_checked": pin_count})


def _erc(value, objects, issue):
    if not isinstance(value, dict) or value.get("source") != "native_erc" or value.get("completed") is not True:
        issue("NEEDS_EVIDENCE", "ERC.MISSING", objects, "缺完成的原生 ERC 分级记录")
        return
    for key in ("fatal", "error", "warning", "information"):
        count = value.get(key)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            issue("NEEDS_EVIDENCE", "ERC.INVALID", objects, "ERC 计数不完整或非法")
        elif count and key in ("fatal", "error"):
            issue("BLOCK", "ERC.ERROR", objects, "原生 ERC 存在致命/错误项")
        elif count and key == "warning":
            issue("WARN", "ERC.WARNING", objects, "原生 ERC 警告仍需评审，不等同零警告")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, help="项目原理图规格 JSON")
    parser.add_argument("--evidence", required=True, help="归一化原理图回读证据 JSON")
    parser.add_argument("--json-out", help="完整报告，拒绝覆盖已有文件")
    args = parser.parse_args(argv)
    try:
        raw = [Path(p).read_bytes() for p in (args.spec, args.evidence)]
        report = audit(*(json.loads(b.decode("utf-8")) for b in raw))
        report["input_sha256"] = dict(zip(("spec", "evidence"), (hashlib.sha256(b).hexdigest() for b in raw)))
        if args.json_out:
            with Path(args.json_out).open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report["overall"] == "BLOCKED" else 2 if report["overall"] == "NEEDS_EVIDENCE" else 0
    except (OSError, ValueError) as exc:
        print("NEEDS_EVIDENCE: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    sys.exit(main())

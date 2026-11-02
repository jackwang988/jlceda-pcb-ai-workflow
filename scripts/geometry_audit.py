#!/usr/bin/env python3
"""Read-only schematic/PCB geometry preflight on measured EDA JSON.

Exit 0 = no blocker/unknown (warnings allowed); 1 = hard violation;
2 = missing or invalid evidence. Not an ERC/DRC or layout solver.
"""
import argparse
import json
import math
import sys
from pathlib import Path

RULES = Path(__file__).resolve().parents[1] / "data" / "design-rules.json"
UNITS = {"schematic": "sch_api_10mil", "pcb": "pcb_mil"}
DIRECTIONS = {"top": "up", "bottom": "down", "left": "left", "right": "right"}
SCH_SOLIDS = {"component", "label", "port", "title_block", "annotation"}
PCB_SOLIDS = {"component", "mounting_hole", "mechanical"}


def box(value):
    if (not isinstance(value, list) or len(value) != 4 or
            any(isinstance(x, bool) or not isinstance(x, (float, int)) or
                not math.isfinite(x) for x in value)):
        raise ValueError("bbox 必须是四个有限数字")
    if value[0] >= value[2] or value[1] >= value[3]:
        raise ValueError("bbox 宽高必须为正")
    return value


def overlap(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def within(a, b):
    return a[0] >= b[0] and a[1] >= b[1] and a[2] <= b[2] and a[3] <= b[3]


def area(b):
    return (b[2] - b[0]) * (b[3] - b[1])


def crossing(a, b):
    def cross(p, q, r):
        return (q[0]-p[0])*(r[1]-p[1]) - (q[1]-p[1])*(r[0]-p[0])
    p, q, r, t = a[:2], a[2:], b[:2], b[2:]
    c1, c2, c3, c4 = cross(p, q, r), cross(p, q, t), cross(r, t, p), cross(r, t, q)
    return c1*c2 < 0 and c3*c4 < 0


def wire_hits_body(seg, rect):
    """Liang-Barsky segment clipping; tangent to edge does not count."""
    if (not isinstance(seg, list) or len(seg) != 4 or
            any(isinstance(x, bool) or not isinstance(x, (float, int)) or
                not math.isfinite(x) for x in seg)):
        raise ValueError("wire.segment 必须为四个有限坐标")
    x1, y1, x2, y2 = seg
    dx, dy = x2-x1, y2-y1
    lower, upper = 0.0, 1.0
    for p, q in zip((-dx, dx, -dy, dy),
                    (x1-rect[0], rect[2]-x1, y1-rect[1], rect[3]-y1)):
        if abs(p) < 1e-12:
            if q < 0:
                return False
        else:
            t = q/p
            if p < 0:
                lower = max(lower, t)
            else:
                upper = min(upper, t)
            if lower > upper:
                return False
    if upper-lower < 1e-9:
        return False
    t = (lower + upper)/2
    return rect[0] < x1+dx*t < rect[2] and rect[1] < y1+dy*t < rect[3]


def audit(data):
    if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("domain") not in UNITS:
        raise ValueError("schema_version=1 和 domain=schematic|pcb 必填")
    domain = data["domain"]
    if data.get("unit") != UNITS[domain]:
        raise ValueError("单位不匹配：" + UNITS[domain])
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("items 必须为数组")
    issues = []

    def issue(severity, code, ids, detail):
        issues.append({"severity": severity, "code": code, "ids": list(ids), "detail": detail})

    if data.get("capture_source") != "eda_readback":
        issue("NEEDS_EVIDENCE", "CAPTURE.UNVERIFIED", [], "缺少真实 EDA 回读声明；合成数据不能用于项目放行")

    parsed = []
    ids = set()
    for obj in items:
        if not isinstance(obj, dict):
            raise ValueError("items 存在非对象")
        ident, kind = obj.get("id"), obj.get("kind")
        if not isinstance(ident, str) or not ident or ident in ids:
            raise ValueError("图元 ID 必须非空且唯一")
        if not isinstance(kind, str) or not kind:
            raise ValueError(ident + ": kind 缺失")
        ids.add(ident)
        rect = box(obj["bbox"]) if obj.get("bbox") is not None else None
        if rect is None:
            issue("NEEDS_EVIDENCE", "BBOX.MISSING", [ident], "没有实测 BBox")
        if obj.get("bbox_source") != "eda_measured":
            issue("NEEDS_EVIDENCE", "BBOX.UNVERIFIED", [ident], "BBox 无真实 EDA 逐图元回读来源")
        if kind == "wire" and "segment" not in obj:
            issue("NEEDS_EVIDENCE", "WIRE.SEGMENT", [ident], "实际线段端点缺失")
        elif kind == "wire":
            wire_hits_body(obj["segment"], [min(obj["segment"][0],obj["segment"][2])-1,
                min(obj["segment"][1],obj["segment"][3])-1,
                max(obj["segment"][0],obj["segment"][2])+1,
                max(obj["segment"][1],obj["segment"][3])+1])
        parsed.append((obj, rect))

    if domain == "schematic":
        page = box(data["drawable_bbox"]) if data.get("drawable_bbox") is not None else None
        if page is None:
            issue("NEEDS_EVIDENCE", "PAGE.DRAWABLE", [], "缺少扣除图框与标题栏的可用区域")
        for obj, rect in parsed:
            if rect and page and obj["kind"] not in ("frame","section","title_block") and not within(rect,page):
                issue("BLOCK","SCH.PAGE_OVERFLOW",[obj["id"]],"图元超出可绘图区")
        for i, (a, ba) in enumerate(parsed):
            if ba is None:
                continue
            for b, bb in parsed[i+1:]:
                if bb is None or not overlap(ba, bb):
                    continue
                if a["kind"] in SCH_SOLIDS and b["kind"] in SCH_SOLIDS:
                    issue("BLOCK","SCH.SOLID_OVERLAP",[a["id"],b["id"]],"实体占位重叠")
                if (a["kind"] == "stub" and b["kind"] in SCH_SOLIDS) or (
                    b["kind"] == "stub" and a["kind"] in SCH_SOLIDS):
                    issue("BLOCK","SCH.STUB_OBSTRUCTED",[a["id"],b["id"]],"Stub 通道受阻")
        solids = [(o, b) for o,b in parsed if b and o["kind"] in SCH_SOLIDS]
        wires = [o for o,b in parsed if o["kind"] == "wire" and "segment" in o]
        for wire in wires:
            if not wire.get("net"):
                issue("NEEDS_EVIDENCE","SCH.WIRE_NET",[wire["id"]],"缺少 wire.net")
            for target, rect in solids:
                if wire_hits_body(wire["segment"], rect):
                    issue("BLOCK","SCH.WIRE_THROUGH_BODY",
                          [wire["id"],target["id"]],"导线穿过实体内部；端点合法接触不算")
        for i, a in enumerate(wires):
            for b in wires[i+1:]:
                if a.get("net") and b.get("net") and a["net"] != b["net"] and crossing(a["segment"],b["segment"]):
                    issue("WARN","SCH.WIRE_CROSSING",[a["id"],b["id"]],"异网线段交叉，需核对非连接符号和 ERC")
        if page:
            occupancy = sum(area(b) for o,b in solids)/area(page)
        else:
            occupancy = None
        if page and solids:
            weights = [area(b) for o,b in solids]
            x = sum(((b[0]+b[2])/2)*w for (o,b),w in zip(solids,weights))/sum(weights)
            y = sum(((b[1]+b[3])/2)*w for (o,b),w in zip(solids,weights))/sum(weights)
            centroid = [round((x-(page[0]+page[2])/2)/(page[2]-page[0]),4),
                        round((y-(page[1]+page[3])/2)/(page[3]-page[1]),4)]
        else:
            centroid = None
        metrics = {"solid_bbox_occupancy_ratio":round(occupancy,4) if occupancy is not None else None,
                   "visual_centroid_offset_xy":centroid,
                   "component_count":sum(o["kind"] == "component" for o,b in parsed)}
        rules = json.loads(RULES.read_text(encoding="utf-8"))
        if occupancy is not None and occupancy > rules["schematic"]["page_occupancy_suggest_at"]:
            issue("SUGGEST","SCH.PAGE_CAPACITY",[],"几何占用偏高，建议评估按功能分页；不自动强制分页")
    else:
        board = box(data["board_bbox"]) if data.get("board_bbox") is not None else None
        if board is None:
            issue("NEEDS_EVIDENCE","PCB.BOARD",[],"缺少板框 BBox")
        if data.get("board_geometry") != "eda_measured":
            issue("NEEDS_EVIDENCE","PCB.BOARD_GEOMETRY",[],
                  "BBox 无法表示非矩形板轮廓；需 EDA 原生 DRC 和机械证据")
        solids = [(o,b) for o,b in parsed if b and o["kind"] in PCB_SOLIDS]
        for i,(a,ba) in enumerate(solids):
            if board and not within(ba,board):
                if a.get("allow_mechanical_overhang") is True and a.get("overhang_evidence"):
                    issue("WARN","PCB.OVERHANG",[a["id"]],"已声明允许机械外伸，焊盘与插拔净空还需单独验证")
                else:
                    issue("BLOCK","PCB.OFF_BOARD",[a["id"]],"机械实体超出矩形板框")
            for b,bb in solids[i+1:]:
                if a.get("assembly_side","top") == b.get("assembly_side","top") and overlap(ba,bb):
                    issue("BLOCK","PCB.MECHANICAL_OVERLAP",
                          [a["id"],b["id"]],"同一装配面机械 BBox 冲突")
        zones = [(o,b) for o,b in parsed if b and o["kind"] == "keepout"]
        for zone, rect in zones:
            forbid = zone.get("forbid")
            if not isinstance(forbid,list) or not forbid:
                issue("NEEDS_EVIDENCE","PCB.KEEPOUT_SCOPE",[zone["id"]],"禁布区未指定禁止对象")
                continue
            for obj,bb in parsed:
                if obj["id"] == zone["id"] or obj["kind"] not in forbid or bb is None:
                    continue
                if zone.get("layers") is not None:
                    if obj.get("layers") is None:
                        issue("NEEDS_EVIDENCE","PCB.LAYER_UNKNOWN",
                              [zone["id"],obj["id"]],"对象所在层未知")
                        continue
                    if not set(zone["layers"]).intersection(obj["layers"]):
                        continue
                if overlap(rect,bb):
                    issue("BLOCK","PCB.KEEP_OUT",
                          [zone["id"],obj["id"]],"对象侵入禁布区 BBox")
        if any(o.get("role") == "antenna_module" for o,b in parsed) and not any(
                o["kind"] == "keepout" and o.get("role") == "antenna_keepout" for o,b in parsed):
            issue("NEEDS_EVIDENCE","PCB.ANTENNA_KEEPOUT",[],"板载天线模组缺少同步 Keepout")
        for obj,rect in parsed:
            if obj.get("role") not in ("usb_c_receptacle","antenna_module"):
                continue
            edge, direction = obj.get("edge"),obj.get("outward_direction")
            if edge not in DIRECTIONS or direction not in DIRECTIONS.values() or (
                    obj.get("direction_evidence") != "verified_mechanical_geometry"):
                issue("NEEDS_EVIDENCE","PCB.DIRECTION_UNKNOWN",
                      [obj["id"]],"方向需由真实连接器开口/天线外形确认")
            elif DIRECTIONS[edge] != direction:
                issue("BLOCK","PCB.DIRECTION_INWARD",[obj["id"]],"连接器开口/天线朝向板内")
        metrics={"pcb_component_count":sum(o["kind"] == "component" for o,b in parsed),
                 "keepout_count":len(zones)}

    counts = {v:sum(x["severity"] == v for x in issues)
              for v in ("BLOCK","NEEDS_EVIDENCE","WARN","SUGGEST")}
    overall = ("BLOCKED" if counts["BLOCK"] else "NEEDS_EVIDENCE" if counts["NEEDS_EVIDENCE"]
               else "PASS_WITH_WARN" if counts["WARN"] else "PASS_SCOPE_ONLY")
    return {"domain":domain,"overall":overall,"counts":counts,"metrics":metrics,
            "issues":issues,"limitations":[
                "审计仅用于粗筛；必须另外运行原生 ERC/DRC、检查非矩形板及真实三维装配",
                "没有实现 ratsnest、crossings 或可布线性评分，不得声称已测得"]}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",required=True)
    parser.add_argument("--json-out")
    args=parser.parse_args(argv)
    try:
        data=json.loads(Path(args.input).read_text(encoding="utf-8"))
        r=audit(data)
        content=json.dumps(r,ensure_ascii=False,indent=2)+"\n"
        print(content)
        if args.json_out:
            Path(args.json_out).write_text(content,encoding="utf-8")
        return 1 if r["overall"] == "BLOCKED" else 2 if r["overall"] == "NEEDS_EVIDENCE" else 0
    except (ValueError,TypeError,KeyError,OSError) as exc:
        print("BLOCKED: 输入无效："+str(exc),file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
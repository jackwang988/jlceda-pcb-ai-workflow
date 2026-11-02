#!/usr/bin/env python3
"""Synthetic geometry audit tests; this suite does not access the EDA Bridge."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("geometry_audit", ROOT / "scripts" / "geometry_audit.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def obj(ident, kind, bbox, **kwargs):
    return {"id": ident, "kind": kind, "bbox": bbox, "bbox_source": "eda_measured", **kwargs}


def sch(items=None, **kwargs):
    return {"schema_version": 1, "domain": "schematic", "unit": "sch_api_10mil",
            "capture_source": "eda_readback", "drawable_bbox": [0, 0, 200, 150],
            "items": items or [], **kwargs}


def pcb(items=None, **kwargs):
    return {"schema_version": 1, "domain": "pcb", "unit": "pcb_mil",
            "capture_source": "eda_readback", "board_bbox": [0, 0, 200, 100],
            "board_geometry": "eda_measured", "items": items or [], **kwargs}


def codes(report):
    return {x["code"] for x in report["issues"]}


class GeometryAuditTests(unittest.TestCase):
    def test_disjoint_components(self):
        r=mod.audit(sch([obj("U1","component",[10,20,30,40]),obj("U2","component",[40,20,70,40])]))
        self.assertEqual(r["overall"],"PASS_SCOPE_ONLY")

    def test_schematic_body_overlap_block(self):
        r=mod.audit(sch([obj("U1","component",[10,10,40,40]),obj("R1","component",[30,20,50,30])]))
        self.assertIn("SCH.SOLID_OVERLAP",codes(r))

    def test_section_contains_module_not_overlap(self):
        r=mod.audit(sch([obj("A","component",[10,10,30,30]),obj("SEC","section",[5,5,80,60])]))
        self.assertNotIn("SCH.SOLID_OVERLAP",codes(r))

    def test_stub_obstructed(self):
        r=mod.audit(sch([obj("stub1","stub",[30,20,80,40]),obj("U1","component",[50,25,70,45])]))
        self.assertIn("SCH.STUB_OBSTRUCTED",codes(r))

    def test_wire_to_boundary_not_body(self):
        r=mod.audit(sch([obj("U1","component",[30,30,70,70]),
                         obj("w","wire",[10,45,30,45.01],net="3V3",segment=[10,45,30,45])]))
        self.assertNotIn("SCH.WIRE_THROUGH_BODY",codes(r))

    def test_wire_through_body(self):
        r=mod.audit(sch([obj("U1","component",[30,30,70,70]),
                         obj("w","wire",[10,45,90,45.01],net="3V3",segment=[10,45,90,45])]))
        self.assertIn("SCH.WIRE_THROUGH_BODY",codes(r))

    def test_wire_crossing_warns_not_fake_short(self):
        r=mod.audit(sch([obj("w1","wire",[10,30,90,30.01],net="A",segment=[10,30,90,30]),
                         obj("w2","wire",[50,10,50.01,60],net="B",segment=[50,10,50,60])]))
        self.assertIn("SCH.WIRE_CROSSING",codes(r))
        self.assertEqual(r["overall"],"PASS_WITH_WARN")

    def test_visual_centroid_metric_is_not_gate(self):
        r=mod.audit(sch([obj("U1","component",[10,10,30,30])]))
        self.assertIsNotNone(r["metrics"]["visual_centroid_offset_xy"])
        self.assertEqual(r["overall"],"PASS_SCOPE_ONLY")

    def test_wire_missing_network_evidence(self):
        r=mod.audit(sch([obj("w","wire",[10,10,50,10.01],segment=[10,10,50,10])]))
        self.assertIn("SCH.WIRE_NET",codes(r))
        self.assertEqual(r["overall"],"NEEDS_EVIDENCE")

    def test_page_overflow(self):
        r=mod.audit(sch([obj("U1","component",[190,10,210,30])]))
        self.assertIn("SCH.PAGE_OVERFLOW",codes(r))

    def test_page_occupancy_soft(self):
        r=mod.audit(sch([obj("U1","component",[5,5,195,125])]))
        self.assertIn("SCH.PAGE_CAPACITY",codes(r))
        self.assertEqual(r["overall"],"PASS_SCOPE_ONLY")

    def test_missing_real_capture(self):
        d=sch([obj("U1","component",[10,10,30,30])])
        d["capture_source"]="synthetic"
        self.assertEqual(mod.audit(d)["overall"],"NEEDS_EVIDENCE")

    def test_missing_bbox(self):
        r=mod.audit(sch([{"id":"U1","kind":"component","bbox_source":"eda_measured"}]))
        self.assertIn("BBOX.MISSING",codes(r))

    def test_units_refused(self):
        d=sch()
        d["unit"]="pcb_mil"
        with self.assertRaises(ValueError): mod.audit(d)

    def test_bad_nan_bbox(self):
        d=sch([obj("u","component",[0,0,float("nan"),20])])
        with self.assertRaises(ValueError): mod.audit(d)

    def test_duplicate_ids(self):
        d=sch([obj("u","component",[10,10,20,20]),obj("u","component",[40,40,50,50])])
        with self.assertRaises(ValueError): mod.audit(d)

    def test_pcb_collisions(self):
        r=mod.audit(pcb([obj("u","component",[20,20,50,50]),
                         obj("v","component",[40,30,60,50])]))
        self.assertIn("PCB.MECHANICAL_OVERLAP",codes(r))

    def test_opposite_assembly_sides(self):
        r=mod.audit(pcb([obj("u","component",[20,20,50,50],assembly_side="top"),
                         obj("v","component",[30,30,40,40],assembly_side="bottom")]))
        self.assertNotIn("PCB.MECHANICAL_OVERLAP",codes(r))

    def test_offboard_block(self):
        r=mod.audit(pcb([obj("u","component",[-10,20,30,30])]))
        self.assertIn("PCB.OFF_BOARD",codes(r))

    def test_approved_usb_overhang_warn(self):
        r=mod.audit(pcb([obj("J1","component",[-10,20,30,40],
                         allow_mechanical_overhang=True,overhang_evidence="mechanical-datasheet")]))
        self.assertIn("PCB.OVERHANG",codes(r))
        self.assertEqual(r["overall"],"PASS_WITH_WARN")

    def test_antenna_keepout_missing(self):
        r=mod.audit(pcb([obj("U4","component",[20,20,60,50],
                         role="antenna_module",edge="top",outward_direction="up",
                         direction_evidence="verified_mechanical_geometry")]))
        self.assertIn("PCB.ANTENNA_KEEPOUT",codes(r))

    def test_usb_wrong_direction(self):
        r=mod.audit(pcb([obj("J1","component",[2,20,30,50],
                         role="usb_c_receptacle",edge="left",outward_direction="right",
                         direction_evidence="verified_mechanical_geometry")]))
        self.assertIn("PCB.DIRECTION_INWARD",codes(r))

    def test_missing_orientation_evidence(self):
        r=mod.audit(pcb([obj("J1","component",[2,20,30,50],
                         role="usb_c_receptacle",edge="left",outward_direction="left")]))
        self.assertIn("PCB.DIRECTION_UNKNOWN",codes(r))

    def test_keepout_blocks_copper(self):
        zone=obj("RF-KO","keepout",[50,10,100,50],forbid=["copper"],layers=[1],role="antenna_keepout")
        copper=obj("C1","copper",[55,15,75,35],layers=[1])
        self.assertIn("PCB.KEEP_OUT",codes(mod.audit(pcb([zone,copper]))))

    def test_layer_specific_keepout(self):
        zone=obj("K","keepout",[50,10,100,50],forbid=["trace"],layers=[1])
        trace=obj("T","trace",[55,15,75,35],layers=[2])
        self.assertNotIn("PCB.KEEP_OUT",codes(mod.audit(pcb([zone,trace]))))

    def test_missing_layer_needs_evidence(self):
        zone=obj("K","keepout",[50,10,100,50],forbid=["trace"],layers=[1])
        trace=obj("T","trace",[55,15,75,35])
        self.assertIn("PCB.LAYER_UNKNOWN",codes(mod.audit(pcb([zone,trace]))))

    def test_no_unknown_ratsnest_score(self):
        r=mod.audit(pcb())
        self.assertNotIn("routability_score",r["metrics"])
        self.assertNotIn("ratsnest",r["metrics"])

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/"evidence.json"
            report=Path(d)/"report.json"
            src.write_text(json.dumps(sch()),encoding="utf-8")
            p=subprocess.run([sys.executable,str(ROOT/"scripts"/"geometry_audit.py"),
                              "--input",str(src),"--json-out",str(report)],capture_output=True)
            self.assertEqual(p.returncode,0,p.stderr.decode(errors="replace"))
            self.assertTrue(report.exists())
            src.write_text(json.dumps(sch([obj("U","component",[190,10,210,30])])),encoding="utf-8")
            p=subprocess.run([sys.executable,str(ROOT/"scripts"/"geometry_audit.py"),"--input",str(src)],capture_output=True)
            self.assertEqual(p.returncode,1)
            src.write_text(json.dumps(sch([{"id":"U","kind":"component"}])),encoding="utf-8")
            p=subprocess.run([sys.executable,str(ROOT/"scripts"/"geometry_audit.py"),"--input",str(src)],capture_output=True)
            self.assertEqual(p.returncode,2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
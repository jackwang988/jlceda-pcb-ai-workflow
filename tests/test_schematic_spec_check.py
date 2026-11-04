#!/usr/bin/env python3
"""Synthetic schematic-only contracts; no EDA connection or real project data."""
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import schematic_spec_check as check


def erc():
    return {"source": "native_erc", "completed": True, "fatal": 0, "error": 0, "warning": 0, "information": 3}


def recalc(evidence):
    for page in evidence["pages"]:
        counts = Counter(x["kind"] for x in page["items"])
        page["coverage"] = {k: {"complete": True, "count": counts[k]} for k in check.KINDS}


def example():
    spec = {"schema_version": 1, "domain": "schematic", "unit": "sch_api_10mil",
            "project_id": "demo-project", "schematic_id": "demo-schematic",
            "pages": [{"id": "p1", "drawable_bbox": [-10, -10, 240, 110], "forbidden_bboxes": []}],
            "modules": [], "components": [], "interfaces": [],
            "required_geometry": sorted(check.KINDS), "layout": {"module_padding": 2, "label_gap": 2}}
    evidence = {"schema_version": 1, "domain": "schematic", "unit": "sch_api_10mil",
                "project_id": "demo-project", "schematic_id": "demo-schematic",
                "revision": "candidate-a", "capture_source": "eda_readback", "project_erc": erc(),
                "pages": [{"id": "p1", "items": [], "erc": erc(), "visual_review": {
                    "status": "reviewed", "capture_refs": ["overview", "detail"],
                    "observations": ["Synthetic review record, not an actual EDA observation."]}}]}
    for i, (mid, title, offset) in enumerate((("power", "Power", 0), ("io", "I/O", 110)), 1):
        ref = "U" + str(i)
        spec["modules"].append({"id": mid, "title": title, "page_id": "p1", "parent_id": None,
                                "frame_required": True, "title_required": True})
        spec["components"].append({"ref": ref, "subpart": "", "module_id": mid, "pins": [
            {"number": "1", "state": "connected", "net": "BUS", "net_scope": "project"},
            {"number": "2", "state": "nc", "reason": "Synthetic part explicitly leaves this pin unused."}]})
        items = [
            {"id": "frame-"+mid, "kind": "section", "bbox": [offset, 0, offset+100, 70]},
            {"id": "title-"+mid, "kind": "annotation", "role": "module_title", "content": title,
             "bbox": [offset+4, 60, offset+40, 66]},
            {"id": "c-"+mid, "kind": "component", "ref": ref, "bbox": [offset+10, 10, offset+35, 30],
             "pins": [{"number": "1", "net": "BUS", "net_scope": "project", "no_connect": False,
                       "x": offset+35, "y": 20}, {"number": "2", "net": None, "no_connect": True}]},
            {"id": "label-"+mid, "kind": "label", "parent_id": "c-"+mid,
             "bbox": [offset+20, 40, offset+35, 44]},
            {"id": "stub-"+mid, "kind": "stub", "component_key": ref, "pin_number": "1",
             "net": "BUS", "net_scope": "project", "segment": [offset+35, 20, offset+45, 20],
             "bbox": [offset+34, 19, offset+46, 21]},
            {"id": "port-"+mid, "kind": "port", "net": "BUS", "net_scope": "project",
             "native_type": "demo-port", "bbox": [offset+70, 18, offset+82, 24]}]
        for item in items:
            item.update(module_id=mid, bbox_source="eda_measured")
        evidence["pages"][0]["items"].extend(items)
    spec["interfaces"] = [{"id": "bus", "net": "BUS", "net_scope": "project", "endpoints": [
        {"module_id": mid, "port_id": "port-"+mid, "native_type": "demo-port"} for mid in ("power", "io")]}]
    recalc(evidence)
    return spec, evidence


class SchematicSpecTests(unittest.TestCase):
    def setUp(self):
        self.spec, self.evidence = example()

    def item(self, ident):
        return next(x for page in self.evidence["pages"] for x in page["items"] if x["id"] == ident)

    def assert_code(self, code, severity=None):
        report = check.audit(self.spec, self.evidence)
        self.assertTrue(any(x["code"] == code and (severity is None or x["severity"] == severity)
                            for x in report["issues"]), report)
        self.assertNotIn(report["overall"], ("PASS_SCOPE_ONLY", "PASS_WITH_WARN"))

    def split_pages(self):
        self.spec["pages"].append(dict(self.spec["pages"][0], id="p2"))
        self.spec["modules"][1]["page_id"] = "p2"
        first = self.evidence["pages"][0]
        second = copy.deepcopy(first)
        second["id"] = "p2"
        second["items"] = [x for x in first["items"] if x["module_id"] == "io"]
        first["items"] = [x for x in first["items"] if x["module_id"] != "io"]
        self.evidence["pages"].append(second)
        recalc(self.evidence)

    def test_valid_scope(self):
        report = check.audit(self.spec, self.evidence)
        self.assertEqual(report["overall"], "PASS_SCOPE_ONLY")
        self.assertEqual(report["metrics"]["pins_checked"], 4)

    def test_sibling_frames_overlap(self):
        self.item("frame-io")["bbox"] = self.item("frame-power")["bbox"][:]
        self.assert_code("MODULE.OVERLAP")

    def test_long_model_label_outside_module(self):
        self.item("label-power")["bbox"][2] = 106
        self.assert_code("MODULE.CONTAINMENT")

    def test_member_too_close_to_frame(self):
        self.item("c-power")["bbox"][0] = 1
        self.assert_code("MODULE.CONTAINMENT")

    def test_title_wrong_text(self):
        self.item("title-power")["content"] = "Old title"
        self.assert_code("MODULE.TITLE_TEXT")

    def test_title_outside_frame(self):
        self.item("title-power")["bbox"] = [95, 60, 120, 66]
        self.assert_code("MODULE.CONTAINMENT")

    def test_ids_not_array_order_define_membership(self):
        self.evidence["pages"][0]["items"].reverse()
        self.assertEqual(check.audit(self.spec, self.evidence)["overall"], "PASS_SCOPE_ONLY")

    def test_legal_nested_modules(self):
        self.spec["modules"][1]["parent_id"] = "power"
        self.item("frame-power")["bbox"] = [0, 0, 220, 80]
        self.assertEqual(check.audit(self.spec, self.evidence)["overall"], "PASS_SCOPE_ONLY")

    def test_child_outside_parent(self):
        self.spec["modules"][1]["parent_id"] = "power"
        self.assert_code("MODULE.PARENT")

    def test_parent_cycle(self):
        self.spec["modules"][0]["parent_id"] = "io"
        self.spec["modules"][1]["parent_id"] = "power"
        self.assert_code("INPUT.INVALID")

    def test_extra_module_note_not_duplicate_title(self):
        self.evidence["pages"][0]["items"].append({"id": "note", "kind": "annotation", "module_id": "power",
            "content": "A local design note", "bbox": [50, 45, 80, 50], "bbox_source": "eda_measured"})
        recalc(self.evidence)
        self.assertEqual(check.audit(self.spec, self.evidence)["overall"], "PASS_SCOPE_ONLY")

    def test_missing_module_title(self):
        self.evidence["pages"][0]["items"].remove(self.item("title-power"))
        recalc(self.evidence)
        self.assert_code("MODULE.TITLE")

    def test_wrong_component_owner(self):
        self.item("c-power")["module_id"] = "io"
        self.assert_code("COMPONENT.OWNER")

    def test_label_parent_module_mismatch(self):
        self.item("label-power")["parent_id"] = "c-io"
        self.assert_code("LABEL.PARENT")

    def test_titlebar_exclusion(self):
        self.spec["pages"][0]["forbidden_bboxes"] = [[15, 35, 40, 50]]
        self.assert_code("PAGE.BOUNDS")

    def test_label_gap(self):
        label = dict(self.item("label-power"), id="second-label", bbox=[36, 40, 50, 44])
        self.evidence["pages"][0]["items"].append(label)
        recalc(self.evidence)
        self.assert_code("LABEL.GAP")

    def test_missing_inventory_component(self):
        self.evidence["pages"][0]["items"].remove(self.item("c-power"))
        recalc(self.evidence)
        self.assert_code("COMPONENT.SET")

    def test_extra_pin_is_not_ignored(self):
        self.item("c-power")["pins"].append({"number": "3", "no_connect": True})
        self.assert_code("PIN.SET")

    def test_unresolved_must_not_become_nc(self):
        self.spec["components"][0]["pins"][1]["state"] = "unresolved"
        self.assert_code("PIN.UNRESOLVED")

    def test_nc_requires_reason(self):
        self.spec["components"][0]["pins"][1].pop("reason")
        self.assert_code("INPUT.INVALID")

    def test_actual_nc_still_connected(self):
        self.item("c-power")["pins"][1]["net"] = "BUS"
        self.assert_code("PIN.NC")

    def test_actual_nc_unknown(self):
        self.item("c-power")["pins"][1].pop("no_connect")
        self.assert_code("PIN.NC_UNKNOWN")

    def test_wrong_pin_net(self):
        self.item("c-power")["pins"][0]["net"] = "OTHER"
        self.assert_code("PIN.NET")

    def test_wrong_pin_scope(self):
        self.item("c-power")["pins"][0]["net_scope"] = "page"
        self.assert_code("PIN.NET")

    def test_subparts_can_share_ref(self):
        for i, mid in enumerate(("power", "io")):
            unit = chr(ord("A")+i)
            self.spec["components"][i].update(ref="U1", subpart=unit)
            self.item("c-"+mid).update(ref="U1", subpart=unit)
            self.item("stub-"+mid)["component_key"] = "U1."+unit
        self.assertEqual(check.audit(self.spec, self.evidence)["overall"], "PASS_SCOPE_ONLY")

    def test_missing_coverage(self):
        self.evidence["pages"][0]["coverage"].pop("label")
        self.assert_code("COVERAGE.INCOMPLETE")

    def test_declared_count_mismatch(self):
        self.evidence["pages"][0]["coverage"]["component"]["count"] = 1
        self.assert_code("COVERAGE.INCOMPLETE")

    def test_zero_stub_objects_not_zero_conflicts(self):
        self.evidence["pages"][0]["items"] = [x for x in self.evidence["pages"][0]["items"] if x["kind"] != "stub"]
        recalc(self.evidence)
        self.assert_code("STUB.MISSING")

    def test_stub_wrong_net(self):
        self.item("stub-power")["net"] = "OTHER"
        self.assert_code("STUB.OWNER")

    def test_stub_detached_from_pin(self):
        self.item("stub-power")["segment"] = [36, 20, 45, 20]
        self.assert_code("STUB.CONTACT")

    def test_stub_without_pin_position(self):
        self.item("c-power")["pins"][0].pop("x")
        self.assert_code("STUB.PIN_POSITION")

    def test_stub_zero_length_or_unrelated_bbox(self):
        for segment in ([35, 20, 35, 20], [35, 20, 90, 20]):
            with self.subTest(segment=segment):
                self.item("stub-power")["segment"] = segment
                self.assert_code("STUB.GEOMETRY")

    def test_unmeasured_bbox(self):
        self.item("label-power")["bbox_source"] = "estimated"
        self.assert_code("BBOX.UNVERIFIED")

    def test_bad_bbox_values(self):
        for value in (None, [0, 0, float("nan"), 4], [0, 0, 0, 4], [0, 0, True, 4]):
            with self.subTest(value=value):
                original = self.item("label-power")["bbox"]
                self.item("label-power")["bbox"] = value
                self.assert_code("INPUT.INVALID")
                self.item("label-power")["bbox"] = original

    def test_crosspage_project_net(self):
        self.split_pages()
        self.assertEqual(check.audit(self.spec, self.evidence)["overall"], "PASS_SCOPE_ONLY")

    def test_crosspage_local_name_not_connectivity(self):
        self.split_pages()
        self.spec["interfaces"][0]["net_scope"] = "page"
        for mid in ("power", "io"):
            self.item("port-"+mid)["net_scope"] = "page"
        self.assert_code("INTERFACE.SCOPE")

    def test_multidrop_interface(self):
        port = dict(self.item("port-io"), id="third-port", bbox=[185, 32, 200, 38])
        self.evidence["pages"][0]["items"].append(port)
        self.spec["interfaces"][0]["endpoints"].append({"module_id": "io", "port_id": "third-port", "native_type": "demo-port"})
        recalc(self.evidence)
        self.assertEqual(check.audit(self.spec, self.evidence)["overall"], "PASS_SCOPE_ONLY")

    def test_unregistered_port(self):
        self.spec["interfaces"] = []
        self.assert_code("INTERFACE.UNREGISTERED")

    def test_wrong_native_port_type(self):
        self.item("port-power")["native_type"] = "different-type"
        self.assert_code("INTERFACE.TYPE")

    def test_unknown_interface_cannot_bypass_frame(self):
        self.item("label-power")["interface_id"] = "not-registered"
        self.item("label-power")["bbox"] = [99, 40, 120, 44]
        self.assert_code("INPUT.INVALID")

    def test_registered_wire_can_cross_frames(self):
        self.evidence["pages"][0]["items"].append({"id": "link", "kind": "wire", "module_id": "power",
            "interface_id": "bus", "net": "BUS", "net_scope": "project", "bbox": [80, 19, 180, 21], "bbox_source": "eda_measured"})
        recalc(self.evidence)
        self.assertEqual(check.audit(self.spec, self.evidence)["overall"], "PASS_SCOPE_ONLY")

    def test_interface_exception_not_for_unrelated_module(self):
        self.spec["modules"].append({"id": "other", "title": "Other", "page_id": "p1", "parent_id": None,
                                    "frame_required": False, "title_required": False})
        self.evidence["pages"][0]["items"].append({"id": "link", "kind": "wire", "module_id": "other",
            "interface_id": "bus", "net": "BUS", "net_scope": "project", "bbox": [80, 19, 180, 21], "bbox_source": "eda_measured"})
        recalc(self.evidence)
        self.assert_code("INTERFACE.WIRE_SCOPE")

    def test_erc_missing_or_invalid(self):
        for value in (None, False, [], {"completed": True}, dict(erc(), error=True)):
            with self.subTest(value=value):
                self.evidence["pages"][0]["erc"] = value
                report = check.audit(self.spec, self.evidence)
                self.assertEqual(report["overall"], "NEEDS_EVIDENCE", report)

    def test_erc_error_blocks(self):
        self.evidence["pages"][0]["erc"]["error"] = 1
        self.assert_code("ERC.ERROR")

    def test_erc_warning_kept_separate(self):
        self.evidence["pages"][0]["erc"]["warning"] = 1
        self.assertEqual(check.audit(self.spec, self.evidence)["overall"], "PASS_WITH_WARN")

    def test_erc_information_not_error(self):
        self.evidence["pages"][0]["erc"]["information"] = 14
        self.assertEqual(check.audit(self.spec, self.evidence)["overall"], "PASS_SCOPE_ONLY")

    def test_project_erc_required(self):
        self.evidence.pop("project_erc")
        self.assert_code("ERC.MISSING")

    def test_visual_review_required(self):
        self.evidence["pages"][0].pop("visual_review")
        self.assert_code("VISUAL.MISSING")

    def test_visual_list_not_boolean(self):
        self.evidence["pages"][0]["visual_review"]["observations"] = True
        self.assert_code("VISUAL.MISSING")

    def test_scope_mismatch(self):
        self.evidence["schematic_id"] = "another-schematic"
        self.assert_code("SCOPE.MISMATCH")

    def test_wrong_unit_and_non_schematic_refused(self):
        for field, value in (("unit", "raw"), ("domain", "pcb")):
            with self.subTest(field=field):
                old = self.evidence[field]
                self.evidence[field] = value
                self.assert_code("INPUT.INVALID")
                self.evidence[field] = old

    def test_template_is_not_pass_fixture(self):
        self.spec = json.loads((ROOT / "assets/schematic-project.template.json").read_text(encoding="utf-8"))
        self.assert_code("INPUT.INVALID")

    def test_cli_codes_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec, evidence, report = [Path(tmp)/name for name in ("spec.json", "evidence.json", "report.json")]
            spec.write_text(json.dumps(self.spec), encoding="utf-8")
            evidence.write_text(json.dumps(self.evidence), encoding="utf-8")
            original = (spec.read_bytes(), evidence.read_bytes())
            args = ["--spec", str(spec), "--evidence", str(evidence)]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(check.main(args+["--json-out", str(report)]), 0)
                saved = report.read_bytes()
                self.assertEqual(check.main(args+["--json-out", str(report)]), 2)
                self.assertEqual(report.read_bytes(), saved)
                self.assertEqual((spec.read_bytes(), evidence.read_bytes()), original)
                self.evidence["pages"][0]["erc"]["error"] = 1
                evidence.write_text(json.dumps(self.evidence), encoding="utf-8")
                self.assertEqual(check.main(args), 1)
                evidence.write_text("{", encoding="utf-8")
                self.assertEqual(check.main(args), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

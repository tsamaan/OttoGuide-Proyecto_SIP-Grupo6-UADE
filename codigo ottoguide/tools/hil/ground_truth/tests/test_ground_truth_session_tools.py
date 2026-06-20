#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/f"{name}.py");module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
prepare=load("prepare_ground_truth_session");validate=load("validate_ground_truth_session");seal=load("seal_ground_truth_preflight");assess=load("assess_ground_truth_readiness")

class FailSafeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.templates=ROOT/"templates"
    def tearDown(self):self.temp.cleanup()
    def args(self,session_id,route,comparable="PENDING_REVIEW"):
        return argparse.Namespace(session_id=session_id,route_spec=route,created_at="2026-06-20T12:00:00+00:00",operator="OPERATOR_ROLE_A",location="LAB_ZONE_A",ground_truth_level="GT-MIN",experiment_phase="CALIBRATION",initial_orientation_marker="ORIENTATION_NORTH",comparability_status=comparable,sync_method="VISIBLE_SYNC_METHOD",sync_expected_accuracy_s=.05,force=False)
    def copy_events(self,session):
        (session/"ground_truth"/"ground_truth_events.csv").write_bytes((self.templates/"ground_truth_events.example.csv").read_bytes())
    def conservative(self,sealed=True):
        session=prepare.prepare(self.root,self.args("GT_EXAMPLE_001",self.templates/"route_spec.example.json"));self.copy_events(session)
        if sealed:seal.seal(session,self.templates/"hardware_inventory.example.json",self.templates/"human_review.example.json")
        return session
    def go_fixture(self,**overrides):
        route=json.loads((self.templates/"route_spec.example.json").read_text(encoding="utf-8"));route.update(route_id="R3-CAL",origin_marker_id="ORIGIN_A",origin_reference="FLOOR_CENTER_A",distance_instrument="LASER_METER_A",angle_instrument="ANGLE_GAUGE_A",approved_by_role="GT_PROTOCOL_REVIEWER",approval_date="2026-06-20",notes="Synthetic test fixture")
        for segment in route["segments"]:segment["start_marker"]=segment["start_marker"].replace("EXAMPLE","A");segment["end_marker"]=segment["end_marker"].replace("EXAMPLE","A")
        route_path=self.root/f"route_{len(list(self.root.iterdir()))}.json";route_path.write_text(json.dumps(route,sort_keys=True),encoding="utf-8")
        session_id=f"GO_SESSION_{len(list(self.root.iterdir()))}";session=prepare.prepare(self.root,self.args(session_id,route_path,"COMPARABLE"));self.copy_events(session)
        manifest=json.loads((session/"session_manifest.json").read_text(encoding="utf-8"));manifest["physical_readiness_status"]="GO";(session/"session_manifest.json").write_text(json.dumps(manifest,sort_keys=True),encoding="utf-8")
        inventory={"schema_version":"1.0","inventory_id":"INVENTORY_A","inventory_revision":"1","inventory_status":"REVIEWED_READY","reviewed_by_role":"HARDWARE_REVIEWER","reviewed_at":"2026-06-20T12:00:00+00:00","location_scope":"LAB_ZONE_A","valid_for_route_ids":["R3-CAL"],"valid_until":overrides.get("valid_until","2099-06-20T12:00:00+00:00"),"distance_instrument_available":True,"distance_instrument":"LASER_METER_A","distance_accuracy_m":.01,"angle_instrument_available":True,"angle_instrument":"ANGLE_GAUGE_A","angle_accuracy_rad":.02,"floor_markers_available":True,"orientation_marker_available":True,"sync_marker_available":True,"sync_method":"VISIBLE_SYNC_METHOD","sync_expected_accuracy_s":.05,"external_camera_available":False,"camera_support_available":False,"fiducial_marker_available":False,"storage_confirmed":True,"supervised_area_confirmed":True,"safety_observer_confirmed":True,"notes":"Synthetic temporary fixture"}
        inventory.update(overrides.get("inventory",{}));inventory_path=self.root/f"inventory_{session_id}.json";inventory_raw=(json.dumps(inventory,sort_keys=True)).encode();inventory_path.write_bytes(inventory_raw)
        review={"schema_version":"1.0","review_id":"REVIEW_A","review_revision":"1","reviewed_at":"2026-06-20T12:30:00+00:00","reviewed_by_role":"SAFETY_REVIEWER","decision":overrides.get("decision","GO"),"session_id":session_id,"route_id":"R3-CAL","route_revision":"1","route_spec_sha256":manifest["route_spec_sha256"],"hardware_inventory_id":inventory["inventory_id"],"hardware_inventory_revision":inventory["inventory_revision"],"hardware_inventory_sha256":hashlib.sha256(inventory_raw).hexdigest(),"origin_placement_status":overrides.get("origin_status","IN_TOLERANCE"),"origin_position_error_m":overrides.get("position_error",.01),"origin_yaw_error_rad":overrides.get("yaw_error",.01),"sync_plan_reviewed":True,"safety_protocol_reviewed":True,"movement_authorization_reference":overrides.get("authorization","AUTH_RECORD_001"),"notes":"Synthetic temporary fixture"}
        review.update(overrides.get("review",{}));review_path=self.root/f"review_{session_id}.json";review_path.write_text(json.dumps(review,sort_keys=True),encoding="utf-8")
        seal.seal(session,inventory_path,review_path);return session
    def manifest(self,session):return json.loads((session/"session_manifest.json").read_text(encoding="utf-8"))
    def put_manifest(self,session,data):(session/"session_manifest.json").write_text(json.dumps(data,sort_keys=True),encoding="utf-8")
    def cli(self,session):return subprocess.run([sys.executable,str(ROOT/"assess_ground_truth_readiness.py"),str(session)],capture_output=True,text=True,check=False)

    def test_exit_code_go_0(self):self.assertEqual(self.cli(self.go_fixture()).returncode,0)
    def test_exit_code_no_go_2(self):self.assertEqual(self.cli(self.conservative()).returncode,2)
    def test_exit_code_invalid_3(self):
        session=self.conservative();(session/"calibration"/"route_spec.json").write_text("{}",encoding="utf-8");self.assertEqual(self.cli(session).returncode,3)
    def test_inventory_copied(self):self.assertTrue((self.conservative()/"calibration"/"hardware_inventory.json").is_file())
    def test_human_review_copied(self):self.assertTrue((self.conservative()/"calibration"/"human_review.json").is_file())
    def test_inventory_hash(self):
        s=self.conservative();m=self.manifest(s);self.assertEqual(m["hardware_inventory_sha256"],hashlib.sha256((s/m["hardware_inventory"]).read_bytes()).hexdigest())
    def test_review_hash(self):
        s=self.conservative();m=self.manifest(s);self.assertEqual(m["human_review_sha256"],hashlib.sha256((s/m["human_review"]).read_bytes()).hexdigest())
    def test_inventory_modified_after_seal_invalid(self):
        s=self.conservative();(s/"calibration"/"hardware_inventory.json").write_text("{}",encoding="utf-8");self.assertEqual(assess.assess(s)["decision"],"INVALID");self.assertEqual(self.cli(s).returncode,3)
    def test_review_modified_after_seal_invalid(self):
        s=self.conservative();(s/"calibration"/"human_review.json").write_text("{}",encoding="utf-8");self.assertEqual(assess.assess(s)["decision"],"INVALID");self.assertEqual(self.cli(s).returncode,3)
    def test_inventory_expired(self):self.assertEqual(assess.assess(self.go_fixture(valid_until="2020-01-01T00:00:00+00:00"))["decision"],"NO_GO")
    def test_inventory_wrong_route(self):self.assertEqual(assess.assess(self.go_fixture(inventory={"valid_for_route_ids":["R9"]}))["decision"],"NO_GO")
    def test_instrument_mismatch(self):self.assertEqual(assess.assess(self.go_fixture(inventory={"distance_instrument":"OTHER_TOOL"}))["decision"],"NO_GO")
    def test_accuracy_mismatch(self):self.assertEqual(assess.assess(self.go_fixture(inventory={"distance_accuracy_m":.02}))["decision"],"NO_GO")
    def test_sync_method_mismatch(self):self.assertEqual(assess.assess(self.go_fixture(inventory={"sync_method":"OTHER_SYNC"}))["decision"],"NO_GO")
    def mutate_events(self,session,mutation):
        path=session/"ground_truth"/"ground_truth_events.csv"
        with path.open(newline="",encoding="utf-8") as h:rows=list(csv.DictReader(h));fields=rows[0].keys()
        mutation(rows)
        with path.open("w",newline="",encoding="utf-8") as h:w=csv.DictWriter(h,fieldnames=fields);w.writeheader();w.writerows(rows)
    def test_one_sync(self):
        s=self.go_fixture();self.mutate_events(s,lambda r:r.pop(8));self.assertEqual(assess.assess(s)["decision"],"NO_GO")
    def test_initial_sync_missing(self):
        def move_initial(rows):
            marker=rows.pop(1);marker["timestamp_ns"]="2050000000";marker["relative_time_s"]="1.05";rows.insert(2,marker)
        s=self.go_fixture();self.mutate_events(s,move_initial);self.assertEqual(assess.assess(s)["decision"],"NO_GO")
    def test_final_sync_missing(self):
        def move_final(rows):
            marker=rows.pop(8);marker["timestamp_ns"]="70000000000";marker["relative_time_s"]="69.0";rows.insert(7,marker)
        s=self.go_fixture();self.mutate_events(s,move_final);self.assertEqual(assess.assess(s)["decision"],"NO_GO")
    def test_sync_tolerance_excessive(self):
        s=self.go_fixture();self.mutate_events(s,lambda r:r[1].__setitem__("time_tolerance_s","0.06"));self.assertEqual(assess.assess(s)["decision"],"NO_GO")
    def test_comparability_pending(self):
        s=self.go_fixture();m=self.manifest(s);m["comparability_status"]="PENDING_REVIEW";self.put_manifest(s,m);self.assertEqual(assess.assess(s)["decision"],"NO_GO")
    def test_origin_not_reviewed(self):self.assertEqual(assess.assess(self.go_fixture(origin_status="NOT_CHECKED"))["decision"],"NO_GO")
    def test_origin_out_of_tolerance(self):self.assertEqual(assess.assess(self.go_fixture(position_error=.03))["decision"],"NO_GO")
    def test_review_no_go(self):self.assertEqual(assess.assess(self.go_fixture(decision="NO_GO"))["decision"],"NO_GO")
    def test_authorization_placeholder(self):self.assertEqual(assess.assess(self.go_fixture(authorization="AUTHORIZATION_PLACEHOLDER"))["decision"],"NO_GO")
    def test_go_fully_synthetic(self):
        result=assess.assess(self.go_fixture());self.assertTrue(result["ok"]);self.assertTrue(result["physical_ready"]);self.assertEqual(result["decision"],"GO")
    def test_assess_read_only(self):
        s=self.conservative();before={p.relative_to(s):p.read_bytes() for p in s.rglob("*") if p.is_file()};assess.assess(s);after={p.relative_to(s):p.read_bytes() for p in s.rglob("*") if p.is_file()};self.assertEqual(before,after)
    def test_determinism(self):
        s=self.conservative();self.assertEqual(assess.assess(s),assess.assess(s))
    def test_seal_rejects_overwrite(self):
        s=self.conservative()
        with self.assertRaises(FileExistsError):seal.seal(s,self.templates/"hardware_inventory.example.json",self.templates/"human_review.example.json")
    def test_seal_does_not_mark_go(self):self.assertEqual(self.manifest(self.conservative())["physical_readiness_status"],"NOT_REVIEWED")
    def test_schema_unknown_invalid(self):
        s=self.conservative();m=self.manifest(s);m["schema_version"]="9";self.put_manifest(s,m);self.assertEqual(assess.assess(s)["decision"],"INVALID");self.assertEqual(self.cli(s).returncode,3)
    def test_session_id_invalid(self):
        s=self.conservative();m=self.manifest(s);m["session_id"]="OTHER";self.put_manifest(s,m);self.assertEqual(assess.assess(s)["decision"],"INVALID");self.assertEqual(self.cli(s).returncode,3)
    def test_route_hash_invalid(self):
        s=self.conservative();(s/"calibration"/"route_spec.json").write_text("{}",encoding="utf-8");self.assertEqual(assess.assess(s)["decision"],"INVALID");self.assertEqual(self.cli(s).returncode,3)
    def test_review_links_mismatch_no_go(self):self.assertEqual(assess.assess(self.go_fixture(review={"route_revision":"99"}))["decision"],"NO_GO")
    def test_versioned_templates_no_go(self):self.assertEqual(assess.assess(self.conservative())["decision"],"NO_GO")
    def test_no_ros_or_network(self):
        allowed={"__future__","argparse","ast","csv","hashlib","importlib","json","subprocess","sys","tempfile","unittest","shutil","datetime","pathlib","math","os","validate_ground_truth_session"}
        for path in (ROOT/"prepare_ground_truth_session.py",ROOT/"validate_ground_truth_session.py",ROOT/"seal_ground_truth_preflight.py",ROOT/"assess_ground_truth_readiness.py"):
            tree=ast.parse(path.read_text(encoding="utf-8"));imports={n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import)}|{(n.module or '').split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)};self.assertFalse(imports-allowed,f"unexpected imports {imports-allowed}")

if __name__=="__main__":unittest.main(verbosity=2)

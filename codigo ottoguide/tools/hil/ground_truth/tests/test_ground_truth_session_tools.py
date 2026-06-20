#!/usr/bin/env python3
from __future__ import annotations
import argparse,ast,csv,hashlib,importlib.util,json,subprocess,sys,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/f"{name}.py");m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
prepare=load("prepare_ground_truth_session");validate=load("validate_ground_truth_session");assess=load("assess_ground_truth_readiness")

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.route_source=ROOT/"templates"/"route_spec.example.json";self.inventory=ROOT/"templates"/"hardware_inventory.example.json"
        args=argparse.Namespace(session_id="TEST_001",route_spec=self.route_source,created_at="2026-06-20T12:00:00+00:00",operator="OPERATOR_PLACEHOLDER",location="LOCATION_PLACEHOLDER",ground_truth_level="GT-MIN",experiment_phase="CALIBRATION",initial_orientation_marker="NORTH",comparability_status="PENDING_REVIEW",sync_method="VISIBLE_MARKER",sync_expected_accuracy_s=.05,force=False)
        self.session=prepare.prepare(self.root,args);self.manifest_path=self.session/"session_manifest.json";self.events_path=self.session/"ground_truth"/"ground_truth_events.csv";self.route_path=self.session/"calibration"/"route_spec.json";self.write_events(self.valid_rows())
    def tearDown(self):self.tmp.cleanup()
    @staticmethod
    def valid_rows():return [
      [1000000000,0,"E0","SESSION_START","","STATIONARY",0,0,0,.02,.035,"","TEST","start"],
      [1100000000,.1,"E1","SYNC_MARKER","","UNKNOWN","","","","","",.05,"TEST","sync"],
      [2000000000,1,"E2","SEGMENT_START","S00","STATIONARY",0,0,0,.02,.035,"","TEST","s0"],
      [2100000000,1.1,"E3","STATIONARY_START","S00","STATIONARY",0,0,0,.02,.035,"","TEST","still"],
      [62000000000,61,"E4","STATIONARY_END","S00","STATIONARY",0,0,0,.02,.035,"","TEST","still end"],
      [62100000000,61.1,"E5","SEGMENT_END","S00","STATIONARY",0,0,0,.02,.035,"","TEST","s0 end"],
      [63000000000,62,"E6","SEGMENT_START","S01","TRANSLATING",0,0,0,.02,.035,"","TEST","s1"],
      [73000000000,72,"E7","SEGMENT_END","S01","STATIONARY",1,0,0,.02,.035,"","TEST","s1 end"],
      [73100000000,72.1,"E8","SYNC_MARKER","","UNKNOWN","","","","","",.05,"TEST","sync"],
      [74000000000,73,"E9","SESSION_END","","STATIONARY",1,0,0,.02,.035,"","TEST","end"]]
    def write_events(self,rows):
        with self.events_path.open("w",newline="",encoding="utf-8") as h:w=csv.writer(h);w.writerow(prepare.EVENT_COLUMNS);w.writerows(rows)
    def manifest(self):return json.loads(self.manifest_path.read_text(encoding="utf-8"))
    def put_manifest(self,d):self.manifest_path.write_text(json.dumps(d),encoding="utf-8")
    def route(self):return json.loads(self.route_path.read_text(encoding="utf-8"))
    def put_route(self,d,rehash=True):
        self.route_path.write_text(json.dumps(d,sort_keys=True),encoding="utf-8")
        if rehash:
            m=self.manifest();m["route_spec_sha256"]=hashlib.sha256(self.route_path.read_bytes()).hexdigest();self.put_manifest(m)
    def report(self,inventory=None):return validate.validate(self.session,inventory)
    def mutate_manifest(self,key,value):m=self.manifest();m[key]=value;self.put_manifest(m)

    def test_schema_valid(self):self.assertTrue(self.report()["ok"])
    def test_unknown_schema(self):self.mutate_manifest("schema_version","2.0");self.assertFalse(self.report()["ok"])
    def test_tooling_version_recorded(self):self.assertEqual(self.manifest()["tooling_version"],"1.0")
    def test_session_id_mismatch(self):self.mutate_manifest("session_id","OTHER");self.assertFalse(self.report()["ok"])
    def test_created_at_without_timezone(self):self.mutate_manifest("created_at","2026-06-20T12:00:00");self.assertFalse(self.report()["ok"])
    def test_created_at_invalid(self):self.mutate_manifest("created_at","bad");self.assertFalse(self.report()["ok"])
    def test_route_valid(self):self.assertEqual(self.report()["errors"],[])
    def test_route_hash_bad(self):self.mutate_manifest("route_spec_sha256","0"*64);self.assertFalse(self.report()["ok"])
    def test_route_id_mismatch(self):self.mutate_manifest("route_id","R9");self.assertFalse(self.report()["ok"])
    def test_route_revision_mismatch(self):self.mutate_manifest("route_revision","9");self.assertFalse(self.report()["ok"])
    def test_expected_segments_duplicate(self):self.mutate_manifest("expected_segments",["S00","S00"]);self.assertFalse(self.report()["ok"])
    def test_unexpected_segment(self):
        rows=self.valid_rows();rows[7][4]="S99";self.write_events(rows);self.assertFalse(self.report()["ok"])
    def test_repeated_segment(self):
        rows=self.valid_rows();rows[8:8]=[[73050000000,72.05,"EX","SEGMENT_START","S01","TRANSLATING",0,0,0,.02,.035,"","TEST","repeat"],[73060000000,72.06,"EY","SEGMENT_END","S01","STATIONARY",1,0,0,.02,.035,"","TEST","repeat"]];self.write_events(rows);self.assertFalse(self.report()["ok"])
    def test_new_csv_valid(self):self.assertEqual(self.report()["stats"],{"event_count":10,"segment_count":2})
    def test_negative_tolerance(self):rows=self.valid_rows();rows[7][9]=-.1;self.write_events(rows);self.assertFalse(self.report()["ok"])
    def test_nonfinite_tolerance(self):rows=self.valid_rows();rows[7][9]="nan";self.write_events(rows);self.assertFalse(self.report()["ok"])
    def test_sync_without_time_tolerance(self):rows=self.valid_rows();rows[1][11]="";self.write_events(rows);self.assertFalse(self.report()["ok"])
    def test_manifest_accuracy_invalid(self):self.mutate_manifest("distance_accuracy_m",-1);self.assertFalse(self.report()["ok"])
    def test_inventory_incomplete(self):
        p=self.root/"bad.json";p.write_text("{}",encoding="utf-8");self.assertFalse(self.report(p)["ok"])
    def test_readiness_not_reviewed(self):
        r=assess.assess(self.session,self.inventory);self.assertTrue(r["ok"]);self.assertFalse(r["physical_ready"]);self.assertEqual(r["decision"],"NO_GO")
    def test_readiness_no_go(self):self.mutate_manifest("physical_readiness_status","NO_GO");self.assertEqual(assess.assess(self.session,self.inventory)["decision"],"NO_GO")
    def test_readiness_go_all_requirements(self):
        route=self.route();route["approval_date"]="2026-06-20";self.put_route(route);m=self.manifest();m["physical_readiness_status"]="GO";self.put_manifest(m)
        hw=json.loads(self.inventory.read_text(encoding="utf-8"));
        for k in ("distance_instrument_available","angle_instrument_available","floor_markers_available","orientation_marker_available","sync_marker_available","storage_confirmed","supervised_area_confirmed","safety_observer_confirmed"):hw[k]=True
        hw.update(distance_instrument="MEASURED_TOOL",distance_accuracy_m=.01,angle_instrument="MEASURED_ANGLE_TOOL",angle_accuracy_rad=.02,sync_method="VISIBLE_MARKER",sync_expected_accuracy_s=.05)
        p=self.root/"go.json";p.write_text(json.dumps(hw),encoding="utf-8");r=assess.assess(self.session,p);self.assertTrue(r["physical_ready"]);self.assertEqual(r["decision"],"GO")
    def test_readiness_read_only(self):
        before={p.relative_to(self.session):p.read_bytes() for p in self.session.rglob("*") if p.is_file()};assess.assess(self.session,self.inventory);after={p.relative_to(self.session):p.read_bytes() for p in self.session.rglob("*") if p.is_file()};self.assertEqual(before,after)
    def test_determinism(self):self.assertEqual(self.report(),self.report());self.assertEqual(assess.assess(self.session,self.inventory),assess.assess(self.session,self.inventory))
    def test_overwrite_rejected(self):
        a=argparse.Namespace(session_id="TEST_001",route_spec=self.route_source,created_at="x",operator="x",location="x",ground_truth_level="GT-MIN",experiment_phase="CALIBRATION",initial_orientation_marker="x",comparability_status="PENDING_REVIEW",sync_method="x",sync_expected_accuracy_s=.05,force=False)
        with self.assertRaises(FileExistsError):prepare.prepare(self.root,a)
    def test_path_traversal_rejected(self):
        a=argparse.Namespace(session_id="../x",route_spec=self.route_source,created_at="x",operator="x",location="x",ground_truth_level="GT-MIN",experiment_phase="CALIBRATION",initial_orientation_marker="x",comparability_status="PENDING_REVIEW",sync_method="x",sync_expected_accuracy_s=.05,force=False)
        with self.assertRaises(ValueError):prepare.prepare(self.root,a)
    def test_nonmonotonic(self):rows=self.valid_rows();rows[5][0]=2000000000;self.write_events(rows);self.assertFalse(self.report()["ok"])
    def test_duplicate_event(self):rows=self.valid_rows();rows[5][2]="E4";self.write_events(rows);self.assertFalse(self.report()["ok"])
    def test_bad_event_type(self):rows=self.valid_rows();rows[2][3]="BAD";self.write_events(rows);self.assertFalse(self.report()["ok"])
    def test_bad_state(self):rows=self.valid_rows();rows[2][5]="MOVING";self.write_events(rows);self.assertFalse(self.report()["ok"])
    def test_start_without_end(self):rows=self.valid_rows();del rows[7];self.write_events(rows);self.assertFalse(self.report()["ok"])
    def test_end_without_start(self):rows=self.valid_rows();del rows[6];self.write_events(rows);self.assertFalse(self.report()["ok"])
    def test_missing_reference(self):self.mutate_manifest("external_video","external/missing.mp4");self.assertFalse(self.report()["ok"])
    def test_json_cli(self):
        r=subprocess.run([sys.executable,str(ROOT/"validate_ground_truth_session.py"),str(self.session)],capture_output=True,text=True);self.assertEqual(r.returncode,0);self.assertTrue(json.loads(r.stdout)["ok"])
    def test_no_ros_or_network(self):
        allowed={"__future__","argparse","ast","csv","hashlib","importlib","json","subprocess","sys","tempfile","unittest","shutil","datetime","pathlib","math","validate_ground_truth_session"}
        for p in (ROOT/"prepare_ground_truth_session.py",ROOT/"validate_ground_truth_session.py",ROOT/"assess_ground_truth_readiness.py"):
            tree=ast.parse(p.read_text(encoding="utf-8"));imports={n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import)}|{(n.module or '').split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)};self.assertFalse(imports-allowed)

if __name__=="__main__":unittest.main(verbosity=2)

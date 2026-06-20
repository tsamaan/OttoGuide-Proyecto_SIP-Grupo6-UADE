#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


prepare = load("prepare_ground_truth_session")
validate = load("validate_ground_truth_session")


class GroundTruthToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        args = argparse.Namespace(session_id="TEST_001", created_at="2026-06-20T12:00:00+00:00", operator="OPERATOR_PLACEHOLDER", location="LOCATION_PLACEHOLDER", ground_truth_level="GT-MIN", experiment_phase="CALIBRATION", route_id="R1", motion_domain="TRANSLATIONAL", origin_marker_id="O1", initial_orientation_marker="NORTH", comparability_status="COMPARABLE", force=False)
        self.session = prepare.prepare(self.root, args)
        self.manifest_path = self.session / "session_manifest.json"; self.events_path = self.session / "ground_truth" / "ground_truth_events.csv"
        self.write_events(self.valid_rows())

    def tearDown(self): self.tmp.cleanup()

    @staticmethod
    def valid_rows():
        return [
            [1000000000,0.0,"E0","SESSION_START","","STATIONARY",0,0,0,0.02,"TEST","start"],
            [1100000000,0.1,"E1","SYNC_MARKER","","UNKNOWN","","","",0.05,"TEST","sync"],
            [2000000000,1.0,"E2","SEGMENT_START","S1","TRANSLATING",0,0,0,0.02,"TEST","segment"],
            [3000000000,2.0,"E3","SEGMENT_END","S1","STATIONARY",1,0,0,0.02,"TEST","stop"],
            [4000000000,3.0,"E4","SESSION_END","","STATIONARY",1,0,0,0.02,"TEST","end"],
        ]

    def write_events(self, rows):
        with self.events_path.open("w", newline="", encoding="utf-8") as handle:
            writer=csv.writer(handle); writer.writerow(prepare.EVENT_COLUMNS); writer.writerows(rows)

    def manifest(self): return json.loads(self.manifest_path.read_text(encoding="utf-8"))
    def write_manifest(self, data): self.manifest_path.write_text(json.dumps(data), encoding="utf-8")

    def test_correct_structure(self):
        self.assertTrue(validate.validate(self.session)["ok"]); self.assertTrue(all((self.session/x).is_dir() for x in prepare.SESSION_DIRS))

    def test_overwrite_rejected(self):
        args=argparse.Namespace(session_id="TEST_001", created_at="x", operator="x", location="x", ground_truth_level="GT-MIN", experiment_phase="CALIBRATION", route_id="R1", motion_domain="X", origin_marker_id="O", initial_orientation_marker="I", comparability_status="PENDING_REVIEW", force=False)
        with self.assertRaises(FileExistsError): prepare.prepare(self.root,args)

    def test_unsafe_session_id_rejected(self):
        args=argparse.Namespace(session_id="../escape", created_at="x", operator="x", location="x", ground_truth_level="GT-MIN", experiment_phase="CALIBRATION", route_id="R1", motion_domain="X", origin_marker_id="O", initial_orientation_marker="I", comparability_status="PENDING_REVIEW", force=False)
        with self.assertRaises(ValueError): prepare.prepare(self.root,args)

    def test_valid_manifest(self): self.assertTrue(validate.validate(self.session)["ok"])

    def test_missing_manifest_field(self):
        data=self.manifest(); del data["route_id"]; self.write_manifest(data); self.assertFalse(validate.validate(self.session)["ok"])

    def test_invalid_experiment_phase(self): self.mutate_enum("experiment_phase","INVALID")
    def test_invalid_ground_truth_level(self): self.mutate_enum("ground_truth_level","INVALID")
    def test_invalid_comparability(self): self.mutate_enum("comparability_status","INVALID")

    def mutate_enum(self,key,value):
        data=self.manifest(); data[key]=value; self.write_manifest(data); self.assertFalse(validate.validate(self.session)["ok"])

    def test_valid_csv(self): self.assertEqual(validate.validate(self.session)["stats"]["event_count"],5)

    def test_non_monotonic_timestamps(self):
        rows=self.valid_rows(); rows[3][0]=1500000000; self.write_events(rows); self.assertFalse(validate.validate(self.session)["ok"])

    def test_duplicate_event_id(self):
        rows=self.valid_rows(); rows[3][2]="E2"; self.write_events(rows); self.assertFalse(validate.validate(self.session)["ok"])

    def test_invalid_event_type(self):
        rows=self.valid_rows(); rows[2][3]="BAD"; self.write_events(rows); self.assertFalse(validate.validate(self.session)["ok"])

    def test_invalid_expected_state(self):
        rows=self.valid_rows(); rows[2][5]="MOVING"; self.write_events(rows); self.assertFalse(validate.validate(self.session)["ok"])

    def test_start_without_end(self):
        rows=self.valid_rows(); del rows[3]; self.write_events(rows); self.assertFalse(validate.validate(self.session)["ok"])

    def test_end_without_start(self):
        rows=self.valid_rows(); del rows[2]; self.write_events(rows); self.assertFalse(validate.validate(self.session)["ok"])

    def test_overlapping_segments(self):
        rows=self.valid_rows(); rows[3:3]=[[2500000000,1.5,"EX","SEGMENT_START","S2","ROTATING",0.5,0,0,0.03,"TEST","overlap"],[2750000000,1.75,"EY","SEGMENT_END","S2","STATIONARY",0.5,0,1.57,0.03,"TEST","overlap"]]; self.write_events(rows); self.assertFalse(validate.validate(self.session)["ok"])

    def test_missing_referenced_file(self):
        data=self.manifest(); data["external_video"]="external/missing.mp4"; self.write_manifest(data); self.assertFalse(validate.validate(self.session)["ok"])

    def test_json_output_and_exit_code(self):
        result=subprocess.run([sys.executable,str(ROOT/"validate_ground_truth_session.py"),str(self.session)],capture_output=True,text=True,check=False)
        self.assertEqual(result.returncode,0); self.assertTrue(json.loads(result.stdout)["ok"])

    def test_determinism(self): self.assertEqual(validate.validate(self.session),validate.validate(self.session))

    def test_no_ros_or_network_dependencies(self):
        allowed={"__future__","argparse","csv","json","shutil","datetime","pathlib","math"}
        for path in (ROOT/"prepare_ground_truth_session.py",ROOT/"validate_ground_truth_session.py"):
            tree=ast.parse(path.read_text(encoding="utf-8")); imports={n.names[0].name.split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.Import)}|{(n.module or '').split('.')[0] for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}
            self.assertFalse(imports-allowed, f"unexpected dependencies: {imports-allowed}")


if __name__ == "__main__": unittest.main(verbosity=2)

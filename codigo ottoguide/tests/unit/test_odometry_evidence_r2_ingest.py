"""Unit tests for src.navigation.odometry_evidence_r2.ingest.

Helper-function tests (parsing, phase grouping) run standalone with
synthetic temp fixtures. The full build_bundle() integration test runs
against the real local physical-evidence harvest and is skipped (not
failed) if that harvest is not present on this machine -- it is real
hardware-derived evidence outside the repository, not a portable fixture.
"""
import json
import tempfile
import unittest
from pathlib import Path

from src.navigation.odometry_evidence_r2 import ingest

# Same harvest root used by the R2-P0 checkpoint; a real, hash-verified,
# local physical-evidence capsule outside the repository.
_HARVEST_ROOT = Path(
    r"C:\Users\IdeaPad 3-15IILO5\Documents\OttoGuide-Final-Physical-Harvest"
    r"\FINAL-R4-20260720T204735Z"
)


class TestOdomFieldForTopic(unittest.TestCase):
    def test_primary_topic_uses_odom_field(self):
        self.assertEqual(ingest._odom_field_for_topic("rt/odommodestate"), "odom")

    def test_secondary_topic_uses_lf_odom_field(self):
        self.assertEqual(ingest._odom_field_for_topic("rt/lf/odommodestate"), "lf_odom")


class TestParseChannelJsonlDir(unittest.TestCase):
    def test_filters_by_topic_and_sorts_by_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "a.jsonl").write_text(
                json.dumps({"topic": "rt/odommodestate", "sequence": 5,
                            "phase": "UNMARKED", "odom": {"position": [0, 0, 0], "yaw_speed": 0.0}}) + "\n"
                + json.dumps({"topic": "rt/lf/odommodestate", "sequence": 1,
                              "phase": "UNMARKED", "lf_odom": {"position": [0, 0, 0], "yaw_speed": 0.0}}) + "\n",
                encoding="utf-8",
            )
            (directory / "b.jsonl").write_text(
                json.dumps({"topic": "rt/odommodestate", "sequence": 2,
                            "phase": "UNMARKED", "odom": {"position": [0, 0, 0], "yaw_speed": 0.0}}) + "\n",
                encoding="utf-8",
            )
            records, truncated = ingest._parse_channel_jsonl_dir(directory, "rt/odommodestate")
            self.assertEqual(truncated, 0)
            self.assertEqual([r["sequence"] for r in records], [2, 5])

    def test_terminal_nul_byte_truncates_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            good_line = json.dumps({"topic": "rt/odommodestate", "sequence": 1,
                                     "phase": "UNMARKED", "odom": {"position": [0, 0, 0], "yaw_speed": 0.0}})
            raw = (good_line + "\n").encode("utf-8") + b"\x00\x00\x00\x00"
            (directory / "truncated.jsonl").write_bytes(raw)
            records, truncated = ingest._parse_channel_jsonl_dir(directory, "rt/odommodestate")
            self.assertEqual(truncated, 1)
            self.assertEqual(len(records), 1)

    def test_malformed_json_line_skipped_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "bad.jsonl").write_text("{not valid json\n", encoding="utf-8")
            records, truncated = ingest._parse_channel_jsonl_dir(directory, "rt/odommodestate")
            self.assertEqual(records, [])


class TestGroupByPhase(unittest.TestCase):
    def test_groups_correctly(self):
        records = [
            {"phase": "PRE_ROUTE_STATIONARY", "sequence": 1},
            {"phase": "ROUTE_ACTIVE", "sequence": 2},
            {"phase": "PRE_ROUTE_STATIONARY", "sequence": 3},
        ]
        by_phase = ingest._group_by_phase(records)
        self.assertEqual(len(by_phase["PRE_ROUTE_STATIONARY"]), 2)
        self.assertEqual(len(by_phase["ROUTE_ACTIVE"]), 1)

    def test_missing_phase_defaults_to_unmarked(self):
        by_phase = ingest._group_by_phase([{"sequence": 1}])
        self.assertIn("UNMARKED", by_phase)


@unittest.skipUnless(_HARVEST_ROOT.is_dir(), "local physical-evidence harvest not present on this machine")
class TestBuildBundleIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = ingest.build_bundle(_HARVEST_ROOT, "2026-07-21T00:00:00Z")

    def test_three_sessions_ingested(self):
        session_types = {s.session_type for s in self.bundle.sessions}
        self.assertEqual(session_types, {
            "R3C_MANUAL_PHYSICAL_ROUTE",
            "R4_FINAL_PHYSICAL_HARVEST",
            "R4B_FINAL_BEST_EFFORT_GROUND_TRUTH",
        })

    def test_no_authoritative_channel_selected(self):
        self.assertIsNone(self.bundle.channel_comparison.authoritative_source_channel)

    def test_covariance_never_publication_ready(self):
        self.assertFalse(self.bundle.covariance.publication_model_ready)

    def test_invalid_r4b_segment_excluded_from_computation(self):
        invalidated = [
            s for s in self.bundle.dynamic_segments
            if s.phase == "left_90_return_invalidated"
        ]
        self.assertTrue(invalidated)
        for segment in invalidated:
            self.assertFalse(segment.valid)
            self.assertEqual(segment.ground_truth_constraint, "INVALID")
            self.assertIsNotNone(segment.invalid_reason)

    def test_corrected_180_segment_retains_traceable_label(self):
        corrected = [
            s for s in self.bundle.dynamic_segments
            if s.phase == "left_180_operator_corrected"
        ]
        self.assertTrue(corrected)
        for segment in corrected:
            self.assertTrue(segment.valid)
            self.assertEqual(segment.movement_type, "OPERATOR_YAW_TURN_LEFT")

    def test_retry_segment_is_distinct_from_first_and_invalidated(self):
        evidence_ids = {s.evidence_id for s in self.bundle.dynamic_segments}
        retry_ids = {e for e in evidence_ids if "valid_retry_local_baseline" in e}
        first_ids = {e for e in evidence_ids if e.endswith("left_90_first.rt_odommodestate")
                     or e.endswith("left_90_first.rt_lf_odommodestate")}
        self.assertTrue(retry_ids)
        self.assertTrue(first_ids)
        self.assertTrue(retry_ids.isdisjoint(first_ids))

    def test_r3c_and_r4_use_distinct_boot_domains(self):
        self.assertNotEqual(
            self.bundle.reset_discontinuity.from_boot_id,
            self.bundle.reset_discontinuity.to_boot_id,
        )
        self.assertFalse(self.bundle.reset_discontinuity.trajectory_concatenation_permitted)

    def test_deterministic_rebuild(self):
        second = ingest.build_bundle(_HARVEST_ROOT, "2026-07-21T00:00:00Z")
        from src.navigation.odometry_evidence_r2 import report
        self.assertEqual(report.bundle_document(self.bundle), report.bundle_document(second))


if __name__ == "__main__":
    unittest.main()

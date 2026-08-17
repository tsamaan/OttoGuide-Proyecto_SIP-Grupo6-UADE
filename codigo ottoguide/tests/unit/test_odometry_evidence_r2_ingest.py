"""Unit tests for src.navigation.odometry_evidence_r2.ingest.

Helper-function tests (parsing, phase grouping) are pure UNIT_TESTS: they run
standalone with synthetic temp fixtures, no harvest required, portable to
any machine.

The full build_bundle() integration test is a HARVEST_INTEGRATION_TEST: it
is opt-in via the OTTOGUIDE_R2_HARVEST_ROOT environment variable (never a
hardcoded personal path -- closes finding F9). If the variable is unset, the
class is skipped (harvest integration is genuinely optional on a machine
without the local physical-evidence capsule). If the variable IS set but
points to a directory that doesn't exist, setUpClass raises -- these tests
must FAIL, never silently report PASS-via-skip, when a harvest was expected
(section 11.11).
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from src.navigation.odometry_evidence_r2 import ingest
from src.navigation.odometry_evidence_r2.validation import EvidenceValidationError

_HARVEST_ROOT_ENV = os.environ.get("OTTOGUIDE_R2_HARVEST_ROOT")
_HARVEST_ROOT = Path(_HARVEST_ROOT_ENV) if _HARVEST_ROOT_ENV else None


def _sample_line(topic, sequence, phase="UNMARKED", position=(0.0, 0.0, 0.0), yaw_speed=0.0):
    field = "odom" if topic == "rt/odommodestate" else "lf_odom"
    return json.dumps({
        "topic": topic, "sequence": sequence, "phase": phase,
        field: {"position": list(position), "yaw_speed": yaw_speed},
    })


class TestOdomFieldForTopic(unittest.TestCase):
    def test_primary_topic_uses_odom_field(self):
        self.assertEqual(ingest._odom_field_for_topic("rt/odommodestate"), "odom")

    def test_secondary_topic_uses_lf_odom_field(self):
        self.assertEqual(ingest._odom_field_for_topic("rt/lf/odommodestate"), "lf_odom")

    def test_unknown_topic_raises(self):
        with self.assertRaises(EvidenceValidationError):
            ingest._odom_field_for_topic("rt/some/other/topic")


class TestParseChannelJsonlDirUnit(unittest.TestCase):
    """Pure unit tests using synthetic in-memory fixtures -- no harvest
    dependency, fully portable."""

    def test_filters_by_topic_and_sorts_by_sequence(self):
        # Chunk files are appended in sorted-filename order, matching real
        # recorder chunk numbering; sequence must already be non-decreasing
        # in that append order (a separate test covers the inversion case).
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "a.jsonl").write_text(
                _sample_line("rt/odommodestate", 2) + "\n"
                + _sample_line("rt/lf/odommodestate", 1) + "\n",
                encoding="utf-8",
            )
            (directory / "b.jsonl").write_text(
                _sample_line("rt/odommodestate", 5) + "\n", encoding="utf-8",
            )
            records, parse_report = ingest._parse_channel_jsonl_dir(directory, "rt/odommodestate")
            self.assertEqual([r["sequence"] for r in records], [2, 5])
            self.assertEqual(parse_report.file_count, 2)
            self.assertEqual(parse_report.record_count, 2)
            self.assertEqual(parse_report.discarded_records, 1)  # the lf/odommodestate line
            self.assertEqual(parse_report.schema_errors, 0)

    def test_valid_terminal_nul_after_complete_line_is_tolerated(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            raw = (_sample_line("rt/odommodestate", 1) + "\n").encode("utf-8") + b"\x00\x00\x00\x00"
            (directory / "truncated.jsonl").write_bytes(raw)
            records, parse_report = ingest._parse_channel_jsonl_dir(directory, "rt/odommodestate")
            self.assertEqual(parse_report.terminal_nul_files, 1)
            self.assertEqual(len(records), 1)

    def test_non_terminal_nul_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            raw = b"\x00\x00" + (_sample_line("rt/odommodestate", 1) + "\n").encode("utf-8")
            (directory / "bad.jsonl").write_bytes(raw)
            with self.assertRaises(EvidenceValidationError):
                ingest._parse_channel_jsonl_dir(directory, "rt/odommodestate")

    def test_nul_not_after_complete_line_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            partial = _sample_line("rt/odommodestate", 1)[:10].encode("utf-8")
            raw = partial + b"\x00\x00\x00"
            (directory / "bad.jsonl").write_bytes(raw)
            with self.assertRaises(EvidenceValidationError):
                ingest._parse_channel_jsonl_dir(directory, "rt/odommodestate")

    def test_malformed_json_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "bad.jsonl").write_text("{not valid json\n", encoding="utf-8")
            with self.assertRaises(EvidenceValidationError):
                ingest._parse_channel_jsonl_dir(directory, "rt/odommodestate")

    def test_malformed_utf8_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "bad.jsonl").write_bytes(b"\xff\xfe\x00garbage")
            with self.assertRaises(EvidenceValidationError):
                ingest._parse_channel_jsonl_dir(directory, "rt/odommodestate")

    def test_unknown_topic_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "bad.jsonl").write_text(
                json.dumps({"topic": "rt/unknown_topic", "sequence": 1,
                            "phase": "UNMARKED", "odom": {"position": [0, 0, 0], "yaw_speed": 0.0}}) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(EvidenceValidationError):
                ingest._parse_channel_jsonl_dir(directory, "rt/odommodestate")

    def test_duplicate_sequence_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "a.jsonl").write_text(
                _sample_line("rt/odommodestate", 1) + "\n"
                + _sample_line("rt/odommodestate", 1) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(EvidenceValidationError):
                ingest._parse_channel_jsonl_dir(directory, "rt/odommodestate")

    def test_monotonic_inversion_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "a.jsonl").write_text(
                _sample_line("rt/odommodestate", 5) + "\n"
                + _sample_line("rt/odommodestate", 3) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(EvidenceValidationError):
                ingest._parse_channel_jsonl_dir(directory, "rt/odommodestate")

    def test_non_positive_sequence_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "a.jsonl").write_text(
                _sample_line("rt/odommodestate", 0) + "\n", encoding="utf-8",
            )
            with self.assertRaises(EvidenceValidationError):
                ingest._parse_channel_jsonl_dir(directory, "rt/odommodestate")

    def test_missing_required_field_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "a.jsonl").write_text(
                json.dumps({"topic": "rt/odommodestate", "sequence": 1, "phase": "UNMARKED"}) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(EvidenceValidationError):
                ingest._parse_channel_jsonl_dir(directory, "rt/odommodestate")

    def test_nan_value_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            # json module accepts NaN literal on load (Python extension);
            # verify our parser rejects it rather than propagating it.
            (directory / "a.jsonl").write_text(
                '{"topic": "rt/odommodestate", "sequence": 1, "phase": "UNMARKED", '
                '"odom": {"position": [0.0, NaN, 0.0], "yaw_speed": 0.0}}\n',
                encoding="utf-8",
            )
            with self.assertRaises(EvidenceValidationError):
                ingest._parse_channel_jsonl_dir(directory, "rt/odommodestate")

    def test_infinity_value_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "a.jsonl").write_text(
                '{"topic": "rt/odommodestate", "sequence": 1, "phase": "UNMARKED", '
                '"odom": {"position": [0.0, 0.0, 0.0], "yaw_speed": Infinity}}\n',
                encoding="utf-8",
            )
            with self.assertRaises(EvidenceValidationError):
                ingest._parse_channel_jsonl_dir(directory, "rt/odommodestate")

    def test_empty_directory_produces_empty_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            records, parse_report = ingest._parse_channel_jsonl_dir(Path(tmp), "rt/odommodestate")
            self.assertEqual(records, [])
            self.assertEqual(parse_report.file_count, 0)
            self.assertEqual(parse_report.record_count, 0)

    def test_unknown_expected_topic_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(EvidenceValidationError):
                ingest._parse_channel_jsonl_dir(Path(tmp), "rt/not_a_real_topic")


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


@unittest.skipUnless(
    _HARVEST_ROOT is not None,
    "OTTOGUIDE_R2_HARVEST_ROOT not set; harvest integration tests are opt-in",
)
class TestBuildBundleIntegration(unittest.TestCase):
    """HARVEST_INTEGRATION_TESTS: require OTTOGUIDE_R2_HARVEST_ROOT to point
    at the real, hash-verified local physical-evidence capsule. If the
    variable is set but the path doesn't exist, this must fail loudly, not
    skip (section 11.11) -- see setUpClass."""

    @classmethod
    def setUpClass(cls):
        if not _HARVEST_ROOT.is_dir():
            raise RuntimeError(
                f"OTTOGUIDE_R2_HARVEST_ROOT={_HARVEST_ROOT} does not exist; "
                "harvest integration tests must fail here, not silently skip"
            )
        cls.bundle = ingest.build_bundle(_HARVEST_ROOT, "2026-07-21T00:00:00Z")

    def test_three_sessions_ingested(self):
        session_types = {s.session_type for s in self.bundle.sessions}
        self.assertEqual(session_types, {
            "R3C_MANUAL_PHYSICAL_ROUTE",
            "R4_FINAL_PHYSICAL_HARVEST",
            "R4B_FINAL_BEST_EFFORT_GROUND_TRUTH",
        })

    def test_every_session_has_a_time_domain(self):
        session_ids = {s.session_id for s in self.bundle.sessions}
        time_domain_ids = {t.session_id for t in self.bundle.time_domains}
        self.assertEqual(session_ids, time_domain_ids)

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

    def test_r4b_boot_relation_stated_as_unresolved_not_asserted(self):
        r4b_session = next(s for s in self.bundle.sessions if s.session_type == "R4B_FINAL_BEST_EFFORT_GROUND_TRUTH")
        self.assertIsNone(r4b_session.boot_id)
        self.assertTrue(any("R4B_BOOT_RELATION_TO_R4 = UNRESOLVED" in msg for msg in r4b_session.limitations))

    def test_reset_claims_are_split_not_aggregated(self):
        claim_ids = {c.claim_id for c in self.bundle.claims}
        self.assertIn("CROSS_BOOT_DISCONTINUITY_OBSERVED", claim_ids)
        self.assertIn("RESET_BEHAVIOR_CHARACTERIZED", claim_ids)
        self.assertIn("EXACT_RESET_INSTANT", claim_ids)
        self.assertNotIn("RESET_AND_DISCONTINUITY", claim_ids)
        by_id = {c.claim_id: c for c in self.bundle.claims}
        self.assertEqual(by_id["CROSS_BOOT_DISCONTINUITY_OBSERVED"].r2p0_state, "VERIFIED")
        self.assertEqual(by_id["EXACT_RESET_INSTANT"].r2p0_state, "UNRESOLVED")

    def test_dynamic_residual_statistics_explicit_not_available(self):
        self.assertEqual(len(self.bundle.dynamic_residual_statistics), 1)
        self.assertEqual(self.bundle.dynamic_residual_statistics[0].status, "NOT_AVAILABLE_IN_P0A")

    def test_all_claim_evidence_ids_resolve(self):
        # Bundle construction itself would have raised if not -- this test
        # exists so a future field addition that skips validation is caught.
        known_ids = {s.evidence_id for s in self.bundle.sessions}
        known_ids |= {t.evidence_id for t in self.bundle.time_domains}
        for claim in self.bundle.claims:
            for evidence_id in claim.evidence_ids:
                self.assertTrue(
                    evidence_id in known_ids
                    or any(evidence_id == s.evidence_id for s in self.bundle.dynamic_segments)
                    or evidence_id in (
                        self.bundle.channel_comparison.evidence_id,
                        self.bundle.imu_crosscheck.evidence_id,
                        self.bundle.reset_discontinuity.evidence_id,
                        self.bundle.lidar_extrinsic.evidence_id,
                        self.bundle.covariance.evidence_id,
                    )
                    or any(evidence_id == o.evidence_id for o in self.bundle.axis_observations)
                    or any(evidence_id == o.evidence_id for o in self.bundle.yaw_observations)
                )

    def test_deterministic_rebuild(self):
        second = ingest.build_bundle(_HARVEST_ROOT, "2026-07-21T00:00:00Z")
        from src.navigation.odometry_evidence_r2 import report
        self.assertEqual(report.bundle_document(self.bundle), report.bundle_document(second))


if __name__ == "__main__":
    unittest.main()

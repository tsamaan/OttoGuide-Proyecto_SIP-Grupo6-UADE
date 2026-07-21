"""Tests for MVP-ODOM-TF-R2-P1A (quantitative audit and claim hardening).

PURE_UNIT_TESTS run against synthetic in-memory data. HARVEST_INTEGRATION_
TESTS are opt-in via OTTOGUIDE_R2_HARVEST_ROOT and must actually execute
(never silently skip-as-pass) once the env var is set.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

from src.navigation.odometry_characterization_r2 import (
    arbitration,
    boot_relation,
    causal_lag,
    dropout_semantics,
    models,
    p1a_audit,
    report,
    segment_eligibility,
)
from src.navigation.odometry_evidence_r2.validation import EvidenceValidationError

_HARVEST_ROOT_ENV = os.environ.get("OTTOGUIDE_R2_HARVEST_ROOT")


def _quality(session_id, channel, sample_count, gap_count, dropout_count, jitter=1.0, rate=40.0):
    return models.ChannelQualityMetrics(
        schema_version="2.1.1-p1a", evidence_id=f"e.{session_id}.{channel}",
        session_id=session_id, channel=channel, sample_count=sample_count, duration_s=sample_count / rate,
        first_receipt_monotonic_ns=0, last_receipt_monotonic_ns=int(sample_count / rate * 1e9),
        mean_rate_hz=rate, median_rate_hz=rate, period_p50_ms=25.0, period_p95_ms=30.0, period_p99_ms=40.0,
        jitter_mad_ms=jitter, gap_threshold_ms=100.0, gap_threshold_method="M", max_gap_ms=100.0,
        gap_count=gap_count, dropout_count=dropout_count, duplicate_sequences=0, missing_sequence_spans=0,
        monotonic_inversions=0, non_finite_count=0, stationary_coverage=0.5, dynamic_coverage=0.5,
        status="VERIFIED", limitations=(),
    )


class TestSequenceSemantics(unittest.TestCase):
    def test_classification_is_global_across_all_topics(self):
        s = dropout_semantics.build_sequence_semantics("s1")
        self.assertEqual(s.classification, "GLOBAL_ACROSS_ALL_TOPICS")

    def test_invalid_classification_rejected(self):
        with self.assertRaises(EvidenceValidationError):
            models.SequenceSemantics(evidence_id="e", session_id="s1", classification="BOGUS",
                                      evidence_summary="x", status="VERIFIED", limitations=())


class TestDropoutPolicy(unittest.TestCase):
    def test_primary_signal_must_be_time_gap(self):
        with self.assertRaises(EvidenceValidationError):
            models.DropoutDetectionPolicy(
                schema_version="x", evidence_id="e", primary_signal="CHANNEL_LOCAL_SEQUENCE_GAP_ESTIMATE",
                secondary_signal="X", time_gap_method="m", time_gap_threshold_method="m",
                sequence_gap_caveat="c", status="VERIFIED", limitations=())

    def test_global_sequence_span_not_conflated_with_time_gap(self):
        policy = dropout_semantics.build_dropout_detection_policy()
        classification = dropout_semantics.classify_channel_dropouts(time_gap_count=0, sequence_gap_estimate=407)
        # a large sequence-derived span with ZERO time gaps must not be reported as a dropout
        self.assertEqual(classification["confirmed_dropout_count"], 0)
        self.assertEqual(classification["channel_local_sequence_gap_estimate"], 407)
        self.assertEqual(policy.primary_signal, "TIME_GAP")

    def test_channel_local_cadence_miss_detected_via_time_gap(self):
        classification = dropout_semantics.classify_channel_dropouts(time_gap_count=3, sequence_gap_estimate=0)
        self.assertEqual(classification["confirmed_dropout_count"], 3)


class TestArbitrationAggregationFix(unittest.TestCase):
    def test_aggregates_across_all_sessions_not_just_first(self):
        primary = [
            _quality("r3c", "P", 100, gap_count=18, dropout_count=407, jitter=2.0),
            _quality("r4", "P", 50, gap_count=0, dropout_count=36, jitter=2.0),
            _quality("r4b", "P", 200, gap_count=0, dropout_count=251, jitter=2.0),
        ]
        secondary = [
            _quality("r3c", "L", 50, gap_count=4, dropout_count=12, jitter=1.0),
            _quality("r4", "L", 25, gap_count=0, dropout_count=0, jitter=1.0),
            _quality("r4b", "L", 100, gap_count=0, dropout_count=1, jitter=1.0),
        ]
        matrix = arbitration.build_arbitration_matrix(
            primary_records=primary, secondary_records=secondary, imu_agreement_count=1,
            reset_behavior_status="PARTIAL", provenance_quality_status="PASS")
        # LF wins jitter, gaps, dropouts in this synthetic aggregate -> LF preferred
        self.assertEqual(matrix.preferred_analysis_channel, "rt/lf/odommodestate")

    def test_criterion_count_matches_serialized_length(self):
        audit = arbitration.build_arbitration_audit(
            primary_records=[], secondary_records=[], imu_agreement_count=0,
            reset_behavior_status="PARTIAL", provenance_quality_status="PASS")
        self.assertEqual(audit.criterion_count, len(audit.criteria))

    def test_arbitration_direction_lower_is_better_for_dropouts(self):
        rule = arbitration._audit_criterion("dropouts", "LOWER_IS_BETTER", 10.0, 2.0, "n", 1.0, "x")
        self.assertEqual(rule.winner, "LF")

    def test_arbitration_weighting_excludes_sample_count(self):
        audit = arbitration.build_arbitration_audit(
            primary_records=[_quality("s", "P", 1000, 0, 0)],
            secondary_records=[_quality("s", "L", 10, 0, 0)],
            imu_agreement_count=0, reset_behavior_status="PARTIAL", provenance_quality_status="PASS")
        completeness = next(c for c in audit.criteria if c.name == "data_completeness")
        self.assertEqual(completeness.weight, 0.0)

    def test_authoritative_channel_always_null(self):
        audit = arbitration.build_arbitration_audit(
            primary_records=[], secondary_records=[], imu_agreement_count=0,
            reset_behavior_status="PARTIAL", provenance_quality_status="PASS")
        self.assertIsNone(audit.authoritative_source_channel)


class TestCausalLagAliasing(unittest.TestCase):
    def test_insufficient_paired_samples_rejects_lag(self):
        candidate = causal_lag.scan_causal_lag(
            session_id="s", phase="p", primary_times=[0.0, 0.1], primary_yaw_speed=[1.0, 1.0],
            secondary_times=[0.0, 0.1], secondary_yaw_speed=[1.0, 1.0])
        self.assertEqual(candidate.status, "UNRESOLVED")

    def test_status_always_unresolved_even_with_strong_signal(self):
        import math
        n = 200
        primary_times = [i * 0.025 for i in range(n)]
        primary_yaw = [math.sin(t * 2 * math.pi) for t in primary_times]
        secondary_times = [i * 0.05 for i in range(n // 2)]
        secondary_yaw = [math.sin((t - 0.01) * 2 * math.pi) for t in secondary_times]
        candidate = causal_lag.scan_causal_lag(
            session_id="s", phase="p", primary_times=primary_times, primary_yaw_speed=primary_yaw,
            secondary_times=secondary_times, secondary_yaw_speed=secondary_yaw)
        self.assertEqual(candidate.status, "UNRESOLVED")

    def test_model_rejects_non_unresolved_status(self):
        with self.assertRaises(EvidenceValidationError):
            models.CausalLagCandidate(
                schema_version="x", evidence_id="e", session_id="s", phase="p",
                scan_lags_ms=(0.0,), scan_correlations=(0.9,), peak_lag_ms=0.0, peak_correlation=0.9,
                zero_lag_correlation=0.9, aliasing_risk="LOW", sample_rate_ratio="2:1",
                rejection_reason="x", status="SUPPORTED_INFERENCE", limitations=())


class TestYawUnitSeparation(unittest.TestCase):
    def test_yaw_angle_residual_forced_not_available(self):
        with self.assertRaises(EvidenceValidationError):
            models.YawAngleResidualMetrics(
                schema_version="x", evidence_id="e", session_id="s", phase="p",
                yaw_angle_rmse_rad=0.5, status="NOT_AVAILABLE", limitations=())

    def test_yaw_angle_residual_valid_construction(self):
        m = models.YawAngleResidualMetrics(
            schema_version="x", evidence_id="e", session_id="s", phase="p",
            yaw_angle_rmse_rad=None, status="NOT_AVAILABLE", limitations=("no orientation data",))
        self.assertIsNone(m.yaw_angle_rmse_rad)

    def test_yaw_speed_residual_field_name_is_explicit(self):
        m = models.YawSpeedResidualMetrics(
            schema_version="x", evidence_id="e", session_id="s", phase="p",
            yaw_speed_rmse_rad_s=0.07, yaw_speed_mae_rad_s=0.05, sample_count=10,
            status="VERIFIED", limitations=())
        self.assertEqual(m.yaw_speed_rmse_rad_s, 0.07)


class TestSegmentEligibility(unittest.TestCase):
    def test_invalid_segment_never_ground_truth_eligible(self):
        e = segment_eligibility.r4b_segment_eligibility("s", "left_90_return_invalidated")
        self.assertFalse(e.valid_for_ground_truth)
        self.assertFalse(e.valid_for_translation_scale)
        self.assertFalse(e.valid_for_yaw_gain)
        self.assertTrue(e.valid_for_channel_alignment)

    def test_valid_segment_eligible_for_scale_when_translation(self):
        e = segment_eligibility.r4b_segment_eligibility("s", "forward_x_valid_retry")
        self.assertTrue(e.valid_for_ground_truth)
        self.assertTrue(e.valid_for_translation_scale)
        self.assertFalse(e.valid_for_yaw_gain)

    def test_claim_cannot_be_verified_by_ineligible_evidence(self):
        # structural guard: an eligibility record itself never claims ground-truth
        # validity for an invalid segment, regardless of caller behavior.
        e = segment_eligibility.r4b_segment_eligibility("s", "forward_x_setup_not_executed")
        self.assertIsNotNone(e.invalid_reason)

    def test_unrecognized_segment_raises(self):
        with self.assertRaises(ValueError):
            segment_eligibility.r4b_segment_eligibility("s", "not_a_real_segment")


class TestBootRelationEvidence(unittest.TestCase):
    def test_same_boot_requires_both_hashes_verified(self):
        with self.assertRaises(EvidenceValidationError):
            models.BootRelationEvidence(
                evidence_id="e", session_a="a", session_b="b", boot_id_a="x", boot_id_b="x",
                source_a_sha256="0" * 64, source_b_sha256="1" * 64,
                source_a_hash_verified=True, source_b_hash_verified=False,
                same_boot_verified=True, same_time_domain=False, continuous_capture=False,
                continuous_trajectory_permitted=False, status="VERIFIED", limitations=())

    def test_continuous_trajectory_never_permitted(self):
        with self.assertRaises(EvidenceValidationError):
            models.BootRelationEvidence(
                evidence_id="e", session_a="a", session_b="b", boot_id_a="x", boot_id_b="x",
                source_a_sha256="0" * 64, source_b_sha256="0" * 64,
                source_a_hash_verified=True, source_b_hash_verified=True,
                same_boot_verified=True, same_time_domain=False, continuous_capture=False,
                continuous_trajectory_permitted=True, status="VERIFIED", limitations=())


class TestStaticImportGate(unittest.TestCase):
    _FORBIDDEN = ("rclpy", "nav_msgs", "geometry_msgs", "tf2_ros", "unitree_sdk2py")

    def _p1a_files(self):
        pkg_root = Path(__file__).resolve().parents[2] / "src" / "navigation" / "odometry_characterization_r2"
        new_files = ["dropout_semantics.py", "causal_lag.py", "boot_relation.py",
                     "segment_eligibility.py", "p1a_audit.py"]
        cli = (Path(__file__).resolve().parents[2] / "tools" / "hil" / "offline_navigation"
               / "audit_odom_characterization_r2_p1a.py")
        return [pkg_root / f for f in new_files] + [cli]

    def test_no_forbidden_imports(self):
        for path in self._p1a_files():
            text = path.read_text(encoding="utf-8")
            for forbidden in self._FORBIDDEN:
                self.assertNotIn(forbidden, text, f"{path.name} references forbidden import {forbidden!r}")

    def test_no_hardcoded_personal_path(self):
        for path in self._p1a_files():
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("IdeaPad 3-15IILO5", text, f"{path.name} contains a hardcoded personal path")


@unittest.skipUnless(
    _HARVEST_ROOT_ENV,
    "OTTOGUIDE_R2_HARVEST_ROOT not set; harvest integration tests are opt-in",
)
class TestHarvestIntegrationP1A(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harvest_root = Path(_HARVEST_ROOT_ENV)
        if not cls.harvest_root.is_dir():
            raise AssertionError(f"OTTOGUIDE_R2_HARVEST_ROOT={_HARVEST_ROOT_ENV} does not exist")

    def test_build_p1a_bundle_against_real_harvest(self):
        bundle, hashes = p1a_audit.build_p1a_bundle(self.harvest_root, "2026-01-01T00:00:00Z")
        self.assertEqual(len(bundle.audit_findings), 10)
        self.assertGreater(len(hashes), 0)
        self.assertIsNone(bundle.arbitration_audit.authoritative_source_channel)

    def test_arbitration_corrected_matches_real_data_direction(self):
        bundle, _hashes = p1a_audit.build_p1a_bundle(self.harvest_root, "2026-01-01T00:00:00Z")
        # real data: LF has fewer gaps/dropouts than primary in every session (H2)
        self.assertEqual(bundle.p1_bundle.arbitration.preferred_analysis_channel, "rt/lf/odommodestate")

    def test_boot_relation_hash_verified_against_real_files(self):
        ev = boot_relation.audit_r4b_boot_relation(self.harvest_root)
        self.assertTrue(ev.source_b_hash_verified)
        self.assertTrue(ev.same_boot_verified)
        self.assertFalse(ev.continuous_trajectory_permitted)

    def test_build_p1a_bundle_deterministic(self):
        bundle1, _h1 = p1a_audit.build_p1a_bundle(self.harvest_root, "2026-01-01T00:00:00Z")
        bundle2, _h2 = p1a_audit.build_p1a_bundle(self.harvest_root, "2026-01-01T00:00:00Z")
        self.assertEqual(p1a_audit.result_document(bundle1), p1a_audit.result_document(bundle2))

    def test_cli_two_runs_byte_identical(self):
        import tempfile
        cli_path = (Path(__file__).resolve().parents[2] / "tools" / "hil" / "offline_navigation"
                    / "audit_odom_characterization_r2_p1a.py")
        descriptor_env = os.environ.get("OTTOGUIDE_R2_P0A_DESCRIPTOR")
        descriptor_path = (
            Path(descriptor_env) if descriptor_env else
            self.harvest_root.parent.parent / "outputs" / "OttoGuide-R2-Evidence"
            / "MVP-ODOM-TF-R2-P0A" / "staging" / "portable_descriptor_v2.json"
        )
        if not descriptor_path.is_file():
            self.skipTest(f"portable descriptor not found at {descriptor_path}")
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            for out_dir in (tmp1, tmp2):
                result = subprocess.run(
                    [sys.executable, str(cli_path), "--evidence-descriptor", str(descriptor_path),
                     "--output-dir", out_dir, "--generated-utc", "2026-01-01T00:00:00Z",
                     "--harvest-root", str(self.harvest_root)],
                    capture_output=True, text=True, cwd=str(cli_path.parents[3]),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            for name in os.listdir(tmp1):
                self.assertEqual(Path(tmp1, name).read_bytes(), Path(tmp2, name).read_bytes(),
                                  f"{name} differs between runs")

    def test_no_writes_outside_output_dir(self):
        before = set(self.harvest_root.rglob("*"))
        p1a_audit.build_p1a_bundle(self.harvest_root, "2026-01-01T00:00:00Z")
        after = set(self.harvest_root.rglob("*"))
        self.assertEqual(before, after, "harvest was modified by build_p1a_bundle")


if __name__ == "__main__":
    unittest.main()

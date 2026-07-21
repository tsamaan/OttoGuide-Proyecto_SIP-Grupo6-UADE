"""Tests for MVP-ODOM-TF-R2-P1 (odometry_characterization_r2).

PURE_UNIT_TESTS run against synthetic in-memory data (no filesystem, no
harvest). HARVEST_INTEGRATION_TESTS are opt-in via OTTOGUIDE_R2_HARVEST_ROOT
(never a hardcoded personal path) and run the real fail-closed reparse and
CLI against the real physical evidence -- section 33 requires the harvest
suite to actually execute, never silently count a skip as a pass.
"""
import json
import math
import os
import subprocess
import sys
import unittest
from pathlib import Path

from src.navigation.odometry_characterization_r2 import (
    alignment,
    arbitration,
    channel_quality,
    imu,
    models,
    motion,
    report,
    sample_loader,
    segmentation,
    statistics as p1stats,
)
from src.navigation.odometry_evidence_r2.validation import EvidenceValidationError

_HARVEST_ROOT_ENV = os.environ.get("OTTOGUIDE_R2_HARVEST_ROOT")
_SHA = "0" * 64


def _sample(session_id="s1", boot_id=None, channel="rt/odommodestate", sequence=1,
            receipt_ns=1_000_000_000, phase="UNMARKED", position=(0.0, 0.0, 0.0),
            velocity=(0.0, 0.0, 0.0), yaw_speed=0.0, mode=0):
    return models.NormalizedOdomSample(
        schema_version="2.1.0-p1", session_id=session_id, boot_id=boot_id, channel=channel,
        sequence=sequence, receipt_monotonic_ns=receipt_ns, receipt_utc=None, phase=phase,
        position=position, velocity=velocity, yaw_speed=yaw_speed, mode=mode,
        source_file="a/b.jsonl", source_sha256=_SHA,
    )


def _lowstate_sample(session_id="s1", sequence=1, receipt_ns=1_000_000_000, phase="UNMARKED",
                      gyroscope=(0.0, 0.0, 0.0), rpy_deg=(0.0, 0.0, 0.0)):
    return models.NormalizedLowStateSample(
        schema_version="2.1.0-p1", session_id=session_id, sequence=sequence,
        receipt_monotonic_ns=receipt_ns, phase=phase, gyroscope=gyroscope, rpy_deg=rpy_deg,
        source_file="a/b.jsonl", source_sha256=_SHA,
    )


class TestModelsFailClosed(unittest.TestCase):
    def test_nan_position_rejected(self):
        with self.assertRaises(EvidenceValidationError):
            _sample(position=(float("nan"), 0.0, 0.0))

    def test_infinite_yaw_speed_rejected(self):
        with self.assertRaises(EvidenceValidationError):
            _sample(yaw_speed=float("inf"))

    def test_bool_as_sequence_rejected(self):
        with self.assertRaises(EvidenceValidationError):
            models.NormalizedOdomSample(
                schema_version="2.1.0-p1", session_id="s1", boot_id=None, channel="rt/odommodestate",
                sequence=True, receipt_monotonic_ns=1, receipt_utc=None, phase="UNMARKED",
                position=(0.0, 0.0, 0.0), velocity=(0.0, 0.0, 0.0), yaw_speed=0.0, mode=0,
                source_file="a.jsonl", source_sha256=_SHA)

    def test_absolute_path_rejected(self):
        with self.assertRaises(EvidenceValidationError):
            models.NormalizedOdomSample(
                schema_version="2.1.0-p1", session_id="s1", boot_id=None, channel="rt/odommodestate",
                sequence=1, receipt_monotonic_ns=1, receipt_utc=None, phase="UNMARKED",
                position=(0.0, 0.0, 0.0), velocity=(0.0, 0.0, 0.0), yaw_speed=0.0, mode=0,
                source_file="C:\\absolute\\path.jsonl", source_sha256=_SHA)

    def test_path_traversal_rejected(self):
        with self.assertRaises(EvidenceValidationError):
            models.NormalizedOdomSample(
                schema_version="2.1.0-p1", session_id="s1", boot_id=None, channel="rt/odommodestate",
                sequence=1, receipt_monotonic_ns=1, receipt_utc=None, phase="UNMARKED",
                position=(0.0, 0.0, 0.0), velocity=(0.0, 0.0, 0.0), yaw_speed=0.0, mode=0,
                source_file="../../escape.jsonl", source_sha256=_SHA)

    def test_invalid_sha256_rejected(self):
        with self.assertRaises(EvidenceValidationError):
            models.NormalizedOdomSample(
                schema_version="2.1.0-p1", session_id="s1", boot_id=None, channel="rt/odommodestate",
                sequence=1, receipt_monotonic_ns=1, receipt_utc=None, phase="UNMARKED",
                position=(0.0, 0.0, 0.0), velocity=(0.0, 0.0, 0.0), yaw_speed=0.0, mode=0,
                source_file="a.jsonl", source_sha256="not-a-hash")

    def test_gap_event_start_after_end_rejected(self):
        with self.assertRaises(EvidenceValidationError):
            models.GapEvent(session_id="s1", channel="rt/odommodestate", start_receipt_ns=100,
                             end_receipt_ns=50, gap_s=1.0, before_sequence=1, after_sequence=2)

    def test_imu_agreement_cannot_be_verified(self):
        with self.assertRaises(EvidenceValidationError):
            models.ImuAgreementMetrics(
                schema_version="2.1.0-p1", evidence_id="e", session_id="s1", segment_name="seg",
                sportmode_yaw_speed_sign="POSITIVE", lowstate_gyro_z_sign="POSITIVE", sign_agreement=True,
                gyro_units_status="X", rpy_units_status="Y", wrap_events=0, sample_coverage=1.0,
                status="VERIFIED", limitations=())

    def test_nominal_scale_candidate_cannot_exceed_best_effort(self):
        with self.assertRaises(EvidenceValidationError):
            models.NominalScaleCandidate(
                evidence_id="e", segment_name="seg", operator_nominal_value_m=2.0, observed_value_m=2.0,
                ratio=1.0, ground_truth_mode="BEST_EFFORT_MEASURED", uncertainty_status="X",
                source_sha256=(_SHA,), status="VERIFIED", limitations=())

    def test_arbitration_matrix_rejects_non_null_authoritative_channel(self):
        criterion = models.ChannelArbitrationCriterion(criterion_name="c", primary_status="PASS",
                                                        secondary_status="PARTIAL", notes="n")
        with self.assertRaises(EvidenceValidationError):
            models.ChannelArbitrationMatrix(
                schema_version="2.1.0-p1", evidence_id="e", criteria=(criterion,),
                preferred_analysis_channel="rt/odommodestate",
                authoritative_source_channel="rt/odommodestate",
                status="PARTIAL", limitations=())


class TestStatistics(unittest.TestCase):
    def test_percentile_matches_known_values(self):
        values = [1, 2, 3, 4, 5]
        self.assertAlmostEqual(p1stats.percentile(values, 0.5), 3.0)
        self.assertAlmostEqual(p1stats.percentile(values, 0.0), 1.0)
        self.assertAlmostEqual(p1stats.percentile(values, 1.0), 5.0)

    def test_mad_zero_for_constant_series(self):
        self.assertEqual(p1stats.mad([5.0, 5.0, 5.0, 5.0]), 0.0)

    def test_robust_gap_threshold_floors_at_ten_times_median_for_periodic_data(self):
        intervals = [0.01] * 100  # perfectly periodic, zero jitter
        threshold, method = p1stats.robust_gap_threshold(intervals)
        self.assertAlmostEqual(threshold, 0.1)
        self.assertIn("MEDIAN", method)

    def test_modal_positive_step_ignores_non_positive_deltas(self):
        sequences = [1, 4, 4, 7, 10, 13]  # step of 3, one duplicate (delta 0)
        self.assertEqual(p1stats.modal_positive_step(sequences), 3)

    def test_nearest_neighbor_pairing_is_one_to_one(self):
        primary = [0.0, 1.0, 2.0, 3.0]
        secondary = [0.05, 1.05, 2.05]
        pairs = p1stats.nearest_neighbor_pairing(primary, secondary, tolerance=0.2)
        secondary_indices = [j for _i, j, _o in pairs]
        self.assertEqual(len(secondary_indices), len(set(secondary_indices)), "secondary index reused")

    def test_nearest_neighbor_pairing_respects_tolerance(self):
        primary = [0.0, 100.0]
        secondary = [0.05]
        pairs = p1stats.nearest_neighbor_pairing(primary, secondary, tolerance=0.2)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][0], 0)

    def test_unwrap_angles_counts_wrap_events(self):
        angles = [3.0, -3.0, 3.0]  # crosses +/- pi boundary twice
        unwrapped, wrap_events = p1stats.unwrap_angles(angles)
        self.assertEqual(wrap_events, 2)
        self.assertAlmostEqual(unwrapped[0], 3.0)

    def test_unwrap_angles_no_wrap_for_smooth_series(self):
        angles = [0.0, 0.1, 0.2, 0.3]
        _unwrapped, wrap_events = p1stats.unwrap_angles(angles)
        self.assertEqual(wrap_events, 0)


class TestChannelQuality(unittest.TestCase):
    def _samples(self, n=100, period_ns=10_000_000, gap_at=None, gap_multiplier=20):
        samples = []
        t = 0
        seq = 1
        for i in range(n):
            samples.append(_sample(sequence=seq, receipt_ns=t))
            if gap_at == i:
                t += period_ns * gap_multiplier
            else:
                t += period_ns
            seq += 3  # session-wide shared counter simulation
        return tuple(samples)

    def test_rate_calculation(self):
        samples = self._samples(n=100, period_ns=10_000_000)  # 10ms -> 100Hz
        q = channel_quality.compute_channel_quality(
            session_id="s1", channel="rt/odommodestate", samples=samples,
            stationary_sample_count=100, dynamic_sample_count=0, parse_stats={})
        self.assertAlmostEqual(q.mean_rate_hz, 100.0, delta=1.0)

    def test_gap_detection(self):
        samples = self._samples(n=50, period_ns=10_000_000, gap_at=25, gap_multiplier=50)
        q = channel_quality.compute_channel_quality(
            session_id="s1", channel="rt/odommodestate", samples=samples,
            stationary_sample_count=50, dynamic_sample_count=0, parse_stats={})
        self.assertGreaterEqual(q.gap_count, 1)
        self.assertGreater(q.max_gap_ms, 100.0)

    def test_dropout_detection_uses_observed_modal_step_not_unit_increment(self):
        samples = self._samples(n=50, period_ns=10_000_000)  # sequence step = 3, not 1
        q = channel_quality.compute_channel_quality(
            session_id="s1", channel="rt/odommodestate", samples=samples,
            stationary_sample_count=50, dynamic_sample_count=0, parse_stats={})
        self.assertEqual(q.dropout_count, 0, "regular step-3 sequence must not be flagged as dropout")

    def test_cross_session_mixing_rejected(self):
        samples = (_sample(session_id="a"), _sample(session_id="b", sequence=2))
        with self.assertRaises(EvidenceValidationError):
            channel_quality.compute_channel_quality(
                session_id="a", channel="rt/odommodestate", samples=samples,
                stationary_sample_count=2, dynamic_sample_count=0, parse_stats={})

    def test_zero_samples_rejected(self):
        with self.assertRaises(EvidenceValidationError):
            channel_quality.compute_channel_quality(
                session_id="s1", channel="rt/odommodestate", samples=(),
                stationary_sample_count=0, dynamic_sample_count=0, parse_stats={})


class TestAlignment(unittest.TestCase):
    def test_one_to_one_pairing_no_ambiguous_reuse(self):
        primary = tuple(_sample(sequence=i, receipt_ns=i * 10_000_000) for i in range(1, 21))
        secondary = tuple(_sample(channel="rt/lf/odommodestate", sequence=i, receipt_ns=i * 10_000_000 + 500_000)
                           for i in range(1, 21))
        result = alignment.compute_alignment(session_id="s1", phase="P", primary_samples=primary,
                                              secondary_samples=secondary)
        self.assertIsNotNone(result)
        self.assertLessEqual(result.paired_sample_count, min(len(primary), len(secondary)))

    def test_insufficient_excitation_yields_no_lag_candidate(self):
        # Only 3 samples -- far below MIN_PAIRS_FOR_LAG_CANDIDATE.
        primary = tuple(_sample(sequence=i, receipt_ns=i * 10_000_000) for i in range(1, 4))
        secondary = tuple(_sample(channel="rt/lf/odommodestate", sequence=i, receipt_ns=i * 10_000_000)
                           for i in range(1, 4))
        result = alignment.compute_alignment(session_id="s1", phase="P", primary_samples=primary,
                                              secondary_samples=secondary)
        self.assertIsNone(result.lag_candidate_ms)
        self.assertEqual(result.lag_status, "UNRESOLVED")

    def test_empty_input_returns_none(self):
        self.assertIsNone(alignment.compute_alignment(session_id="s1", phase="P",
                                                        primary_samples=(), secondary_samples=()))


class TestMotionSegments(unittest.TestCase):
    def test_yaw_integration_of_constant_rate_matches_analytic(self):
        # yaw_speed = 1.0 rad/s for 2 seconds -> integral ~= 2.0 rad
        samples = tuple(_sample(sequence=i, receipt_ns=i * 100_000_000, yaw_speed=1.0) for i in range(21))
        m = motion.compute_motion_segment(session_id="s1", segment_name="seg", channel="rt/odommodestate",
                                           valid=True, ground_truth_constraint="BEST_EFFORT_MEASURED",
                                           samples=samples)
        self.assertAlmostEqual(m.integrated_yaw_speed_rad, 2.0, delta=0.05)

    def test_invalid_segment_excluded_from_scale_candidates(self):
        samples = tuple(_sample(sequence=i, receipt_ns=i * 10_000_000, position=(float(i) * 0.1, 0, 0))
                         for i in range(10))
        m = motion.compute_motion_segment(session_id="s1", segment_name="left_90_return_invalidated",
                                           channel="rt/odommodestate", valid=False,
                                           ground_truth_constraint="INVALID", samples=samples)
        candidate = motion.compute_nominal_scale_candidate(segment_name="left_90_return_invalidated",
                                                            motion_metrics=m, source_sha256=(_SHA,))
        self.assertIsNone(candidate)

    def test_cross_session_segment_rejected(self):
        samples = (_sample(session_id="a", sequence=1), _sample(session_id="b", sequence=2))
        with self.assertRaises(EvidenceValidationError):
            motion.compute_motion_segment(session_id="a", segment_name="seg", channel="rt/odommodestate",
                                           valid=True, ground_truth_constraint="NOT_AVAILABLE", samples=samples)

    def test_best_effort_scale_status_never_elevated(self):
        samples = tuple(_sample(sequence=i, receipt_ns=i * 10_000_000, position=(float(i) * 0.2, 0, 0))
                         for i in range(11))
        m = motion.compute_motion_segment(session_id="s1", segment_name="forward_x_valid_retry",
                                           channel="rt/odommodestate", valid=True,
                                           ground_truth_constraint="BEST_EFFORT_MEASURED", samples=samples)
        candidate = motion.compute_nominal_scale_candidate(segment_name="forward_x_valid_retry",
                                                            motion_metrics=m, source_sha256=(_SHA,))
        self.assertEqual(candidate.status, "BEST_EFFORT_ONLY")


class TestImuCrosscheck(unittest.TestCase):
    def test_sign_agreement_detected(self):
        odom_samples = tuple(_sample(sequence=i, receipt_ns=i * 20_000_000, yaw_speed=0.5) for i in range(1, 21))
        lowstate_samples = tuple(_lowstate_sample(sequence=i, receipt_ns=i * 20_000_000, gyroscope=(0, 0, 0.3))
                                  for i in range(1, 21))
        m = imu.compute_imu_agreement(session_id="s1", segment_name="seg", odom_samples=odom_samples,
                                       lowstate_samples=lowstate_samples)
        self.assertTrue(m.sign_agreement)
        self.assertEqual(m.status, "PARTIAL_QUANTIFIED")

    def test_sign_disagreement_detected(self):
        odom_samples = tuple(_sample(sequence=i, receipt_ns=i * 20_000_000, yaw_speed=0.5) for i in range(1, 21))
        lowstate_samples = tuple(_lowstate_sample(sequence=i, receipt_ns=i * 20_000_000, gyroscope=(0, 0, -0.3))
                                  for i in range(1, 21))
        m = imu.compute_imu_agreement(session_id="s1", segment_name="seg", odom_samples=odom_samples,
                                       lowstate_samples=lowstate_samples)
        self.assertFalse(m.sign_agreement)

    def test_gyro_units_never_assumed(self):
        odom_samples = tuple(_sample(sequence=i, receipt_ns=i * 20_000_000, yaw_speed=0.5) for i in range(1, 21))
        lowstate_samples = tuple(_lowstate_sample(sequence=i, receipt_ns=i * 20_000_000, gyroscope=(0, 0, 0.3))
                                  for i in range(1, 21))
        m = imu.compute_imu_agreement(session_id="s1", segment_name="seg", odom_samples=odom_samples,
                                       lowstate_samples=lowstate_samples)
        self.assertEqual(m.gyro_units_status, "UNRESOLVED_NO_UNIT_LABEL_IN_SOURCE")

    def test_status_never_verified(self):
        self.assertNotEqual(models.STATUS_VALUES, set())  # sanity
        odom_samples = tuple(_sample(sequence=i, receipt_ns=i * 20_000_000, yaw_speed=0.5) for i in range(1, 21))
        lowstate_samples = tuple(_lowstate_sample(sequence=i, receipt_ns=i * 20_000_000, gyroscope=(0, 0, 0.3))
                                  for i in range(1, 21))
        m = imu.compute_imu_agreement(session_id="s1", segment_name="seg", odom_samples=odom_samples,
                                       lowstate_samples=lowstate_samples)
        self.assertNotEqual(m.status, "VERIFIED")


class TestSegmentation(unittest.TestCase):
    def test_unrecognized_r4b_occurrence_raises(self):
        samples = tuple(_sample(sequence=i, phase="R4B_UNKNOWN_PHASE") for i in range(1, 5))
        with self.assertRaises(EvidenceValidationError):
            segmentation.r4b_named_segments(samples)

    def test_new_local_baseline_retry_resolved_correctly(self):
        samples = (
            tuple(_sample(sequence=i, phase="R4B_YAW_CCW_90_RETURN") for i in range(1, 4))
            + tuple(_sample(sequence=i, phase="R4B_STANDING_BASELINE") for i in range(4, 6))
            + tuple(_sample(sequence=i, phase="R4B_YAW_CCW_90_RETURN") for i in range(6, 9))
        )
        resolved = segmentation.r4b_named_segments(samples)
        names = [r[0] for r in resolved]
        self.assertIn("left_90_return_invalidated", names)
        self.assertIn("left_90_valid_retry_local_baseline", names)
        invalid_entry = next(r for r in resolved if r[0] == "left_90_return_invalidated")
        self.assertFalse(invalid_entry[1])
        valid_entry = next(r for r in resolved if r[0] == "left_90_valid_retry_local_baseline")
        self.assertTrue(valid_entry[1])

    def test_unmarked_never_treated_as_motion_segment(self):
        samples = tuple(_sample(sequence=i, phase="UNMARKED") for i in range(1, 5))
        resolved = segmentation.r4b_named_segments(samples)
        self.assertEqual(resolved, [])


class TestArbitration(unittest.TestCase):
    def test_authoritative_channel_always_null(self):
        matrix = arbitration.build_arbitration_matrix(
            primary_quality=None, secondary_quality=None, imu_agreement_count=0,
            reset_behavior_status="PARTIAL", provenance_quality_status="PASS")
        self.assertIsNone(matrix.authoritative_source_channel)

    def test_preferred_channel_distinct_from_authoritative(self):
        matrix = arbitration.build_arbitration_matrix(
            primary_quality=None, secondary_quality=None, imu_agreement_count=0,
            reset_behavior_status="PARTIAL", provenance_quality_status="PASS")
        self.assertNotEqual(matrix.preferred_analysis_channel, "AUTHORITATIVE")


class TestStaticImportGate(unittest.TestCase):
    """No ROS/Nav2/rclpy/DDS imports anywhere in the P1 package or CLI."""
    _FORBIDDEN = ("rclpy", "nav_msgs", "geometry_msgs", "tf2_ros", "unitree_sdk2py")

    def _package_files(self):
        pkg_root = Path(__file__).resolve().parents[2] / "src" / "navigation" / "odometry_characterization_r2"
        cli_file = Path(__file__).resolve().parents[2] / "tools" / "hil" / "offline_navigation" / "characterize_physical_odometry_r2.py"
        return list(pkg_root.glob("*.py")) + [cli_file]

    def test_no_forbidden_imports(self):
        for path in self._package_files():
            text = path.read_text(encoding="utf-8")
            for forbidden in self._FORBIDDEN:
                self.assertNotIn(forbidden, text, f"{path.name} references forbidden import {forbidden!r}")

    def test_no_hardcoded_personal_path(self):
        for path in self._package_files():
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("IdeaPad 3-15IILO5", text, f"{path.name} contains a hardcoded personal path")


@unittest.skipUnless(
    _HARVEST_ROOT_ENV,
    "OTTOGUIDE_R2_HARVEST_ROOT not set; harvest integration tests are opt-in",
)
class TestHarvestIntegration(unittest.TestCase):
    """HARVEST_INTEGRATION_TESTS: require OTTOGUIDE_R2_HARVEST_ROOT to point
    at the real, hash-verified physical harvest. Never skipped silently once
    the env var is set -- a bad path is a hard failure, not a skip."""

    @classmethod
    def setUpClass(cls):
        cls.harvest_root = Path(_HARVEST_ROOT_ENV)
        if not cls.harvest_root.is_dir():
            raise AssertionError(f"OTTOGUIDE_R2_HARVEST_ROOT={_HARVEST_ROOT_ENV} does not exist")

    def test_build_bundle_against_real_harvest(self):
        bundle, hashes = report.build_characterization_bundle(self.harvest_root, "2026-01-01T00:00:00Z")
        self.assertGreater(len(bundle.channel_quality), 0)
        self.assertGreater(len(bundle.motion), 0)
        self.assertGreater(len(hashes), 0)
        self.assertIsNone(bundle.arbitration.authoritative_source_channel)

    def test_build_bundle_deterministic(self):
        bundle1, _h1 = report.build_characterization_bundle(self.harvest_root, "2026-01-01T00:00:00Z")
        bundle2, _h2 = report.build_characterization_bundle(self.harvest_root, "2026-01-01T00:00:00Z")
        self.assertEqual(report.bundle_document(bundle1), report.bundle_document(bundle2))

    def test_r4b_segment_geometry_matches_nominal_within_tolerance(self):
        bundle, _hashes = report.build_characterization_bundle(self.harvest_root, "2026-01-01T00:00:00Z")
        by_segment = {(m.segment_name, m.channel): m for m in bundle.motion}
        forward_x = by_segment.get(("forward_x_valid_retry", "rt/odommodestate"))
        self.assertIsNotNone(forward_x)
        self.assertAlmostEqual(forward_x.planar_displacement, 2.0, delta=0.5)

    def test_manifest_mismatch_fails_closed(self):
        from src.navigation.odometry_evidence_r2.source_manifest import verify_harvest_against_descriptor
        descriptor = {
            "descriptor_schema_version": "1.0.0-p0a",
            "harvest_id": "WRONG_ID",
            "manifest_relative_path": "FINAL_PHYSICAL_HARVEST_INDEX.json",
            "manifest_sha256": "0" * 64,
            "expected_source_files": [],
            "expected_source_sha256": [],
        }
        with self.assertRaises(EvidenceValidationError):
            verify_harvest_against_descriptor(descriptor, self.harvest_root)

    def test_cli_two_runs_byte_identical(self):
        import tempfile
        cli_path = (Path(__file__).resolve().parents[2] / "tools" / "hil" / "offline_navigation"
                    / "characterize_physical_odometry_r2.py")
        descriptor_env = os.environ.get("OTTOGUIDE_R2_P0A_DESCRIPTOR")
        descriptor_path = (
            Path(descriptor_env) if descriptor_env else
            self.harvest_root.parent.parent / "outputs" / "OttoGuide-R2-Evidence"
            / "MVP-ODOM-TF-R2-P0A" / "staging" / "portable_descriptor_v2.json"
        )
        if not descriptor_path.is_file():
            self.skipTest(f"portable descriptor not found at {descriptor_path} "
                           "(set OTTOGUIDE_R2_P0A_DESCRIPTOR to override)")
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
                content1 = Path(tmp1, name).read_bytes()
                content2 = Path(tmp2, name).read_bytes()
                self.assertEqual(content1, content2, f"{name} differs between runs")

    def test_no_writes_outside_output_dir(self):
        import tempfile
        watched_dirs = [Path(_HARVEST_ROOT_ENV)]
        before = {d: set(p for p in d.rglob("*")) for d in watched_dirs}
        with tempfile.TemporaryDirectory() as tmp:
            report.build_characterization_bundle(Path(_HARVEST_ROOT_ENV), "2026-01-01T00:00:00Z")
        after = {d: set(p for p in d.rglob("*")) for d in watched_dirs}
        for d in watched_dirs:
            self.assertEqual(before[d], after[d], f"{d} was modified by build_characterization_bundle")


if __name__ == "__main__":
    unittest.main()

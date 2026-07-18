"""MVP-ODOM-TF-R1 / R1A offline readiness gate tests (stdlib unittest only).

Runnable without pytest:

    python -m unittest discover -s tests/unit -p "test_odom_tf_readiness.py" -v

SYNTHETIC_TEST_ONLY = true
PHYSICAL_VALIDATION_CLAIM = false

Some tests build synthetic candidates / contracts to exercise the gate's
logical branches. Those are test scaffolding ONLY: no synthetic test authorizes
`/odom` or TF publication, and none is evidence about the physical robot. The
real-fixture tests assert the opposite -- that the actual stationary evidence
blocks publication.
"""
import json
import unittest
from dataclasses import replace
from pathlib import Path

from src.navigation.odometry_candidate_adapter import (
    OdometryCandidate,
    assess_odom_tf_readiness,
    to_odometry_candidate,
)
from src.navigation.odometry_candidate_adapter.readiness import (
    BLOCKER,
    CLASSIFICATION_CONTRACT_READY,
    CLASSIFICATION_FAIL_CLOSED_INVALID_INPUT,
    OBSERVATION,
    AUTHORITATIVE_CHANNEL_NOT_PRESENT,
    AXIS_CONVENTION_UNVERIFIED,
    CANDIDATE_STRUCTURE_INVALID,
    CHILD_FRAME_ID_UNRESOLVED,
    COVARIANCE_EVIDENCE_CONTRADICTION,
    COVARIANCE_UNAVAILABLE,
    DYNAMIC_EVIDENCE_CONTRADICTION,
    DYNAMIC_MOTION_EVIDENCE_MISSING,
    EMPTY_OR_INVALID_SEQUENCE,
    EVIDENCE_CONTRACT_INVALID,
    IMU_CROSSCHECK_UNAVAILABLE,
    IMU_EVIDENCE_CONTRADICTION,
    MESSAGE_TIMESTAMP_ZERO,
    MIXED_CHANNEL_SEQUENCE_REQUIRES_FILTERING,
    RECEIPT_MONOTONIC_ORDER_INVALID,
    SOURCE_CHANNEL_ARBITRATION_UNRESOLVED,
    OdomTfEvidenceContract,
)
from src.navigation.odometry_candidate_adapter.validation import (
    COVARIANCE_POLICY,
    FRAME_ID,
    TIMESTAMP_POLICY,
)

# SYNTHETIC_TEST_ONLY = true  /  PHYSICAL_VALIDATION_CLAIM = false
SYNTHETIC_TEST_ONLY = True
PHYSICAL_VALIDATION_CLAIM = False

FIXTURES_DIR = (
    Path(__file__).resolve().parent.parent / "fixtures" / "mfr_r6_sportmodestate"
)

EXPECTED_FIXTURE_BLOCKERS = (
    DYNAMIC_MOTION_EVIDENCE_MISSING,
    SOURCE_CHANNEL_ARBITRATION_UNRESOLVED,
    "SOURCE_FRAME_SEMANTICS_UNVERIFIED",
    CHILD_FRAME_ID_UNRESOLVED,
    AXIS_CONVENTION_UNVERIFIED,
    "SCALE_AND_SIGN_UNVERIFIED",
    MESSAGE_TIMESTAMP_ZERO,
    "RECEIPT_TIME_TO_ROS_TIME_UNRESOLVED",
    COVARIANCE_UNAVAILABLE,
    IMU_CROSSCHECK_UNAVAILABLE,
    "RESET_AND_DISCONTINUITY_BEHAVIOR_UNVERIFIED",
)


def load_jsonl(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _synthetic_candidate(channel="rt/odommodestate", receipt=100,
                         stamp_zero=False, position=(1.0, 2.0, 0.5),
                         covariance=True, gyro_ok=True, accel_ok=True,
                         velocity=(0.1, 0.0, 0.0), yaw=0.05):
    """A fully-coherent SYNTHETIC candidate. Not physical evidence."""
    return OdometryCandidate(
        valid=True,
        source_channel=channel,
        receipt_monotonic_ns=receipt,
        receipt_wall_utc_ns=receipt + 1,
        timestamp_policy=TIMESTAMP_POLICY,
        message_stamp_sec=0 if stamp_zero else 5,
        message_stamp_nanosec=0 if stamp_zero else 7,
        frame_id=FRAME_ID,
        child_frame_id=None,
        position_xyz=tuple(position),
        velocity_xyz=tuple(velocity),
        yaw_speed=yaw,
        orientation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        rpy=(0.0, 0.0, 0.1),
        covariance_policy=COVARIANCE_POLICY,
        covariance_available=covariance,
        gyro_reliable=gyro_ok,
        accel_reliable=accel_ok,
        warnings=[],
        errors=[],
    )


def _fully_satisfied_contract():
    return OdomTfEvidenceContract(
        dynamic_motion_evidence_available=True,
        source_channel_arbitration_resolved=True,
        authoritative_source_channel="rt/odommodestate",
        source_frame_semantics_verified=True,
        child_frame_id_resolved=True,
        resolved_child_frame_id="base_link",
        axis_convention_verified=True,
        scale_and_sign_verified=True,
        receipt_to_ros_time_mapping_resolved=True,
        covariance_available=True,
        imu_crosscheck_available=True,
        reset_and_discontinuity_behavior_verified=True,
    )


class TestRealStationaryFixtures(unittest.TestCase):
    def setUp(self):
        primary = load_jsonl(FIXTURES_DIR / "mfr_r6_primary_rt_odommodestate.jsonl")
        secondary = load_jsonl(FIXTURES_DIR / "mfr_r6_secondary_rt_lf_odommodestate.jsonl")
        self.samples = primary + secondary
        self.candidates = [to_odometry_candidate(s) for s in self.samples]
        self.report = assess_odom_tf_readiness(self.candidates, OdomTfEvidenceContract())

    def test_real_stationary_fixtures_publication_blocked(self):
        self.assertFalse(self.report.odom_publication_ready)
        self.assertFalse(self.report.odom_to_base_link_tf_ready)
        self.assertTrue(self.report.physical_validation_required)

    def test_exact_eleven_blockers_and_order(self):
        self.assertEqual(self.report.blocker_codes(), EXPECTED_FIXTURE_BLOCKERS)
        self.assertEqual(self.report.blocker_count, 11)

    def test_classification_is_contract_ready_not_plain_ready(self):
        self.assertEqual(self.report.classification, CLASSIFICATION_CONTRACT_READY)
        self.assertNotEqual(self.report.classification, "READY")

    def test_both_physical_channels_preserved(self):
        self.assertEqual(
            set(self.report.channels), {"rt/odommodestate", "rt/lf/odommodestate"}
        )

    def test_candidate_counts(self):
        self.assertEqual(self.report.candidate_count, 160)
        self.assertEqual(self.report.candidate_invalid_count, 0)

    def test_nav2_always_false_and_physical_required(self):
        self.assertFalse(self.report.nav2_ready)
        self.assertTrue(self.report.physical_validation_required)

    def test_rate_difference_is_observation(self):
        pairs = {(b.code, b.severity) for b in self.report.blockers}
        self.assertIn(("RATE_DIFFERENCE_BETWEEN_CHANNELS", OBSERVATION), pairs)


class TestContractFailClosed(unittest.TestCase):
    def test_none_contract_fails_closed(self):
        report = assess_odom_tf_readiness([], None)
        self.assertEqual(report.classification, CLASSIFICATION_FAIL_CLOSED_INVALID_INPUT)
        self.assertIn(EVIDENCE_CONTRACT_INVALID, report.blocker_codes())
        self.assertFalse(report.odom_publication_ready)

    def test_wrong_contract_type_fails_closed_no_exception(self):
        report = assess_odom_tf_readiness([], {"covariance_available": True})
        self.assertIn(EVIDENCE_CONTRACT_INVALID, report.blocker_codes())

    def test_truthy_string_field_is_contract_invalid(self):
        # A truthy non-bool like "false" must be rejected, not trusted.
        bad = replace(OdomTfEvidenceContract(), covariance_available="false")
        report = assess_odom_tf_readiness([], bad)
        self.assertIn(EVIDENCE_CONTRACT_INVALID, report.blocker_codes())

    def test_int_field_is_contract_invalid(self):
        bad = replace(OdomTfEvidenceContract(), dynamic_motion_evidence_available=1)
        report = assess_odom_tf_readiness([], bad)
        self.assertIn(EVIDENCE_CONTRACT_INVALID, report.blocker_codes())


class TestCandidateFailClosed(unittest.TestCase):
    def _valid_sample(self):
        return {
            "channel": "rt/odommodestate",
            "receipt_monotonic_ns": 123456789,
            "receipt_wall_utc_ns": 987654321,
            "stamp_sec": 0, "stamp_nanosec": 0,
            "position": [1.0, 2.0, 0.5],
            "velocity": [0.0, 0.0, 0.0],
            "yaw_speed": 0.0,
            "imu_quaternion": [0.0, 0.0, 0.0, 1.0],
            "imu_rpy": [0.0, 0.0, 0.0],
            "imu_gyroscope": [0.0, 0.0, 0.0],
            "imu_accelerometer": [0.0, 0.0, 0.0],
        }

    def test_arbitrary_object_with_valid_true_is_candidate_invalid(self):
        class Fake:
            valid = True  # bare valid=True must NOT be trusted
        report = assess_odom_tf_readiness([Fake()], OdomTfEvidenceContract())
        self.assertEqual(report.classification, CLASSIFICATION_FAIL_CLOSED_INVALID_INPUT)
        self.assertIn(CANDIDATE_STRUCTURE_INVALID, report.blocker_codes())
        self.assertFalse(report.odom_publication_ready)

    def test_empty_sequence_fails_closed(self):
        report = assess_odom_tf_readiness([], OdomTfEvidenceContract())
        self.assertIn(EMPTY_OR_INVALID_SEQUENCE, report.blocker_codes())
        self.assertFalse(report.offline_contract_ready)

    def test_non_iterable_fails_closed(self):
        report = assess_odom_tf_readiness(42, OdomTfEvidenceContract())
        self.assertEqual(report.classification, CLASSIFICATION_FAIL_CLOSED_INVALID_INPUT)
        self.assertIn(EMPTY_OR_INVALID_SEQUENCE, report.blocker_codes())

    def test_all_invalid_adapter_candidates_block(self):
        bad = self._valid_sample()
        del bad["position"]
        cands = [to_odometry_candidate(bad)]
        report = assess_odom_tf_readiness(cands, OdomTfEvidenceContract())
        # Invalid adapter candidate is structurally-shaped but valid=False ->
        # empty/invalid-sequence blocker, still fail-closed.
        self.assertFalse(report.offline_contract_ready)
        self.assertIn(EMPTY_OR_INVALID_SEQUENCE, report.blocker_codes())


class TestChannelCoherence(unittest.TestCase):
    def test_authoritative_channel_absent_blocks(self):
        contract = replace(
            _fully_satisfied_contract(),
            authoritative_source_channel="rt/odommodestate",
        )
        # candidates only on the OTHER channel
        cands = [
            _synthetic_candidate(channel="rt/lf/odommodestate", receipt=10),
            _synthetic_candidate(channel="rt/lf/odommodestate", receipt=20),
        ]
        report = assess_odom_tf_readiness(cands, contract)
        self.assertIn(AUTHORITATIVE_CHANNEL_NOT_PRESENT, report.blocker_codes())
        self.assertFalse(report.odom_publication_ready)

    def test_authoritative_channel_not_in_allowlist_blocks(self):
        contract = replace(
            _fully_satisfied_contract(),
            authoritative_source_channel="rt/bogus_channel",
        )
        cands = [
            _synthetic_candidate(receipt=10), _synthetic_candidate(receipt=20),
        ]
        report = assess_odom_tf_readiness(cands, contract)
        self.assertIn(AUTHORITATIVE_CHANNEL_NOT_PRESENT, report.blocker_codes())

    def test_mixed_channel_sequence_blocks_publication(self):
        contract = _fully_satisfied_contract()
        cands = [
            _synthetic_candidate(channel="rt/odommodestate", receipt=10, position=(0, 0, 0)),
            _synthetic_candidate(channel="rt/lf/odommodestate", receipt=20, position=(1, 1, 1)),
        ]
        report = assess_odom_tf_readiness(cands, contract)
        self.assertIn(MIXED_CHANNEL_SEQUENCE_REQUIRES_FILTERING, report.blocker_codes())
        self.assertFalse(report.odom_publication_ready)


class TestTemporalCoherence(unittest.TestCase):
    def test_non_monotonic_receipt_order_blocks(self):
        contract = _fully_satisfied_contract()
        cands = [
            _synthetic_candidate(receipt=30, position=(0, 0, 0)),
            _synthetic_candidate(receipt=10, position=(1, 1, 1)),  # goes backwards
        ]
        report = assess_odom_tf_readiness(cands, contract)
        self.assertIn(RECEIPT_MONOTONIC_ORDER_INVALID, report.blocker_codes())
        self.assertFalse(report.odom_publication_ready)


class TestEvidenceContradiction(unittest.TestCase):
    def test_contract_covariance_true_candidate_false_contradiction(self):
        contract = _fully_satisfied_contract()
        cands = [
            _synthetic_candidate(receipt=10, covariance=False, position=(0, 0, 0)),
            _synthetic_candidate(receipt=20, covariance=False, position=(1, 1, 1)),
        ]
        report = assess_odom_tf_readiness(cands, contract)
        self.assertIn(COVARIANCE_EVIDENCE_CONTRADICTION, report.blocker_codes())
        self.assertFalse(report.odom_publication_ready)

    def test_contract_imu_true_unreliable_candidate_contradiction(self):
        contract = _fully_satisfied_contract()
        cands = [
            _synthetic_candidate(receipt=10, gyro_ok=False, position=(0, 0, 0)),
            _synthetic_candidate(receipt=20, gyro_ok=False, position=(1, 1, 1)),
        ]
        report = assess_odom_tf_readiness(cands, contract)
        self.assertIn(IMU_EVIDENCE_CONTRADICTION, report.blocker_codes())

    def test_contract_dynamic_true_single_stationary_sample_contradiction(self):
        contract = _fully_satisfied_contract()
        cands = [_synthetic_candidate(receipt=10, position=(0, 0, 0),
                                      velocity=(0, 0, 0), yaw=0.0)]
        report = assess_odom_tf_readiness(cands, contract)
        self.assertIn(DYNAMIC_EVIDENCE_CONTRADICTION, report.blocker_codes())
        self.assertFalse(report.odom_publication_ready)


class TestDeterminismAndSerialization(unittest.TestCase):
    def setUp(self):
        primary = load_jsonl(FIXTURES_DIR / "mfr_r6_primary_rt_odommodestate.jsonl")
        self.candidates = [to_odometry_candidate(s) for s in primary]

    def test_deterministic_ordering(self):
        r1 = assess_odom_tf_readiness(self.candidates, OdomTfEvidenceContract())
        r2 = assess_odom_tf_readiness(self.candidates, OdomTfEvidenceContract())
        self.assertEqual(r1.blocker_codes(), r2.blocker_codes())
        severities = [b.severity for b in r1.blockers]
        last_blocker = max((i for i, s in enumerate(severities) if s == BLOCKER), default=-1)
        first_obs = next((i for i, s in enumerate(severities) if s == OBSERVATION), len(severities))
        self.assertLess(last_blocker, first_obs)

    def test_report_serialization_stable(self):
        report = assess_odom_tf_readiness(self.candidates, OdomTfEvidenceContract())
        d1 = json.dumps(report.to_dict(), sort_keys=True)
        d2 = json.dumps(report.to_dict(), sort_keys=True)
        self.assertEqual(d1, d2)
        parsed = json.loads(d1)
        self.assertEqual(parsed["blocker_codes"], list(report.blocker_codes()))


class TestSyntheticContractBranches(unittest.TestCase):
    """SYNTHETIC ONLY. SYNTHETIC_TEST_ONLY=true / PHYSICAL_VALIDATION_CLAIM=false."""

    def test_fully_satisfied_synthetic_contract_flips_readiness(self):
        # Requires COHERENT synthetic candidates: single channel, covariance
        # on the candidates, reliable IMU, observable dynamic variation,
        # monotonic receipts, non-zero stamp. Only then may readiness flip --
        # a bare contract boolean is never sufficient.
        contract = _fully_satisfied_contract()
        cands = [
            _synthetic_candidate(receipt=10, position=(0.0, 0.0, 0.0)),
            _synthetic_candidate(receipt=20, position=(0.5, 0.1, 0.0)),
            _synthetic_candidate(receipt=30, position=(1.2, 0.3, 0.0)),
        ]
        report = assess_odom_tf_readiness(cands, contract)
        self.assertEqual(report.blocker_count, 0)
        self.assertTrue(report.odom_publication_ready)
        self.assertTrue(report.odom_to_base_link_tf_ready)
        self.assertFalse(report.nav2_ready)
        self.assertTrue(report.physical_validation_required)

    def test_satisfied_contract_but_no_candidate_covariance_stays_blocked(self):
        # Even with a fully-satisfied contract, candidates lacking covariance
        # evidence must NOT reach readiness (the R1A coherence fix).
        contract = _fully_satisfied_contract()
        cands = [
            _synthetic_candidate(receipt=10, covariance=False, position=(0.0, 0.0, 0.0)),
            _synthetic_candidate(receipt=20, covariance=False, position=(1.0, 0.1, 0.0)),
        ]
        report = assess_odom_tf_readiness(cands, contract)
        self.assertIn(COVARIANCE_EVIDENCE_CONTRADICTION, report.blocker_codes())
        self.assertFalse(report.odom_publication_ready)

    def test_zero_stamp_blocks_even_with_satisfied_contract(self):
        contract = _fully_satisfied_contract()
        cands = [
            _synthetic_candidate(receipt=10, stamp_zero=True, position=(0.0, 0.0, 0.0)),
            _synthetic_candidate(receipt=20, stamp_zero=True, position=(1.0, 0.1, 0.0)),
        ]
        report = assess_odom_tf_readiness(cands, contract)
        self.assertIn(MESSAGE_TIMESTAMP_ZERO, report.blocker_codes())
        self.assertFalse(report.odom_publication_ready)


if __name__ == "__main__":
    unittest.main()

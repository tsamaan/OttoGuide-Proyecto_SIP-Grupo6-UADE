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
    PUBLICATION_CAPABILITY_WITHHELD,
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

    def test_authoritative_channel_not_in_allowlist_is_contract_invalid(self):
        # R1B: an out-of-allowlist authoritative channel is now rejected at
        # contract validation (EVIDENCE_CONTRACT_INVALID), before the coherence
        # stage -- a non-allow-listed channel can never be authoritative.
        contract = replace(
            _fully_satisfied_contract(),
            authoritative_source_channel="rt/bogus_channel",
        )
        cands = [
            _synthetic_candidate(receipt=10), _synthetic_candidate(receipt=20),
        ]
        report = assess_odom_tf_readiness(cands, contract)
        self.assertIn(EVIDENCE_CONTRACT_INVALID, report.blocker_codes())
        self.assertFalse(report.odom_publication_ready)

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

    def test_fully_satisfied_synthetic_never_authorizes_publication(self):
        # R1B boundary: even fully-satisfied synthetic flags + coherent
        # synthetic candidates may make the input PROCESSABLE
        # (offline_contract_ready True) but must NEVER authorize publication,
        # TF, or nav2 in the R1 series. A synthetic test cannot produce
        # operational readiness.
        contract = _fully_satisfied_contract()
        cands = [
            _synthetic_candidate(receipt=10, position=(0.0, 0.0, 0.0)),
            _synthetic_candidate(receipt=20, position=(0.5, 0.1, 0.0)),
            _synthetic_candidate(receipt=30, position=(1.2, 0.3, 0.0)),
        ]
        report = assess_odom_tf_readiness(cands, contract)
        # Input is processable...
        self.assertTrue(report.offline_contract_ready)
        # ...but the R1 boundary withholds every operational readiness axis.
        self.assertFalse(report.odom_publication_ready)
        self.assertFalse(report.odom_to_base_link_tf_ready)
        self.assertFalse(report.nav2_ready)
        self.assertTrue(report.physical_validation_required)
        self.assertEqual(
            report.publication_capability, PUBLICATION_CAPABILITY_WITHHELD
        )

    def test_covariance_boolean_alone_never_authorizes_publication(self):
        # A candidate covariance boolean (and a contract covariance flag) is
        # not covariance evidence: the model carries no values. It must
        # contradict and never reach publication.
        contract = replace(
            OdomTfEvidenceContract(),
            covariance_available=True,
        )
        cands = [
            _synthetic_candidate(receipt=10, covariance=True, position=(0.0, 0.0, 0.0)),
            _synthetic_candidate(receipt=20, covariance=True, position=(1.0, 0.1, 0.0)),
        ]
        report = assess_odom_tf_readiness(cands, contract)
        self.assertIn(COVARIANCE_EVIDENCE_CONTRADICTION, report.blocker_codes())
        self.assertFalse(report.odom_publication_ready)

    def test_stationary_micro_noise_never_authorizes_dynamic_evidence(self):
        # Tiny stationary spread with dynamic flag asserted must still
        # contradict -- micro-noise is not dynamic proof.
        contract = replace(
            OdomTfEvidenceContract(),
            dynamic_motion_evidence_available=True,
        )
        cands = [
            _synthetic_candidate(receipt=10, position=(0.0, 0.0, 0.0),
                                 velocity=(0.0, 0.0, 0.0), yaw=0.0),
            _synthetic_candidate(receipt=20, position=(1e-7, 0.0, 0.0),
                                 velocity=(0.0, 0.0, 0.0), yaw=0.0),
        ]
        report = assess_odom_tf_readiness(cands, contract)
        self.assertIn(DYNAMIC_EVIDENCE_CONTRADICTION, report.blocker_codes())
        self.assertFalse(report.odom_publication_ready)

    def test_constant_nonzero_velocity_never_authorizes_dynamic_evidence(self):
        # A constant non-zero velocity is not ground-truth dynamic evidence.
        contract = replace(
            OdomTfEvidenceContract(),
            dynamic_motion_evidence_available=True,
        )
        cands = [
            _synthetic_candidate(receipt=10, position=(0.0, 0.0, 0.0),
                                 velocity=(0.5, 0.0, 0.0), yaw=0.0),
            _synthetic_candidate(receipt=20, position=(0.0, 0.0, 0.0),
                                 velocity=(0.5, 0.0, 0.0), yaw=0.0),
        ]
        report = assess_odom_tf_readiness(cands, contract)
        self.assertIn(DYNAMIC_EVIDENCE_CONTRADICTION, report.blocker_codes())
        self.assertFalse(report.odom_publication_ready)

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


class _DuckCandidate:
    """A complete duck-typed fake replicating every OdometryCandidate attribute
    but NOT an OdometryCandidate instance. R1B must reject it."""

    def __init__(self):
        self.valid = True
        self.source_channel = "rt/odommodestate"
        self.receipt_monotonic_ns = 100
        self.receipt_wall_utc_ns = 101
        self.timestamp_policy = TIMESTAMP_POLICY
        self.message_stamp_sec = 5
        self.message_stamp_nanosec = 7
        self.frame_id = FRAME_ID
        self.child_frame_id = None
        self.position_xyz = (1.0, 2.0, 0.5)
        self.velocity_xyz = (0.0, 0.0, 0.0)
        self.yaw_speed = 0.0
        self.orientation_quaternion_xyzw = (0.0, 0.0, 0.0, 1.0)
        self.rpy = (0.0, 0.0, 0.0)
        self.covariance_policy = COVARIANCE_POLICY
        self.covariance_available = False
        self.gyro_reliable = False
        self.accel_reliable = False
        self.warnings = []
        self.errors = []


class TestR1BStructuralHardening(unittest.TestCase):
    """R1B: strict instance + full-structure validation of candidates."""

    def _reject(self, candidate):
        report = assess_odom_tf_readiness([candidate], OdomTfEvidenceContract())
        self.assertEqual(
            report.classification, CLASSIFICATION_FAIL_CLOSED_INVALID_INPUT
        )
        self.assertIn(CANDIDATE_STRUCTURE_INVALID, report.blocker_codes())
        self.assertFalse(report.odom_publication_ready)

    def test_complete_duck_typed_fake_is_rejected(self):
        self._reject(_DuckCandidate())

    def test_wrong_timestamp_policy_rejected(self):
        self._reject(replace(_synthetic_candidate(),
                             timestamp_policy="SOMETHING_ELSE"))

    def test_wrong_frame_id_rejected(self):
        self._reject(replace(_synthetic_candidate(), frame_id="odom"))

    def test_wrong_covariance_policy_rejected(self):
        self._reject(replace(_synthetic_candidate(),
                             covariance_policy="INVENTED_COVARIANCE"))

    def test_malformed_quaternion_rejected(self):
        self._reject(replace(_synthetic_candidate(),
                             orientation_quaternion_xyzw=(0.0, 0.0, 1.0)))

    def test_zero_norm_quaternion_rejected(self):
        self._reject(replace(_synthetic_candidate(),
                             orientation_quaternion_xyzw=(0.0, 0.0, 0.0, 0.0)))

    def test_non_finite_rpy_rejected(self):
        self._reject(replace(_synthetic_candidate(),
                             rpy=(0.0, float("nan"), 0.0)))

    def test_malformed_rpy_length_rejected(self):
        self._reject(replace(_synthetic_candidate(), rpy=(0.0, 0.0)))

    def test_warnings_wrong_type_rejected(self):
        self._reject(replace(_synthetic_candidate(), warnings="not-a-list"))

    def test_errors_wrong_type_rejected(self):
        self._reject(replace(_synthetic_candidate(), errors=[123]))


class TestR1BAdapterNonMappingFailClosed(unittest.TestCase):
    """R1B: to_odometry_candidate never raises on non-mapping input."""

    def test_none_input_invalid_no_exception(self):
        c = to_odometry_candidate(None)
        self.assertFalse(c.valid)
        self.assertTrue(any("not a mapping" in e.lower() for e in c.errors))

    def test_list_input_invalid_no_exception(self):
        c = to_odometry_candidate([1, 2, 3])
        self.assertFalse(c.valid)
        self.assertTrue(any("not a mapping" in e.lower() for e in c.errors))

    def test_int_input_invalid_no_exception(self):
        c = to_odometry_candidate(42)
        self.assertFalse(c.valid)
        self.assertTrue(any("not a mapping" in e.lower() for e in c.errors))

    def test_object_input_invalid_no_exception(self):
        c = to_odometry_candidate(object())
        self.assertFalse(c.valid)
        self.assertTrue(any("not a mapping" in e.lower() for e in c.errors))


class TestR1BContractStringSemantics(unittest.TestCase):
    """R1B: whitespace-only / contradictory contract strings are invalid."""

    def _contract_invalid(self, contract):
        report = assess_odom_tf_readiness([], contract)
        self.assertEqual(
            report.classification, CLASSIFICATION_FAIL_CLOSED_INVALID_INPUT
        )
        self.assertIn(EVIDENCE_CONTRACT_INVALID, report.blocker_codes())

    def test_whitespace_authoritative_channel_invalid(self):
        bad = replace(
            OdomTfEvidenceContract(),
            source_channel_arbitration_resolved=True,
            authoritative_source_channel="   ",
        )
        self._contract_invalid(bad)

    def test_whitespace_child_frame_invalid(self):
        bad = replace(
            OdomTfEvidenceContract(),
            child_frame_id_resolved=True,
            resolved_child_frame_id="  ",
        )
        self._contract_invalid(bad)

    def test_resolved_channel_with_false_flag_invalid(self):
        bad = replace(
            OdomTfEvidenceContract(),
            source_channel_arbitration_resolved=False,
            authoritative_source_channel="rt/odommodestate",
        )
        self._contract_invalid(bad)

    def test_resolved_child_frame_with_false_flag_invalid(self):
        bad = replace(
            OdomTfEvidenceContract(),
            child_frame_id_resolved=False,
            resolved_child_frame_id="base_link",
        )
        self._contract_invalid(bad)

    def test_authoritative_channel_not_in_allowlist_invalid_contract(self):
        bad = replace(
            OdomTfEvidenceContract(),
            source_channel_arbitration_resolved=True,
            authoritative_source_channel="rt/not_a_channel",
        )
        self._contract_invalid(bad)


class TestR1BNonPublishableBoundary(unittest.TestCase):
    """R1B: no boolean combination authorizes publication or TF."""

    def test_real_fixtures_capability_withheld(self):
        primary = load_jsonl(FIXTURES_DIR / "mfr_r6_primary_rt_odommodestate.jsonl")
        secondary = load_jsonl(FIXTURES_DIR / "mfr_r6_secondary_rt_lf_odommodestate.jsonl")
        candidates = [to_odometry_candidate(s) for s in primary + secondary]
        report = assess_odom_tf_readiness(candidates, OdomTfEvidenceContract())
        self.assertEqual(
            report.publication_capability, PUBLICATION_CAPABILITY_WITHHELD
        )
        self.assertFalse(report.odom_publication_ready)
        self.assertFalse(report.odom_to_base_link_tf_ready)
        self.assertFalse(report.nav2_ready)
        self.assertTrue(report.physical_validation_required)
        # exact eleven blockers preserved
        self.assertEqual(report.blocker_codes(), EXPECTED_FIXTURE_BLOCKERS)
        self.assertEqual(report.candidate_count, 160)
        self.assertEqual(report.candidate_invalid_count, 0)

    def test_capability_in_serialization(self):
        report = assess_odom_tf_readiness([], OdomTfEvidenceContract())
        d = json.loads(json.dumps(report.to_dict(), sort_keys=True))
        self.assertEqual(
            d["publication_capability"], PUBLICATION_CAPABILITY_WITHHELD
        )


class _RaisingIterable:
    """An iterable whose iterator raises a chosen exception mid-iteration."""

    def __init__(self, exc_type):
        self._exc_type = exc_type

    def __iter__(self):
        raise self._exc_type("broken iterator")


class _RaisingMapping(dict):
    """A Mapping subclass whose get() raises. isinstance(_, Mapping) is True."""

    def get(self, *args, **kwargs):
        raise ValueError("get is broken")


class _GetOnlyObject:
    """Has a callable get() but is NOT a Mapping."""

    def get(self, key, default=None):
        return default


def _invalid_none_candidate():
    """A real adapter output for a non-mapping input: valid=False,
    source_channel=None."""
    return to_odometry_candidate(None)


class TestR1CMixedSequenceNoException(unittest.TestCase):
    """R1C: mixed valid/invalid sequences never raise; channels come from valid
    candidates only."""

    def _valid(self, receipt=100):
        return _synthetic_candidate(receipt=receipt)

    def test_valid_plus_invalid_none_no_exception(self):
        cands = [self._valid(), _invalid_none_candidate()]
        report = assess_odom_tf_readiness(cands, OdomTfEvidenceContract())
        self.assertEqual(report.candidate_count, 2)
        self.assertEqual(report.candidate_invalid_count, 1)
        self.assertEqual(report.channels, ("rt/odommodestate",))
        self.assertIn(EMPTY_OR_INVALID_SEQUENCE, report.blocker_codes())
        self.assertFalse(report.odom_publication_ready)

    def test_invalid_first_valid_second_same_result(self):
        cands = [_invalid_none_candidate(), self._valid()]
        report = assess_odom_tf_readiness(cands, OdomTfEvidenceContract())
        self.assertEqual(report.candidate_count, 2)
        self.assertEqual(report.candidate_invalid_count, 1)
        self.assertEqual(report.channels, ("rt/odommodestate",))
        self.assertIn(EMPTY_OR_INVALID_SEQUENCE, report.blocker_codes())

    def test_valid_first_invalid_second_same_result(self):
        cands = [self._valid(), _invalid_none_candidate()]
        report = assess_odom_tf_readiness(cands, OdomTfEvidenceContract())
        self.assertEqual(report.channels, ("rt/odommodestate",))
        self.assertEqual(report.candidate_invalid_count, 1)

    def test_two_invalid_incompatible_channels_no_exception(self):
        # invalid candidates carrying None and an int-like channel: must not try
        # to sort None with str; channels must end up ().
        none_inv = _invalid_none_candidate()
        int_inv = to_odometry_candidate(42)  # source_channel=None too
        report = assess_odom_tf_readiness([none_inv, int_inv], OdomTfEvidenceContract())
        self.assertEqual(report.candidate_count, 2)
        self.assertEqual(report.candidate_invalid_count, 2)
        self.assertEqual(report.channels, ())
        self.assertIn(EMPTY_OR_INVALID_SEQUENCE, report.blocker_codes())
        self.assertFalse(report.offline_contract_ready)


class TestR1CBrokenIterableFailClosed(unittest.TestCase):
    def test_iterable_raising_valueerror_fails_closed(self):
        report = assess_odom_tf_readiness(
            _RaisingIterable(ValueError), OdomTfEvidenceContract())
        self.assertEqual(
            report.classification, CLASSIFICATION_FAIL_CLOSED_INVALID_INPUT)
        self.assertIn(EMPTY_OR_INVALID_SEQUENCE, report.blocker_codes())
        self.assertEqual(
            report.publication_capability, PUBLICATION_CAPABILITY_WITHHELD)

    def test_iterable_raising_runtimeerror_fails_closed(self):
        report = assess_odom_tf_readiness(
            _RaisingIterable(RuntimeError), OdomTfEvidenceContract())
        self.assertEqual(
            report.classification, CLASSIFICATION_FAIL_CLOSED_INVALID_INPUT)
        self.assertIn(EMPTY_OR_INVALID_SEQUENCE, report.blocker_codes())


class TestR1CBrokenMappingFailClosed(unittest.TestCase):
    def test_get_only_object_not_mapping_invalid(self):
        c = to_odometry_candidate(_GetOnlyObject())
        self.assertFalse(c.valid)
        self.assertTrue(any("not a mapping" in e.lower() for e in c.errors))

    def test_mapping_subclass_get_raises_invalid_no_exception(self):
        c = to_odometry_candidate(_RaisingMapping())
        self.assertFalse(c.valid)
        self.assertTrue(any("extraction" in e.lower() or "raised" in e.lower()
                            for e in c.errors))


class TestR1CBooleanNumericRejected(unittest.TestCase):
    def _reject(self, candidate):
        report = assess_odom_tf_readiness([candidate], OdomTfEvidenceContract())
        self.assertEqual(
            report.classification, CLASSIFICATION_FAIL_CLOSED_INVALID_INPUT)
        self.assertIn(CANDIDATE_STRUCTURE_INVALID, report.blocker_codes())

    def test_bool_in_position_rejected(self):
        self._reject(replace(_synthetic_candidate(),
                             position_xyz=(True, 0.0, 0.0)))

    def test_bool_in_velocity_rejected(self):
        self._reject(replace(_synthetic_candidate(),
                             velocity_xyz=(0.0, False, 0.0)))

    def test_bool_in_rpy_rejected(self):
        self._reject(replace(_synthetic_candidate(),
                             rpy=(0.0, 0.0, True)))

    def test_bool_in_quaternion_rejected(self):
        self._reject(replace(_synthetic_candidate(),
                             orientation_quaternion_xyzw=(0.0, 0.0, 0.0, True)))

    def test_bool_yaw_speed_rejected(self):
        self._reject(replace(_synthetic_candidate(), yaw_speed=True))


class TestR1DAdapterMalformedPayloadIntegration(unittest.TestCase):
    """R1D: a malformed adapter payload (bool imu_quaternion, missing
    timestamps) must produce an invalid candidate that the readiness gate
    fails closed on -- never an exception -- with publication still
    withheld by the R1 boundary."""

    def test_malformed_quaternion_payload_fails_closed_through_readiness(self):
        # The exact payload shape reported for R1D: imu_quaternion=True would
        # previously reach tuple(True) inside the adapter and raise TypeError.
        sample = {
            "channel": "rt/odommodestate",
            "receipt_monotonic_ns": 1,
            "position": [0.0, 0.0, 0.0],
            "velocity": [0.0, 0.0, 0.0],
            "yaw_speed": 0.0,
            "imu_quaternion": True,
            "imu_rpy": [0.0, 0.0, 0.0],
        }

        candidate = to_odometry_candidate(sample)
        self.assertFalse(candidate.valid)

        report = assess_odom_tf_readiness([candidate], OdomTfEvidenceContract())
        self.assertEqual(
            report.classification, CLASSIFICATION_FAIL_CLOSED_INVALID_INPUT)
        self.assertIn(EMPTY_OR_INVALID_SEQUENCE, report.blocker_codes())
        self.assertFalse(report.odom_publication_ready)
        self.assertFalse(report.odom_to_base_link_tf_ready)
        self.assertFalse(report.nav2_ready)
        self.assertTrue(report.physical_validation_required)
        self.assertEqual(
            report.publication_capability, PUBLICATION_CAPABILITY_WITHHELD)


class TestR1DR1HostileTimestampIntegration(unittest.TestCase):
    """R1D-R1: an invalid candidate built from hostile timestamps (bool,
    arbitrary object, negative, out-of-range) must still flow through
    assess_odom_tf_readiness without raising, landing on
    EMPTY_OR_INVALID_SEQUENCE with the R1 boundary fully withheld."""

    def test_hostile_timestamp_payload_fails_closed_through_readiness(self):
        sample = {
            "channel": "rt/odommodestate",
            "receipt_monotonic_ns": True,
            "receipt_wall_utc_ns": object(),
            "stamp_sec": -1,
            "stamp_nanosec": 1_000_000_000,
            "position": [0.0, 0.0, 0.0],
            "velocity": [0.0, 0.0, 0.0],
            "yaw_speed": 0.0,
            "imu_quaternion": [0.0, 0.0, 0.0, 1.0],
            "imu_rpy": [0.0, 0.0, 0.0],
        }

        candidate = to_odometry_candidate(sample)
        self.assertFalse(candidate.valid)

        report = assess_odom_tf_readiness([candidate], OdomTfEvidenceContract())
        self.assertEqual(report.candidate_invalid_count, 1)
        self.assertEqual(report.channels, ())
        self.assertIn(EMPTY_OR_INVALID_SEQUENCE, report.blocker_codes())
        self.assertEqual(
            report.publication_capability, PUBLICATION_CAPABILITY_WITHHELD)
        self.assertFalse(report.odom_publication_ready)
        self.assertFalse(report.odom_to_base_link_tf_ready)
        self.assertFalse(report.nav2_ready)
        self.assertTrue(report.physical_validation_required)


class TestR1DR2HostileChannelIntegration(unittest.TestCase):
    """R1D-R2: an invalid candidate built from a hostile (unhashable)
    channel must still flow through assess_odom_tf_readiness without
    raising, landing on EMPTY_OR_INVALID_SEQUENCE with the R1 boundary
    fully withheld."""

    def test_hostile_channel_payload_fails_closed_through_readiness(self):
        sample = {
            "channel": [],
            "receipt_monotonic_ns": 1,
            "position": [0.0, 0.0, 0.0],
            "velocity": [0.0, 0.0, 0.0],
            "yaw_speed": 0.0,
            "imu_quaternion": [0.0, 0.0, 0.0, 1.0],
            "imu_rpy": [0.0, 0.0, 0.0],
            "stamp_sec": 0, "stamp_nanosec": 0,
        }

        candidate = to_odometry_candidate(sample)
        self.assertFalse(candidate.valid)
        self.assertEqual(candidate.source_channel, "<invalid>")

        report = assess_odom_tf_readiness([candidate], OdomTfEvidenceContract())
        self.assertEqual(report.candidate_invalid_count, 1)
        self.assertEqual(report.channels, ())
        self.assertIn(EMPTY_OR_INVALID_SEQUENCE, report.blocker_codes())
        self.assertEqual(
            report.publication_capability, PUBLICATION_CAPABILITY_WITHHELD)
        self.assertFalse(report.odom_publication_ready)
        self.assertFalse(report.odom_to_base_link_tf_ready)
        self.assertFalse(report.nav2_ready)
        self.assertTrue(report.physical_validation_required)


# --- R1D-R3: readiness structural check is exception-safe & strictly typed --
# A GitHub-side audit of the published R1D-R2 commit found: (1) a hostile
# field on a manually-constructed valid=True OdometryCandidate could raise
# INSIDE assess_odom_tf_readiness (source_channel membership test, vector
# len()/iteration, quaternion norm re-iteration); (2) the structural check's
# own numeric helpers used isinstance(), so a hostile int/float subclass
# passed the type gate and then raised on comparison/conversion. Both are
# closed by exact-type gates in `_is_structurally_valid_candidate` plus a
# narrow per-candidate exception boundary in the structural loop itself.

class _PosLenRaises(tuple):
    def __len__(self):
        raise RuntimeError("boom-len-position")


class _VelIterRaises(tuple):
    def __iter__(self):
        raise RuntimeError("boom-iter-velocity")


class _RpyIterRaises(tuple):
    def __iter__(self):
        raise RuntimeError("boom-iter-rpy")


class _QuatSecondIterRaises(tuple):
    """A tuple subclass whose __iter__ succeeds once and raises starting on
    the second call -- exercises the quaternion-norm re-iteration defect."""

    def __new__(cls, values):
        obj = super().__new__(cls, values)
        obj._calls = 0
        return obj

    def __iter__(self):
        self._calls += 1
        if self._calls >= 2:
            raise RuntimeError("boom-second-iter-quaternion")
        return super().__iter__()


class _ChannelEqRaises(str):
    def __eq__(self, other):
        raise RuntimeError("boom-eq-channel")

    def __hash__(self):
        return str.__hash__(self)


class _ReceiptComparisonRaises(int):
    def __gt__(self, other):
        raise RuntimeError("gt")

    def __ge__(self, other):
        raise RuntimeError("ge")

    def __lt__(self, other):
        raise RuntimeError("lt")

    def __le__(self, other):
        raise RuntimeError("le")


class _YawFloatConversionRaises(float):
    def __float__(self):
        raise RuntimeError("float")


class _WarningsIterRaises(list):
    def __iter__(self):
        raise RuntimeError("boom-iter-warnings")


class _OdometryCandidateSubclass(OdometryCandidate):
    """A genuine OdometryCandidate SUBCLASS -- R1D-R3 hardens the structural
    check to `type(c) is OdometryCandidate` exactly, so this must be
    rejected too, not just a duck-typed fake."""


def _hostile_candidate(cls=OdometryCandidate, **overrides):
    base = dict(
        valid=True,
        source_channel="rt/odommodestate",
        receipt_monotonic_ns=100,
        receipt_wall_utc_ns=101,
        timestamp_policy=TIMESTAMP_POLICY,
        message_stamp_sec=5,
        message_stamp_nanosec=7,
        frame_id=FRAME_ID,
        child_frame_id=None,
        position_xyz=(1.0, 2.0, 0.5),
        velocity_xyz=(0.0, 0.0, 0.0),
        yaw_speed=0.05,
        orientation_quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        rpy=(0.0, 0.0, 0.1),
        covariance_policy=COVARIANCE_POLICY,
        covariance_available=False,
        gyro_reliable=True,
        accel_reliable=True,
        warnings=[],
        errors=[],
    )
    base.update(overrides)
    return cls(**base)


class TestR1DR3ReadinessStructuralExceptionSafety(unittest.TestCase):
    """A hostile field on a manually-constructed valid=True candidate must
    never raise inside assess_odom_tf_readiness -- it must fail closed with
    CANDIDATE_STRUCTURE_INVALID, and the R1 boundary must stay withheld."""

    def _assert_fails_closed(self, candidate):
        report = assess_odom_tf_readiness([candidate], OdomTfEvidenceContract())
        self.assertEqual(report.classification, CLASSIFICATION_FAIL_CLOSED_INVALID_INPUT)
        self.assertIn(CANDIDATE_STRUCTURE_INVALID, report.blocker_codes())
        self.assertEqual(report.publication_capability, PUBLICATION_CAPABILITY_WITHHELD)
        self.assertFalse(report.odom_publication_ready)
        self.assertFalse(report.odom_to_base_link_tf_ready)
        self.assertFalse(report.nav2_ready)
        self.assertTrue(report.physical_validation_required)

    def test_hostile_source_channel_fails_closed_no_exception(self):
        c = _hostile_candidate(source_channel=_ChannelEqRaises("rt/odommodestate"))
        self._assert_fails_closed(c)

    def test_hostile_receipt_monotonic_ns_fails_closed_no_exception(self):
        c = _hostile_candidate(receipt_monotonic_ns=_ReceiptComparisonRaises(100))
        self._assert_fails_closed(c)

    def test_hostile_stamp_sec_fails_closed_no_exception(self):
        c = _hostile_candidate(message_stamp_sec=_ReceiptComparisonRaises(5))
        self._assert_fails_closed(c)

    def test_hostile_stamp_nanosec_fails_closed_no_exception(self):
        c = _hostile_candidate(message_stamp_nanosec=_ReceiptComparisonRaises(7))
        self._assert_fails_closed(c)

    def test_hostile_position_len_raises_fails_closed_no_exception(self):
        c = _hostile_candidate(position_xyz=_PosLenRaises((1.0, 2.0, 3.0)))
        self._assert_fails_closed(c)

    def test_hostile_velocity_iter_raises_fails_closed_no_exception(self):
        c = _hostile_candidate(velocity_xyz=_VelIterRaises((1.0, 2.0, 3.0)))
        self._assert_fails_closed(c)

    def test_hostile_rpy_iter_raises_fails_closed_no_exception(self):
        c = _hostile_candidate(rpy=_RpyIterRaises((0.0, 0.0, 0.0)))
        self._assert_fails_closed(c)

    def test_hostile_quaternion_second_iter_raises_fails_closed_no_exception(self):
        c = _hostile_candidate(
            orientation_quaternion_xyzw=_QuatSecondIterRaises((0.0, 0.0, 0.0, 1.0)))
        self._assert_fails_closed(c)

    def test_hostile_yaw_speed_fails_closed_no_exception(self):
        c = _hostile_candidate(yaw_speed=_YawFloatConversionRaises(0.05))
        self._assert_fails_closed(c)

    def test_hostile_warnings_collection_fails_closed_no_exception(self):
        c = _hostile_candidate(warnings=_WarningsIterRaises(["ok"]))
        self._assert_fails_closed(c)

    def test_hostile_errors_collection_fails_closed_no_exception(self):
        c = _hostile_candidate(errors=_WarningsIterRaises([]))
        self._assert_fails_closed(c)

    def test_odometry_candidate_subclass_rejected_no_exception(self):
        c = _hostile_candidate(cls=_OdometryCandidateSubclass)
        self._assert_fails_closed(c)

    def test_malformed_candidate_never_raises_contract(self):
        """Textual contract check: every hostile-field case above, run
        through assess_odom_tf_readiness, must complete without raising."""
        hostile_candidates = [
            _hostile_candidate(source_channel=_ChannelEqRaises("rt/odommodestate")),
            _hostile_candidate(receipt_monotonic_ns=_ReceiptComparisonRaises(100)),
            _hostile_candidate(message_stamp_sec=_ReceiptComparisonRaises(5)),
            _hostile_candidate(message_stamp_nanosec=_ReceiptComparisonRaises(7)),
            _hostile_candidate(position_xyz=_PosLenRaises((1.0, 2.0, 3.0))),
            _hostile_candidate(velocity_xyz=_VelIterRaises((1.0, 2.0, 3.0))),
            _hostile_candidate(rpy=_RpyIterRaises((0.0, 0.0, 0.0))),
            _hostile_candidate(
                orientation_quaternion_xyzw=_QuatSecondIterRaises((0.0, 0.0, 0.0, 1.0))),
            _hostile_candidate(yaw_speed=_YawFloatConversionRaises(0.05)),
            _hostile_candidate(warnings=_WarningsIterRaises(["ok"])),
            _hostile_candidate(cls=_OdometryCandidateSubclass),
        ]
        try:
            for c in hostile_candidates:
                assess_odom_tf_readiness([c], OdomTfEvidenceContract())
        except Exception as exc:
            self.fail(f"assess_odom_tf_readiness raised {type(exc).__name__}: {exc}")

    def test_good_manual_candidate_still_processable(self):
        c = _hostile_candidate()
        report = assess_odom_tf_readiness([c], OdomTfEvidenceContract())
        self.assertNotIn(CANDIDATE_STRUCTURE_INVALID, report.blocker_codes())


if __name__ == "__main__":
    unittest.main()

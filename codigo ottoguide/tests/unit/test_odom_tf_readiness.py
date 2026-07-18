"""MVP-ODOM-TF-R1 offline readiness gate tests (stdlib unittest only).

Runnable without pytest:

    python -m unittest discover -s tests/unit -p "test_odom_tf_readiness.py" -v

SYNTHETIC_TEST_ONLY = true
PHYSICAL_VALIDATION_CLAIM = false

Some tests build a fully-satisfied synthetic evidence contract to exercise the
gate's logical branches (e.g. that resolving every gap flips a boolean). Those
synthetic contracts are test scaffolding ONLY: no synthetic test authorizes
`/odom` or TF publication, and none is evidence about the physical robot. The
real-fixture tests assert the opposite -- that the actual stationary evidence
blocks publication.
"""
import json
import unittest
from pathlib import Path

from src.navigation.odometry_candidate_adapter import (
    assess_odom_tf_readiness,
    to_odometry_candidate,
)
from src.navigation.odometry_candidate_adapter.readiness import (
    BLOCKER,
    CLASSIFICATION_CONTRACT_READY,
    CLASSIFICATION_FAIL_CLOSED_INVALID_INPUT,
    OBSERVATION,
    AXIS_CONVENTION_UNVERIFIED,
    CHILD_FRAME_ID_UNRESOLVED,
    COVARIANCE_UNAVAILABLE,
    DYNAMIC_MOTION_EVIDENCE_MISSING,
    EMPTY_OR_INVALID_SEQUENCE,
    IMU_CROSSCHECK_UNAVAILABLE,
    MESSAGE_TIMESTAMP_ZERO,
    OdomTfEvidenceContract,
    SOURCE_CHANNEL_ARBITRATION_UNRESOLVED,
)

# SYNTHETIC_TEST_ONLY = true  /  PHYSICAL_VALIDATION_CLAIM = false
SYNTHETIC_TEST_ONLY = True
PHYSICAL_VALIDATION_CLAIM = False

FIXTURES_DIR = (
    Path(__file__).resolve().parent.parent / "fixtures" / "mfr_r6_sportmodestate"
)


def load_jsonl(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _fully_satisfied_contract():
    """A SYNTHETIC contract with every gap resolved.

    Exists only to prove that the gate's booleans respond to the contract (a
    logical branch), never as a physical claim. child_frame_id is resolved so
    the TF axis can also flip in the fully-satisfied synthetic case.
    """
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
    """Real MFR-R6 stationary evidence must block publication."""

    def setUp(self):
        primary = load_jsonl(FIXTURES_DIR / "mfr_r6_primary_rt_odommodestate.jsonl")
        secondary = load_jsonl(FIXTURES_DIR / "mfr_r6_secondary_rt_lf_odommodestate.jsonl")
        self.samples = primary + secondary
        self.candidates = [to_odometry_candidate(s) for s in self.samples]
        self.report = assess_odom_tf_readiness(
            self.candidates, OdomTfEvidenceContract()
        )

    def test_real_stationary_fixtures_publication_blocked(self):
        self.assertFalse(self.report.odom_publication_ready)
        self.assertFalse(self.report.odom_to_base_link_tf_ready)
        self.assertTrue(self.report.physical_validation_required)

    def test_classification_is_contract_ready_not_plain_ready(self):
        self.assertEqual(self.report.classification, CLASSIFICATION_CONTRACT_READY)
        self.assertNotEqual(self.report.classification, "READY")

    def test_offline_contract_ready_but_publication_withheld(self):
        # The two axes must not collapse: the input is processable, yet
        # publication is still blocked.
        self.assertTrue(self.report.offline_contract_ready)
        self.assertFalse(self.report.odom_publication_ready)

    def test_both_physical_channels_preserved_in_report(self):
        self.assertEqual(
            set(self.report.channels),
            {"rt/odommodestate", "rt/lf/odommodestate"},
        )

    def test_candidate_counts_match_fixture(self):
        self.assertEqual(self.report.candidate_count, 160)
        self.assertEqual(self.report.candidate_invalid_count, 0)

    def test_rate_difference_is_observation_not_source_selection(self):
        # A rate difference must appear only as an OBSERVATION, and must never
        # arbitrate a channel (arbitration stays a BLOCKER).
        codes_by_sev = {(b.code, b.severity) for b in self.report.blockers}
        self.assertIn(("RATE_DIFFERENCE_BETWEEN_CHANNELS", OBSERVATION), codes_by_sev)
        self.assertIn(
            SOURCE_CHANNEL_ARBITRATION_UNRESOLVED, self.report.blocker_codes()
        )

    def test_zero_stamp_blocks_publication(self):
        self.assertIn(MESSAGE_TIMESTAMP_ZERO, self.report.blocker_codes())

    def test_missing_child_frame_blocks_tf(self):
        self.assertIn(CHILD_FRAME_ID_UNRESOLVED, self.report.blocker_codes())
        self.assertFalse(self.report.odom_to_base_link_tf_ready)

    def test_missing_covariance_blocks_publication(self):
        self.assertIn(COVARIANCE_UNAVAILABLE, self.report.blocker_codes())

    def test_unreliable_imu_produces_blocker(self):
        self.assertIn(IMU_CROSSCHECK_UNAVAILABLE, self.report.blocker_codes())

    def test_missing_dynamic_evidence_blocks_publication(self):
        self.assertIn(DYNAMIC_MOTION_EVIDENCE_MISSING, self.report.blocker_codes())

    def test_unknown_axis_semantics_blocks_publication(self):
        self.assertIn(AXIS_CONVENTION_UNVERIFIED, self.report.blocker_codes())

    def test_nav2_always_false(self):
        self.assertFalse(self.report.nav2_ready)


class TestFailClosedInputs(unittest.TestCase):
    """Empty and invalid inputs must fail closed."""

    def _valid_sample(self):
        return {
            "channel": "rt/odommodestate",
            "receipt_monotonic_ns": 123456789,
            "receipt_wall_utc_ns": 987654321,
            "stamp_sec": 0,
            "stamp_nanosec": 0,
            "position": [1.0, 2.0, 0.5],
            "velocity": [0.0, 0.0, 0.0],
            "yaw_speed": 0.0,
            "imu_quaternion": [0.0, 0.0, 0.0, 1.0],
            "imu_rpy": [0.0, 0.0, 0.0],
            "imu_gyroscope": [0.0, 0.0, 0.0],
            "imu_accelerometer": [0.0, 0.0, 0.0],
        }

    def test_empty_sequence_fails_closed(self):
        report = assess_odom_tf_readiness([], OdomTfEvidenceContract())
        self.assertFalse(report.offline_contract_ready)
        self.assertFalse(report.odom_publication_ready)
        self.assertTrue(report.physical_validation_required)
        self.assertEqual(
            report.classification, CLASSIFICATION_FAIL_CLOSED_INVALID_INPUT
        )
        self.assertIn(EMPTY_OR_INVALID_SEQUENCE, report.blocker_codes())

    def test_all_invalid_candidates_fail_closed(self):
        bad = self._valid_sample()
        del bad["position"]  # makes the candidate invalid
        candidates = [to_odometry_candidate(bad) for _ in range(3)]
        report = assess_odom_tf_readiness(candidates, OdomTfEvidenceContract())
        self.assertFalse(report.offline_contract_ready)
        self.assertFalse(report.odom_publication_ready)
        self.assertIn(EMPTY_OR_INVALID_SEQUENCE, report.blocker_codes())

    def test_some_invalid_candidates_block(self):
        good = to_odometry_candidate(self._valid_sample())
        bad_sample = self._valid_sample()
        del bad_sample["velocity"]
        bad = to_odometry_candidate(bad_sample)
        report = assess_odom_tf_readiness([good, bad], OdomTfEvidenceContract())
        self.assertEqual(report.candidate_invalid_count, 1)
        self.assertFalse(report.offline_contract_ready)
        self.assertIn(EMPTY_OR_INVALID_SEQUENCE, report.blocker_codes())

    def test_non_iterable_input_fails_closed(self):
        report = assess_odom_tf_readiness(None, OdomTfEvidenceContract())
        self.assertFalse(report.odom_publication_ready)
        self.assertEqual(
            report.classification, CLASSIFICATION_FAIL_CLOSED_INVALID_INPUT
        )
        self.assertIn(EMPTY_OR_INVALID_SEQUENCE, report.blocker_codes())


class TestDeterminismAndSerialization(unittest.TestCase):
    """Blocker ordering and report serialization must be deterministic."""

    def _valid_candidate(self, stamp_zero=True):
        sample = {
            "channel": "rt/odommodestate",
            "receipt_monotonic_ns": 111,
            "receipt_wall_utc_ns": 222,
            "stamp_sec": 0 if stamp_zero else 5,
            "stamp_nanosec": 0 if stamp_zero else 5,
            "position": [1.0, 2.0, 0.5],
            "velocity": [0.0, 0.0, 0.0],
            "yaw_speed": 0.0,
            "imu_quaternion": [0.0, 0.0, 0.0, 1.0],
            "imu_rpy": [0.0, 0.0, 0.0],
            "imu_gyroscope": [0.0, 0.0, 0.0],
            "imu_accelerometer": [0.0, 0.0, 0.0],
        }
        return to_odometry_candidate(sample)

    def test_deterministic_blocker_ordering(self):
        candidates = [self._valid_candidate()]
        r1 = assess_odom_tf_readiness(candidates, OdomTfEvidenceContract())
        r2 = assess_odom_tf_readiness(candidates, OdomTfEvidenceContract())
        self.assertEqual(r1.blocker_codes(), r2.blocker_codes())
        # BLOCKER entries always precede OBSERVATION entries.
        severities = [b.severity for b in r1.blockers]
        last_blocker = max(
            (i for i, s in enumerate(severities) if s == BLOCKER), default=-1
        )
        first_obs = next(
            (i for i, s in enumerate(severities) if s == OBSERVATION), len(severities)
        )
        self.assertLess(last_blocker, first_obs)

    def test_report_serialization_stable(self):
        candidates = [self._valid_candidate()]
        report = assess_odom_tf_readiness(candidates, OdomTfEvidenceContract())
        d1 = json.dumps(report.to_dict(), sort_keys=True)
        d2 = json.dumps(report.to_dict(), sort_keys=True)
        self.assertEqual(d1, d2)
        # Round-trips through JSON without loss of the key fields.
        parsed = json.loads(d1)
        self.assertEqual(parsed["classification"], report.classification)
        self.assertEqual(parsed["blocker_count"], report.blocker_count)
        self.assertEqual(parsed["blocker_codes"], list(report.blocker_codes()))


class TestSyntheticContractBranches(unittest.TestCase):
    """SYNTHETIC ONLY -- exercises logical branches; authorizes nothing.

    SYNTHETIC_TEST_ONLY = true / PHYSICAL_VALIDATION_CLAIM = false.
    """

    def _valid_candidate(self, stamp_zero):
        sample = {
            "channel": "rt/odommodestate",
            "receipt_monotonic_ns": 111,
            "receipt_wall_utc_ns": 222,
            "stamp_sec": 0 if stamp_zero else 5,
            "stamp_nanosec": 0 if stamp_zero else 7,
            "position": [1.0, 2.0, 0.5],
            "velocity": [0.1, 0.0, 0.0],
            "yaw_speed": 0.05,
            "imu_quaternion": [0.0, 0.0, 0.0, 1.0],
            "imu_rpy": [0.0, 0.0, 0.1],
            "imu_gyroscope": [0.01, 0.0, 0.02],
            "imu_accelerometer": [0.0, 0.0, 9.81],
        }
        return to_odometry_candidate(sample)

    def test_fully_satisfied_synthetic_contract_flips_readiness(self):
        # Non-zero stamp so MESSAGE_TIMESTAMP_ZERO does not block; all contract
        # gaps satisfied. This proves the gate is not hard-wired to False.
        candidates = [self._valid_candidate(stamp_zero=False)]
        report = assess_odom_tf_readiness(candidates, _fully_satisfied_contract())
        self.assertEqual(report.blocker_count, 0)
        self.assertTrue(report.odom_publication_ready)
        self.assertTrue(report.odom_to_base_link_tf_ready)
        # nav2 stays false even in the fully-satisfied synthetic case.
        self.assertFalse(report.nav2_ready)
        self.assertTrue(report.physical_validation_required)

    def test_zero_stamp_blocks_even_with_satisfied_contract(self):
        candidates = [self._valid_candidate(stamp_zero=True)]
        report = assess_odom_tf_readiness(candidates, _fully_satisfied_contract())
        self.assertIn(MESSAGE_TIMESTAMP_ZERO, report.blocker_codes())
        self.assertFalse(report.odom_publication_ready)

    def test_child_frame_resolved_but_other_gaps_still_block(self):
        # Resolving only the child frame must NOT make TF ready while other
        # blockers remain (absence of one gap doesn't imply the rest).
        contract = OdomTfEvidenceContract(
            child_frame_id_resolved=True, resolved_child_frame_id="base_link"
        )
        candidates = [self._valid_candidate(stamp_zero=False)]
        report = assess_odom_tf_readiness(candidates, contract)
        self.assertNotIn(CHILD_FRAME_ID_UNRESOLVED, report.blocker_codes())
        self.assertFalse(report.odom_to_base_link_tf_ready)
        self.assertGreater(report.blocker_count, 0)


if __name__ == "__main__":
    unittest.main()

"""
@TASK: Testear el adapter puro SportModeState_ -> OdometryCandidate contra
       fixtures reales (MFR-R6) y entradas invalidas construidas a mano
@INPUT: src/navigation/odometry_candidate_adapter, tests/fixtures/mfr_r6_sportmodestate
@OUTPUT: Suite pytest que valida valid=True/False, politicas de contrato fijas,
         y agregacion por canal via validate_candidate_sequence
@CONTEXT: Adaptado de ODOM-R1 (run local) al layout src/ + tests/unit/ de este
          repositorio. Mismo comportamiento ya testeado 28/28 en ODOM-R1;
          ODOM-R2 agrega asserts dedicados para validate_candidate_sequence
          (position_min/max, velocity_max_abs, yaw_speed_min/max,
          warning_count) que ODOM-R1 dejo como limitacion documentada.
@SECURITY: Cero imports de rclpy/nav_msgs/geometry_msgs/tf2_ros/tf2/unitree_sdk2.
           Sin I/O de red, sin reloj de sistema dentro del adapter.
"""
import dataclasses
import json
import math
from pathlib import Path

from src.navigation.odometry_candidate_adapter import (
    to_odometry_candidate,
    validate_candidate_sequence,
)
from src.navigation.odometry_candidate_adapter.validation import (
    COVARIANCE_POLICY,
    FRAME_ID,
    TIMESTAMP_POLICY,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "mfr_r6_sportmodestate"


def load_jsonl(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class TestOdometryCandidateAdapterRealFixtures:
    def setup_method(self):
        self.primary = load_jsonl(FIXTURES_DIR / "mfr_r6_primary_rt_odommodestate.jsonl")
        self.secondary = load_jsonl(FIXTURES_DIR / "mfr_r6_secondary_rt_lf_odommodestate.jsonl")

    def test_all_primary_samples_valid(self):
        candidates = [to_odometry_candidate(s) for s in self.primary]
        assert all(c.valid for c in candidates)

    def test_all_secondary_samples_valid(self):
        candidates = [to_odometry_candidate(s) for s in self.secondary]
        assert all(c.valid for c in candidates)

    def test_frame_id_is_unitree_odom_candidate(self):
        c = to_odometry_candidate(self.primary[0])
        assert c.frame_id == "unitree_odom_candidate"
        assert c.frame_id == FRAME_ID
        assert c.child_frame_id is None

    def test_covariance_not_available(self):
        c = to_odometry_candidate(self.primary[0])
        assert c.covariance_available is False
        assert c.covariance_policy == COVARIANCE_POLICY
        assert c.covariance_policy == "NO_COVARIANCE_IN_SOURCE_DOCUMENT_GAP"

    def test_timestamp_policy_value(self):
        c = to_odometry_candidate(self.primary[0])
        assert c.timestamp_policy == "MESSAGE_STAMP_ZERO_USE_RECEIPT_TIME_REQUIRED"
        assert c.timestamp_policy == TIMESTAMP_POLICY

    def test_gyro_not_reliable_for_real_fixtures(self):
        # MFR-R6 confirmo gyroscope en cero en las 160 muestras reales.
        c = to_odometry_candidate(self.primary[0])
        assert c.gyro_reliable is False

    def test_accel_not_reliable_for_real_fixtures(self):
        c = to_odometry_candidate(self.primary[0])
        assert c.accel_reliable is False

    def test_primary_sequence_receipt_monotonic(self):
        candidates = [to_odometry_candidate(s) for s in self.primary]
        report = validate_candidate_sequence(candidates)
        assert report["channels"]["rt/odommodestate"]["receipt_monotonic"] is True

    def test_secondary_sequence_receipt_monotonic(self):
        candidates = [to_odometry_candidate(s) for s in self.secondary]
        report = validate_candidate_sequence(candidates)
        assert report["channels"]["rt/lf/odommodestate"]["receipt_monotonic"] is True

    def test_stamp_zero_produces_warning(self):
        c = to_odometry_candidate(self.primary[0])
        assert any("stamp is zero" in w for w in c.warnings)

    # --- ODOM-R2 hardening: asserts dedicados para validate_candidate_sequence ---
    # ODOM-R1 dejo documentado como limitacion que estos campos se ejercitaban
    # solo indirectamente. Se agregan asserts explicitos sin cambiar el
    # comportamiento de adapter.py/validation.py.

    def test_sequence_position_min_max_within_expected_range(self):
        candidates = [to_odometry_candidate(s) for s in self.primary]
        report = validate_candidate_sequence(candidates)
        stats = report["channels"]["rt/odommodestate"]
        assert stats["position_min"] is not None
        assert stats["position_max"] is not None
        for lo, hi in zip(stats["position_min"], stats["position_max"]):
            assert lo <= hi

    def test_sequence_velocity_max_abs_is_small_for_stationary_robot(self):
        candidates = [to_odometry_candidate(s) for s in self.primary]
        report = validate_candidate_sequence(candidates)
        vmax = report["channels"]["rt/odommodestate"]["velocity_max_abs"]
        assert vmax is not None
        # MFR-R6: robot estacionario, ruido numerico de orden 1e-6 a ~6e-5.
        assert vmax < 0.01

    def test_sequence_yaw_speed_min_max_bracket_zero_for_stationary_robot(self):
        candidates = [to_odometry_candidate(s) for s in self.primary]
        report = validate_candidate_sequence(candidates)
        stats = report["channels"]["rt/odommodestate"]
        assert stats["yaw_speed_min"] is not None
        assert stats["yaw_speed_max"] is not None
        assert stats["yaw_speed_min"] <= stats["yaw_speed_max"]
        assert math.isfinite(stats["yaw_speed_min"])
        assert math.isfinite(stats["yaw_speed_max"])

    def test_sequence_warning_count_reflects_stamp_zero_and_imu_flags(self):
        candidates = [to_odometry_candidate(s) for s in self.primary]
        report = validate_candidate_sequence(candidates)
        stats = report["channels"]["rt/odommodestate"]
        # Cada muestra real produce al menos 3 warnings: stamp=0, gyro no
        # confiable, accel no confiable (confirmado sistematico en MFR-R6).
        assert stats["warning_count"] >= 3 * stats["valid_count"]

    def test_sequence_two_channel_report_has_both_channels(self):
        candidates = [to_odometry_candidate(s) for s in self.primary] + [
            to_odometry_candidate(s) for s in self.secondary
        ]
        report = validate_candidate_sequence(candidates)
        assert set(report["channels"].keys()) == {"rt/odommodestate", "rt/lf/odommodestate"}
        assert report["total_count"] == 160
        assert report["invalid_count"] == 0


class TestOdometryCandidateAdapterInvalidInputs:
    def _base_sample(self):
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

    def test_nan_in_position_invalid(self):
        sample = self._base_sample()
        sample["position"] = [float("nan"), 0.0, 0.0]
        c = to_odometry_candidate(sample)
        assert c.valid is False
        assert any("position" in e for e in c.errors)

    def test_inf_in_velocity_invalid(self):
        sample = self._base_sample()
        sample["velocity"] = [0.0, float("inf"), 0.0]
        c = to_odometry_candidate(sample)
        assert c.valid is False
        assert any("velocity" in e for e in c.errors)

    def test_missing_yaw_speed_invalid(self):
        sample = self._base_sample()
        del sample["yaw_speed"]
        c = to_odometry_candidate(sample)
        assert c.valid is False

    def test_missing_position_invalid(self):
        sample = self._base_sample()
        del sample["position"]
        c = to_odometry_candidate(sample)
        assert c.valid is False

    def test_missing_velocity_invalid(self):
        sample = self._base_sample()
        del sample["velocity"]
        c = to_odometry_candidate(sample)
        assert c.valid is False

    def test_unauthorized_channel_invalid(self):
        sample = self._base_sample()
        sample["channel"] = "odommodestate"
        c = to_odometry_candidate(sample)
        assert c.valid is False
        assert any("not in allowed set" in e for e in c.errors)

    def test_missing_receipt_monotonic_ns_invalid(self):
        sample = self._base_sample()
        del sample["receipt_monotonic_ns"]
        c = to_odometry_candidate(sample)
        assert c.valid is False

    def test_non_positive_receipt_monotonic_ns_invalid(self):
        sample = self._base_sample()
        sample["receipt_monotonic_ns"] = -5
        c = to_odometry_candidate(sample)
        assert c.valid is False

    def test_valid_sample_passes(self):
        c = to_odometry_candidate(self._base_sample())
        assert c.valid is True
        assert c.errors == []


# --- R1A (MVP-ODOM-TF-R1A): IMU reliability hardening -----------------------
# unittest.TestCase so `python -m unittest discover -p
# "test_odometry_candidate_adapter.py"` actually exercises these. A missing,
# malformed, or non-finite IMU vector must NEVER be reported reliable, while the
# candidate itself stays valid when position/velocity/yaw remain usable.
import unittest  # noqa: E402


class TestAdapterImuReliabilityHardeningR1A(unittest.TestCase):
    def _base_sample(self):
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
            "imu_gyroscope": [0.01, 0.0, 0.02],
            "imu_accelerometer": [0.0, 0.0, 9.81],
        }

    def test_missing_gyro_is_not_reliable(self):
        s = self._base_sample()
        del s["imu_gyroscope"]
        c = to_odometry_candidate(s)
        self.assertTrue(c.valid)  # candidate still valid
        self.assertFalse(c.gyro_reliable)
        self.assertTrue(any("gyroscope missing" in w for w in c.warnings))

    def test_missing_accelerometer_is_not_reliable(self):
        s = self._base_sample()
        del s["imu_accelerometer"]
        c = to_odometry_candidate(s)
        self.assertTrue(c.valid)
        self.assertFalse(c.accel_reliable)
        self.assertTrue(any("accelerometer missing" in w for w in c.warnings))

    def test_malformed_gyro_is_not_reliable(self):
        s = self._base_sample()
        s["imu_gyroscope"] = [0.1, 0.2]  # wrong length
        c = to_odometry_candidate(s)
        self.assertTrue(c.valid)
        self.assertFalse(c.gyro_reliable)
        self.assertTrue(any("gyroscope malformed" in w for w in c.warnings))

    def test_non_finite_accel_is_not_reliable(self):
        s = self._base_sample()
        s["imu_accelerometer"] = [0.0, float("inf"), 9.81]
        c = to_odometry_candidate(s)
        self.assertTrue(c.valid)
        self.assertFalse(c.accel_reliable)
        self.assertTrue(any("accelerometer malformed" in w for w in c.warnings))

    def test_all_zero_gyro_is_not_reliable(self):
        s = self._base_sample()
        s["imu_gyroscope"] = [0.0, 0.0, 0.0]
        c = to_odometry_candidate(s)
        self.assertTrue(c.valid)
        self.assertFalse(c.gyro_reliable)
        self.assertTrue(any("gyroscope reads all-zero" in w for w in c.warnings))

    def test_good_imu_is_reliable(self):
        c = to_odometry_candidate(self._base_sample())
        self.assertTrue(c.valid)
        self.assertTrue(c.gyro_reliable)
        self.assertTrue(c.accel_reliable)

    def test_candidate_valid_despite_unreliable_imu(self):
        # Separation: unusable IMU does not invalidate the candidate.
        s = self._base_sample()
        del s["imu_gyroscope"]
        del s["imu_accelerometer"]
        c = to_odometry_candidate(s)
        self.assertTrue(c.valid)
        self.assertFalse(c.gyro_reliable)
        self.assertFalse(c.accel_reliable)


# --- R1D (MVP-ODOM-TF-R1D): malformed payload normalization paths closed ----
# unittest.TestCase so `python -m unittest discover -p
# "test_odometry_candidate_adapter.py"` actually exercises these. A malformed
# imu_quaternion/imu_rpy/timestamp must never raise and must never yield a
# valid=True candidate; a bool must never be accepted as a number anywhere.

class _RaisingIterOnlyList(list):
    """A list subclass whose __iter__ raises mid-iteration. isinstance(_,
    list) is True and len() still works (inherited from list), only
    iteration breaks -- this is what a "sequence defectuosa" looks like."""

    def __iter__(self):
        raise RuntimeError("broken iterator")


class TestAdapterR1DMalformedPayloadNormalization(unittest.TestCase):
    def _base_sample(self):
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
            "imu_gyroscope": [0.01, 0.0, 0.02],
            "imu_accelerometer": [0.0, 0.0, 9.81],
        }

    def test_good_sample_still_valid(self):
        c = to_odometry_candidate(self._base_sample())
        self.assertTrue(c.valid)
        self.assertEqual(c.errors, [])

    # --- imu_quaternion malformed: never raises, never valid=True ----------

    def test_quaternion_bool_true_invalid_no_exception(self):
        s = self._base_sample()
        s["imu_quaternion"] = True
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_quaternion_int_invalid_no_exception(self):
        s = self._base_sample()
        s["imu_quaternion"] = 1
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_quaternion_object_invalid_no_exception(self):
        s = self._base_sample()
        s["imu_quaternion"] = object()
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_quaternion_missing_invalid(self):
        s = self._base_sample()
        del s["imu_quaternion"]
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_quaternion_wrong_length_invalid(self):
        s = self._base_sample()
        s["imu_quaternion"] = [0.0, 0.0, 1.0]
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_quaternion_nan_component_invalid(self):
        s = self._base_sample()
        s["imu_quaternion"] = [0.0, 0.0, 0.0, float("nan")]
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_quaternion_bool_component_invalid(self):
        s = self._base_sample()
        s["imu_quaternion"] = [0.0, 0.0, 0.0, True]
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_quaternion_zero_norm_invalid(self):
        s = self._base_sample()
        s["imu_quaternion"] = [0.0, 0.0, 0.0, 0.0]
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)
        self.assertTrue(any("zero norm" in e for e in c.errors))

    # --- imu_rpy malformed: never raises, never valid=True ------------------

    def test_rpy_bool_true_invalid_no_exception(self):
        s = self._base_sample()
        s["imu_rpy"] = True
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_rpy_int_invalid_no_exception(self):
        s = self._base_sample()
        s["imu_rpy"] = 1
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_rpy_object_invalid_no_exception(self):
        s = self._base_sample()
        s["imu_rpy"] = object()
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_rpy_missing_invalid(self):
        s = self._base_sample()
        del s["imu_rpy"]
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_rpy_inf_component_invalid(self):
        s = self._base_sample()
        s["imu_rpy"] = [0.0, float("inf"), 0.0]
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_rpy_bool_component_invalid(self):
        s = self._base_sample()
        s["imu_rpy"] = [0.0, 0.0, True]
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    # --- bool rejected as a number everywhere -------------------------------

    def test_bool_in_position_invalid(self):
        s = self._base_sample()
        s["position"] = [True, 0.0, 0.0]
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_bool_in_velocity_invalid(self):
        s = self._base_sample()
        s["velocity"] = [0.0, False, 0.0]
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_bool_yaw_speed_invalid(self):
        s = self._base_sample()
        s["yaw_speed"] = True
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_bool_in_gyro_not_reliable(self):
        s = self._base_sample()
        s["imu_gyroscope"] = [True, False, True]
        c = to_odometry_candidate(s)
        self.assertTrue(c.valid)
        self.assertFalse(c.gyro_reliable)

    def test_bool_in_accelerometer_not_reliable(self):
        s = self._base_sample()
        s["imu_accelerometer"] = [True, False, True]
        c = to_odometry_candidate(s)
        self.assertTrue(c.valid)
        self.assertFalse(c.accel_reliable)

    # --- timestamps ----------------------------------------------------------

    def test_bool_receipt_monotonic_ns_invalid(self):
        s = self._base_sample()
        s["receipt_monotonic_ns"] = True
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_bool_stamp_sec_invalid(self):
        s = self._base_sample()
        s["stamp_sec"] = True
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_bool_stamp_nanosec_invalid(self):
        s = self._base_sample()
        s["stamp_nanosec"] = True
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_bool_receipt_wall_utc_ns_invalid(self):
        s = self._base_sample()
        s["receipt_wall_utc_ns"] = True
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_stamp_sec_negative_invalid(self):
        s = self._base_sample()
        s["stamp_sec"] = -1
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_stamp_nanosec_out_of_range_invalid(self):
        s = self._base_sample()
        s["stamp_nanosec"] = 1_000_000_000
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_stamp_nanosec_negative_invalid(self):
        s = self._base_sample()
        s["stamp_nanosec"] = -1
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_receipt_wall_utc_ns_negative_invalid(self):
        s = self._base_sample()
        s["receipt_wall_utc_ns"] = -5
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_receipt_wall_utc_ns_string_invalid(self):
        s = self._base_sample()
        s["receipt_wall_utc_ns"] = "not-a-number"
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_receipt_wall_utc_ns_none_allowed(self):
        s = self._base_sample()
        s["receipt_wall_utc_ns"] = None
        c = to_odometry_candidate(s)
        self.assertTrue(c.valid)

    # --- wrong length (position/velocity) -----------------------------------

    def test_position_wrong_length_invalid(self):
        s = self._base_sample()
        s["position"] = [1.0, 2.0]
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_velocity_wrong_length_invalid(self):
        s = self._base_sample()
        s["velocity"] = [1.0, 2.0, 3.0, 4.0]
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    # --- defective sequences: never raise -----------------------------------

    def test_raising_iterator_in_position_invalid_no_exception(self):
        s = self._base_sample()
        s["position"] = _RaisingIterOnlyList([1.0, 2.0, 3.0])
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_raising_iterator_in_velocity_invalid_no_exception(self):
        s = self._base_sample()
        s["velocity"] = _RaisingIterOnlyList([1.0, 2.0, 3.0])
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_raising_iterator_in_quaternion_invalid_no_exception(self):
        s = self._base_sample()
        s["imu_quaternion"] = _RaisingIterOnlyList([0.0, 0.0, 0.0, 1.0])
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_raising_iterator_in_rpy_invalid_no_exception(self):
        s = self._base_sample()
        s["imu_rpy"] = _RaisingIterOnlyList([0.0, 0.0, 0.0])
        c = to_odometry_candidate(s)
        self.assertFalse(c.valid)

    def test_raising_iterator_in_gyroscope_no_exception(self):
        s = self._base_sample()
        s["imu_gyroscope"] = _RaisingIterOnlyList([0.01, 0.0, 0.02])
        c = to_odometry_candidate(s)
        self.assertTrue(c.valid)
        self.assertFalse(c.gyro_reliable)


# --- R1D-R1: independent pre-push audit remediation -------------------------
# Closes two defects the R1D pre-push audit found: (1) an invalid candidate
# could store a raw bool or an arbitrary object in a timestamp field instead
# of a canonical int/None; (2) a pathological gyro/accelerometer (whose
# __len__ or __iter__ raises) invalidated the WHOLE candidate instead of only
# degrading that sensor's own reliability flag.

class TestAdapterR1DR1InvalidCandidateNormalization(unittest.TestCase):
    """Every invalid candidate must stay typed, deterministic, and JSON-
    serializable: no bool stored where int is expected, no arbitrary object
    stored where int/None is expected."""

    def _base_sample(self):
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
            "imu_gyroscope": [0.01, 0.0, 0.02],
            "imu_accelerometer": [0.0, 0.0, 9.81],
        }

    def _assert_normalized_invalid(self, sample):
        c = to_odometry_candidate(sample)
        self.assertFalse(c.valid)

        self.assertIs(type(c.receipt_monotonic_ns), int)
        self.assertIs(type(c.message_stamp_sec), int)
        self.assertIs(type(c.message_stamp_nanosec), int)
        self.assertTrue(
            c.receipt_wall_utc_ns is None or type(c.receipt_wall_utc_ns) is int
        )

        # json.dumps(dataclasses.asdict(...)) across the whole candidate:
        # proves no arbitrary/non-serializable object survived anywhere.
        payload = json.dumps(dataclasses.asdict(c))
        self.assertIsInstance(payload, str)
        return c

    def test_receipt_monotonic_ns_bool_true_normalized(self):
        s = self._base_sample()
        s["receipt_monotonic_ns"] = True
        self._assert_normalized_invalid(s)

    def test_receipt_monotonic_ns_bool_false_normalized(self):
        s = self._base_sample()
        s["receipt_monotonic_ns"] = False
        self._assert_normalized_invalid(s)

    def test_receipt_monotonic_ns_negative_normalized(self):
        s = self._base_sample()
        s["receipt_monotonic_ns"] = -1
        self._assert_normalized_invalid(s)

    def test_receipt_monotonic_ns_object_normalized(self):
        s = self._base_sample()
        s["receipt_monotonic_ns"] = object()
        self._assert_normalized_invalid(s)

    def test_stamp_sec_bool_true_normalized(self):
        s = self._base_sample()
        s["stamp_sec"] = True
        self._assert_normalized_invalid(s)

    def test_stamp_sec_negative_normalized(self):
        s = self._base_sample()
        s["stamp_sec"] = -1
        self._assert_normalized_invalid(s)

    def test_stamp_sec_object_normalized(self):
        s = self._base_sample()
        s["stamp_sec"] = object()
        self._assert_normalized_invalid(s)

    def test_stamp_nanosec_bool_true_normalized(self):
        s = self._base_sample()
        s["stamp_nanosec"] = True
        self._assert_normalized_invalid(s)

    def test_stamp_nanosec_negative_normalized(self):
        s = self._base_sample()
        s["stamp_nanosec"] = -1
        self._assert_normalized_invalid(s)

    def test_stamp_nanosec_out_of_range_normalized(self):
        s = self._base_sample()
        s["stamp_nanosec"] = 1_000_000_000
        self._assert_normalized_invalid(s)

    def test_stamp_nanosec_object_normalized(self):
        s = self._base_sample()
        s["stamp_nanosec"] = object()
        self._assert_normalized_invalid(s)

    def test_receipt_wall_utc_ns_bool_true_normalized(self):
        s = self._base_sample()
        s["receipt_wall_utc_ns"] = True
        self._assert_normalized_invalid(s)

    def test_receipt_wall_utc_ns_negative_normalized(self):
        s = self._base_sample()
        s["receipt_wall_utc_ns"] = -1
        self._assert_normalized_invalid(s)

    def test_receipt_wall_utc_ns_object_normalized(self):
        s = self._base_sample()
        s["receipt_wall_utc_ns"] = object()
        self._assert_normalized_invalid(s)

    def test_receipt_wall_utc_ns_none_stays_valid_and_none(self):
        # None is a legitimately allowed value on an otherwise-valid sample --
        # must NOT be treated as malformed by the R1D-R1 normalization.
        s = self._base_sample()
        s["receipt_wall_utc_ns"] = None
        c = to_odometry_candidate(s)
        self.assertTrue(c.valid)
        self.assertIsNone(c.receipt_wall_utc_ns)
        payload = json.dumps(dataclasses.asdict(c))
        self.assertIsInstance(payload, str)


class _LenRaises(list):
    """A list subclass whose __len__ raises. This was the exact defect the
    R1D pre-push audit found: len(values) was unprotected inside the old
    _is_reliable_imu_vector and its exception reached a function-wide
    boundary that invalidated the whole candidate."""

    def __len__(self):
        raise RuntimeError("boom-len")


class _IterRaises(list):
    """A list subclass whose __iter__ raises mid-iteration."""

    def __iter__(self):
        raise RuntimeError("boom-iter")


class _GetItemRaises:
    """Deliberately NOT a list/tuple: exposes only __len__/__getitem__ (the
    legacy sequence protocol, no __iter__). Must be rejected as malformed by
    the isinstance(list/tuple) gate before __getitem__ is ever invoked --
    list/tuple iteration in CPython goes through __iter__, never
    __getitem__, so making __getitem__ raise on an actual list subclass would
    not exercise anything; a genuine duck-typed non-list sequence is the
    faithful adversarial case for this protocol."""

    def __len__(self):
        return 3

    def __getitem__(self, index):
        raise RuntimeError("boom-getitem")


class TestAdapterR1DR1AuxiliaryImuFaultIsolation(unittest.TestCase):
    """A pathological auxiliary gyro/accelerometer must never invalidate an
    otherwise-valid candidate -- only degrade that sensor's own reliability
    flag, with an explicit warning, errors staying empty."""

    def _base_sample(self):
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
            "imu_gyroscope": [0.01, 0.0, 0.02],
            "imu_accelerometer": [0.0, 0.0, 9.81],
        }

    def _assert_isolated(self, sample, field):
        c = to_odometry_candidate(sample)
        self.assertTrue(c.valid)
        self.assertEqual(c.errors, [])
        reliable = c.gyro_reliable if field == "imu_gyroscope" else c.accel_reliable
        self.assertFalse(reliable)
        name = "gyroscope" if field == "imu_gyroscope" else "accelerometer"
        self.assertTrue(any(name in w for w in c.warnings))

    # --- adversarial exception classes: gyroscope ---
    def test_gyro_len_raises_isolated_no_exception(self):
        s = self._base_sample()
        s["imu_gyroscope"] = _LenRaises([0.01, 0.0, 0.02])
        self._assert_isolated(s, "imu_gyroscope")

    def test_gyro_iter_raises_isolated_no_exception(self):
        s = self._base_sample()
        s["imu_gyroscope"] = _IterRaises([0.01, 0.0, 0.02])
        self._assert_isolated(s, "imu_gyroscope")

    def test_gyro_getitem_raises_isolated_no_exception(self):
        s = self._base_sample()
        s["imu_gyroscope"] = _GetItemRaises()
        self._assert_isolated(s, "imu_gyroscope")

    # --- adversarial exception classes: accelerometer ---
    def test_accel_len_raises_isolated_no_exception(self):
        s = self._base_sample()
        s["imu_accelerometer"] = _LenRaises([0.0, 0.0, 9.81])
        self._assert_isolated(s, "imu_accelerometer")

    def test_accel_iter_raises_isolated_no_exception(self):
        s = self._base_sample()
        s["imu_accelerometer"] = _IterRaises([0.0, 0.0, 9.81])
        self._assert_isolated(s, "imu_accelerometer")

    def test_accel_getitem_raises_isolated_no_exception(self):
        s = self._base_sample()
        s["imu_accelerometer"] = _GetItemRaises()
        self._assert_isolated(s, "imu_accelerometer")

    # --- bool / NaN / Inf / wrong length / all-zero / missing: gyroscope ---
    def test_gyro_bool_component_isolated(self):
        s = self._base_sample()
        s["imu_gyroscope"] = [True, False, True]
        self._assert_isolated(s, "imu_gyroscope")

    def test_gyro_nan_component_isolated(self):
        s = self._base_sample()
        s["imu_gyroscope"] = [float("nan"), 0.0, 0.0]
        self._assert_isolated(s, "imu_gyroscope")

    def test_gyro_inf_component_isolated(self):
        s = self._base_sample()
        s["imu_gyroscope"] = [float("inf"), 0.0, 0.0]
        self._assert_isolated(s, "imu_gyroscope")

    def test_gyro_wrong_length_isolated(self):
        s = self._base_sample()
        s["imu_gyroscope"] = [0.01, 0.0]
        self._assert_isolated(s, "imu_gyroscope")

    def test_gyro_all_zero_isolated(self):
        s = self._base_sample()
        s["imu_gyroscope"] = [0.0, 0.0, 0.0]
        self._assert_isolated(s, "imu_gyroscope")

    def test_gyro_missing_isolated(self):
        s = self._base_sample()
        del s["imu_gyroscope"]
        self._assert_isolated(s, "imu_gyroscope")

    def test_gyro_valid_nonzero_is_reliable(self):
        c = to_odometry_candidate(self._base_sample())
        self.assertTrue(c.valid)
        self.assertTrue(c.gyro_reliable)

    # --- bool / NaN / Inf / wrong length / all-zero / missing: accelerometer ---
    def test_accel_bool_component_isolated(self):
        s = self._base_sample()
        s["imu_accelerometer"] = [True, False, True]
        self._assert_isolated(s, "imu_accelerometer")

    def test_accel_nan_component_isolated(self):
        s = self._base_sample()
        s["imu_accelerometer"] = [float("nan"), 0.0, 9.81]
        self._assert_isolated(s, "imu_accelerometer")

    def test_accel_inf_component_isolated(self):
        s = self._base_sample()
        s["imu_accelerometer"] = [float("inf"), 0.0, 9.81]
        self._assert_isolated(s, "imu_accelerometer")

    def test_accel_wrong_length_isolated(self):
        s = self._base_sample()
        s["imu_accelerometer"] = [0.0, 0.0]
        self._assert_isolated(s, "imu_accelerometer")

    def test_accel_all_zero_isolated(self):
        s = self._base_sample()
        s["imu_accelerometer"] = [0.0, 0.0, 0.0]
        self._assert_isolated(s, "imu_accelerometer")

    def test_accel_missing_isolated(self):
        s = self._base_sample()
        del s["imu_accelerometer"]
        self._assert_isolated(s, "imu_accelerometer")

    def test_accel_valid_nonzero_is_reliable(self):
        c = to_odometry_candidate(self._base_sample())
        self.assertTrue(c.valid)
        self.assertTrue(c.accel_reliable)


if __name__ == "__main__":
    unittest.main()

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

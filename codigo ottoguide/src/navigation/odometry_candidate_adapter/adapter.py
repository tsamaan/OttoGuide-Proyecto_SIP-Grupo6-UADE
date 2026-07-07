"""ODOM-R1 offline adapter: SportModeState_ sample dict -> OdometryCandidate.

Pure functions only. No ROS, no DDS, no Unitree SDK, no network I/O, no file
I/O, no wall-clock reads inside the functions -- all timing comes from the
`receipt_monotonic_ns` / `receipt_wall_utc_ns` fields already present on the
input sample (captured at subscription time in MFR-R6, not read here).

This module does not publish anything and does not construct nav_msgs or TF
transforms. See MFR_R6_SPORTMODESTATE_ODOM_CONTRACT.md for the full contract
this implements.
"""
from .models import OdometryCandidate
from .validation import (
    ALLOWED_SOURCE_CHANNELS,
    COVARIANCE_POLICY,
    FRAME_ID,
    TIMESTAMP_POLICY,
    all_finite,
    is_all_zero,
    is_finite_number,
    is_positive_int,
)


def _invalid(source_channel, receipt_monotonic_ns, receipt_wall_utc_ns,
             message_stamp_sec, message_stamp_nanosec, errors, warnings=None):
    return OdometryCandidate(
        valid=False,
        source_channel=source_channel,
        receipt_monotonic_ns=receipt_monotonic_ns if isinstance(receipt_monotonic_ns, int) else 0,
        receipt_wall_utc_ns=receipt_wall_utc_ns,
        timestamp_policy=TIMESTAMP_POLICY,
        message_stamp_sec=message_stamp_sec if isinstance(message_stamp_sec, int) else 0,
        message_stamp_nanosec=message_stamp_nanosec if isinstance(message_stamp_nanosec, int) else 0,
        frame_id=FRAME_ID,
        child_frame_id=None,
        position_xyz=(0.0, 0.0, 0.0),
        velocity_xyz=(0.0, 0.0, 0.0),
        yaw_speed=0.0,
        orientation_quaternion_xyzw=(0.0, 0.0, 0.0, 0.0),
        rpy=(0.0, 0.0, 0.0),
        covariance_policy=COVARIANCE_POLICY,
        covariance_available=False,
        gyro_reliable=False,
        accel_reliable=False,
        warnings=list(warnings) if warnings else [],
        errors=list(errors),
    )


def to_odometry_candidate(sample: dict) -> OdometryCandidate:
    """Pure transform: SportModeState_ sample dict -> OdometryCandidate.

    `sample` is expected to carry the fields captured by the MFR-R6 probe:
    channel, receipt_monotonic_ns, receipt_wall_utc_ns, stamp_sec,
    stamp_nanosec, position, velocity, yaw_speed, imu_quaternion, imu_rpy,
    imu_gyroscope, imu_accelerometer. Missing/malformed fields make the
    result invalid rather than raising -- callers get a typed, inspectable
    failure instead of an exception from untrusted input.
    """
    channel = sample.get("channel")
    receipt_monotonic_ns = sample.get("receipt_monotonic_ns")
    receipt_wall_utc_ns = sample.get("receipt_wall_utc_ns")
    stamp_sec = sample.get("stamp_sec")
    stamp_nanosec = sample.get("stamp_nanosec")
    position = sample.get("position")
    velocity = sample.get("velocity")
    yaw_speed = sample.get("yaw_speed")
    quaternion = sample.get("imu_quaternion")
    rpy = sample.get("imu_rpy")
    gyroscope = sample.get("imu_gyroscope")
    accelerometer = sample.get("imu_accelerometer")

    errors = []

    if channel not in ALLOWED_SOURCE_CHANNELS:
        errors.append(
            f"source_channel '{channel}' not in allowed set {ALLOWED_SOURCE_CHANNELS}"
        )

    if not is_positive_int(receipt_monotonic_ns):
        errors.append("receipt_monotonic_ns missing or not a positive integer")

    if position is None or velocity is None or yaw_speed is None:
        errors.append("position, velocity, or yaw_speed missing")
    else:
        if not (isinstance(position, (list, tuple)) and len(position) == 3):
            errors.append("position must have exactly 3 components")
        elif not all_finite(position):
            errors.append("position contains NaN or Inf")

        if not (isinstance(velocity, (list, tuple)) and len(velocity) == 3):
            errors.append("velocity must have exactly 3 components")
        elif not all_finite(velocity):
            errors.append("velocity contains NaN or Inf")

        if not is_finite_number(yaw_speed):
            errors.append("yaw_speed is not a finite number")

    if errors:
        return _invalid(
            channel, receipt_monotonic_ns, receipt_wall_utc_ns,
            stamp_sec, stamp_nanosec, errors,
        )

    warnings = []
    stamp_is_zero = (stamp_sec == 0 and stamp_nanosec == 0)
    if stamp_is_zero:
        warnings.append(
            "message stamp is zero; ordering/timing relies on receipt_monotonic_ns, "
            "not sensor timestamp (see MESSAGE_STAMP_ZERO_USE_RECEIPT_TIME_REQUIRED)"
        )

    gyro_reliable = not (gyroscope is not None and is_all_zero(gyroscope))
    accel_reliable = not (accelerometer is not None and is_all_zero(accelerometer))
    if not gyro_reliable:
        warnings.append("imu gyroscope reads all-zero; not treated as reliable")
    if not accel_reliable:
        warnings.append("imu accelerometer reads all-zero; not treated as reliable")

    quaternion_tuple = tuple(quaternion) if quaternion else (0.0, 0.0, 0.0, 0.0)
    rpy_tuple = tuple(rpy) if rpy else (0.0, 0.0, 0.0)

    return OdometryCandidate(
        valid=True,
        source_channel=channel,
        receipt_monotonic_ns=receipt_monotonic_ns,
        receipt_wall_utc_ns=receipt_wall_utc_ns,
        timestamp_policy=TIMESTAMP_POLICY,
        message_stamp_sec=stamp_sec if isinstance(stamp_sec, int) else 0,
        message_stamp_nanosec=stamp_nanosec if isinstance(stamp_nanosec, int) else 0,
        frame_id=FRAME_ID,
        child_frame_id=None,
        position_xyz=tuple(position),
        velocity_xyz=tuple(velocity),
        yaw_speed=float(yaw_speed),
        orientation_quaternion_xyzw=quaternion_tuple,
        rpy=rpy_tuple,
        covariance_policy=COVARIANCE_POLICY,
        covariance_available=False,
        gyro_reliable=gyro_reliable,
        accel_reliable=accel_reliable,
        warnings=warnings,
        errors=[],
    )


def validate_candidate_sequence(candidates: "list[OdometryCandidate]") -> dict:
    """Pure aggregate check over a sequence of candidates from one run.

    Does not assume all candidates share a channel; buckets by
    source_channel and reports per-channel stats plus an overall
    invalid_count / warning_count.
    """
    by_channel: "dict[str, list[OdometryCandidate]]" = {}
    for c in candidates:
        by_channel.setdefault(c.source_channel, []).append(c)

    result = {
        "total_count": len(candidates),
        "invalid_count": sum(1 for c in candidates if not c.valid),
        "warning_count": sum(len(c.warnings) for c in candidates),
        "channels": {},
    }

    for channel, items in by_channel.items():
        valid_items = [c for c in items if c.valid]
        receipts = [c.receipt_monotonic_ns for c in valid_items]
        monotonic = all(receipts[i] <= receipts[i + 1] for i in range(len(receipts) - 1)) if receipts else None

        if valid_items:
            xs = [c.position_xyz[0] for c in valid_items]
            ys = [c.position_xyz[1] for c in valid_items]
            zs = [c.position_xyz[2] for c in valid_items]
            vmax = max(
                max(abs(c.velocity_xyz[0]), abs(c.velocity_xyz[1]), abs(c.velocity_xyz[2]))
                for c in valid_items
            )
            yaw_speeds = [c.yaw_speed for c in valid_items]
            position_min = (min(xs), min(ys), min(zs))
            position_max = (max(xs), max(ys), max(zs))
            yaw_speed_min = min(yaw_speeds)
            yaw_speed_max = max(yaw_speeds)
        else:
            position_min = position_max = None
            vmax = None
            yaw_speed_min = yaw_speed_max = None

        result["channels"][channel] = {
            "count": len(items),
            "valid_count": len(valid_items),
            "invalid_count": len(items) - len(valid_items),
            "receipt_monotonic": monotonic,
            "position_min": position_min,
            "position_max": position_max,
            "velocity_max_abs": vmax,
            "yaw_speed_min": yaw_speed_min,
            "yaw_speed_max": yaw_speed_max,
            "warning_count": sum(len(c.warnings) for c in items),
        }

    return result

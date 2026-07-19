"""ODOM-R1 offline adapter: SportModeState_ sample dict -> OdometryCandidate.

Pure functions only. No ROS, no DDS, no Unitree SDK, no network I/O, no file
I/O, no wall-clock reads inside the functions -- all timing comes from the
`receipt_monotonic_ns` / `receipt_wall_utc_ns` fields already present on the
input sample (captured at subscription time in MFR-R6, not read here).

This module does not publish anything and does not construct nav_msgs or TF
transforms. See MFR_R6_SPORTMODESTATE_ODOM_CONTRACT.md for the full contract
this implements.
"""
from collections.abc import Mapping

from .models import OdometryCandidate
from .validation import (
    ALLOWED_SOURCE_CHANNELS,
    COVARIANCE_POLICY,
    FRAME_ID,
    TIMESTAMP_POLICY,
    all_finite,
    is_finite_number,
    is_finite_vector,
    is_nonnegative_int,
    is_positive_int,
)


def _is_reliable_imu_vector(values) -> bool:
    """A 3-component IMU vector is reliable only when it exists, has exactly
    three finite numeric components, and is not entirely zero.

    A missing (None), malformed (wrong length / non-numeric / bool), or
    non-finite vector is NOT reliable -- absence is never silently promoted
    to reliable. R1D: `all_finite` itself now rejects `bool` components, so
    a vector of booleans can never be reported reliable.
    """
    if not isinstance(values, (list, tuple)):
        return False
    if len(values) != 3:
        return False
    if not all_finite(values):
        return False
    return not all(v == 0.0 for v in values)


def _vector_error(name, value, length):
    """Bounded error message if `value` is not a list/tuple of exactly
    `length` finite, non-bool numbers; else None.

    Never raises: `is_finite_vector` fails closed on its own (wrong type,
    wrong length, non-numeric/bool component, or a defective sequence that
    raises during `len()`/iteration all yield False, never an exception), so
    this wrapper only needs to turn that boolean into a field-scoped message.
    """
    if is_finite_vector(value, length):
        return None
    return f"{name} must be a list/tuple of exactly {length} finite, non-bool numbers"


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

    R1B: a non-mapping input (None, list, tuple, int, or any object without a
    usable `get`) also fails closed to an invalid candidate with an explicit
    error, never an exception.

    R1C: input must be a strict `collections.abc.Mapping` (an object that merely
    exposes a `get` method is not enough), and the field extraction itself is
    wrapped fail-closed so a defective Mapping subclass whose `get` raises still
    yields an invalid candidate instead of propagating the exception.

    R1D: `imu_quaternion` and `imu_rpy` are required fields, validated with the
    same fail-closed, exception-safe shape/finiteness check as position/velocity
    (list/tuple of the exact length, finite non-bool components) before any
    `tuple()` conversion is attempted; a valid candidate's quaternion must have
    non-zero norm. `stamp_sec`, `stamp_nanosec`, and `receipt_wall_utc_ns` are
    validated as non-negative, non-bool integers (`receipt_wall_utc_ns` may be
    `None`) instead of being silently defaulted to 0 or passed through
    unchecked. The shared numeric helpers reject `bool` as a valid number
    (`bool` is a subclass of `int` and would otherwise pass as `0`/`1`), so a
    bool in position, velocity, yaw_speed, or an IMU vector fails closed here
    rather than only being caught later by the readiness gate. Every
    validation step in this function is exception-safe, so an ordinary
    exception raised by a malformed value (e.g. a defective sequence that
    raises during iteration) yields an invalid candidate, never a propagated
    exception.
    """
    # Fix C (R1C): accept only a strict Mapping. An object with a callable `get`
    # that is not a Mapping (None / list / int / duck-typed object) is invalid.
    if not isinstance(sample, Mapping):
        return _invalid(
            None, None, None, None, None,
            [f"sample is not a Mapping (got {type(sample).__name__}); "
             f"a SportModeState_ sample dict is required"],
        )

    # Fix C (R1C): protect the extraction -- a defective Mapping subclass whose
    # `get` raises must fail closed, never propagate. Only ordinary exceptions
    # are caught (never BaseException / KeyboardInterrupt / SystemExit).
    try:
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
    except Exception as exc:
        return _invalid(
            None, None, None, None, None,
            [f"sample.get() raised {type(exc).__name__} during field "
             f"extraction; treated as invalid input"],
        )

    try:
        errors = []

        if channel not in ALLOWED_SOURCE_CHANNELS:
            errors.append(
                f"source_channel '{channel}' not in allowed set {ALLOWED_SOURCE_CHANNELS}"
            )

        if not is_positive_int(receipt_monotonic_ns):
            errors.append("receipt_monotonic_ns missing or not a positive integer")

        if not is_nonnegative_int(stamp_sec):
            errors.append("stamp_sec missing, not an integer, or negative")

        if not is_nonnegative_int(stamp_nanosec) or stamp_nanosec > 999_999_999:
            errors.append(
                "stamp_nanosec missing, not an integer, negative, or out of "
                "range [0, 999999999]"
            )

        if receipt_wall_utc_ns is not None and not is_nonnegative_int(receipt_wall_utc_ns):
            errors.append("receipt_wall_utc_ns must be a non-negative integer or None")

        if position is None or velocity is None or yaw_speed is None:
            errors.append("position, velocity, or yaw_speed missing")
        else:
            pos_error = _vector_error("position", position, 3)
            if pos_error:
                errors.append(pos_error)
            vel_error = _vector_error("velocity", velocity, 3)
            if vel_error:
                errors.append(vel_error)
            if not is_finite_number(yaw_speed):
                errors.append("yaw_speed is not a finite number")

        # R1D: imu_quaternion / imu_rpy are required and validated with the
        # same fail-closed shape/finiteness check BEFORE any tuple()
        # conversion -- a bool, a wrong-length sequence, or a non-iterable
        # value must never reach tuple() and must never yield valid=True.
        quat_error = _vector_error("imu_quaternion", quaternion, 4)
        if quat_error:
            errors.append(quat_error)
        elif sum(component * component for component in quaternion) <= 0.0:
            errors.append("imu_quaternion has zero norm")

        rpy_error = _vector_error("imu_rpy", rpy, 3)
        if rpy_error:
            errors.append(rpy_error)

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

        # An IMU vector is reliable only when it exists, has exactly three finite
        # components and is not entirely zero. A missing / malformed / non-finite
        # vector is NOT reliable (absence is never promoted to reliable). This does
        # NOT invalidate the whole candidate: position/velocity/yaw remain usable.
        gyro_reliable = _is_reliable_imu_vector(gyroscope)
        accel_reliable = _is_reliable_imu_vector(accelerometer)
        if not gyro_reliable:
            if gyroscope is None:
                warnings.append("imu gyroscope missing; not treated as reliable")
            elif not (isinstance(gyroscope, (list, tuple)) and len(gyroscope) == 3 and all_finite(gyroscope)):
                warnings.append("imu gyroscope malformed or non-finite; not treated as reliable")
            else:
                warnings.append("imu gyroscope reads all-zero; not treated as reliable")
        if not accel_reliable:
            if accelerometer is None:
                warnings.append("imu accelerometer missing; not treated as reliable")
            elif not (isinstance(accelerometer, (list, tuple)) and len(accelerometer) == 3 and all_finite(accelerometer)):
                warnings.append("imu accelerometer malformed or non-finite; not treated as reliable")
            else:
                warnings.append("imu accelerometer reads all-zero; not treated as reliable")

        return OdometryCandidate(
            valid=True,
            source_channel=channel,
            receipt_monotonic_ns=receipt_monotonic_ns,
            receipt_wall_utc_ns=receipt_wall_utc_ns,
            timestamp_policy=TIMESTAMP_POLICY,
            message_stamp_sec=stamp_sec,
            message_stamp_nanosec=stamp_nanosec,
            frame_id=FRAME_ID,
            child_frame_id=None,
            position_xyz=tuple(position),
            velocity_xyz=tuple(velocity),
            yaw_speed=float(yaw_speed),
            orientation_quaternion_xyzw=tuple(quaternion),
            rpy=tuple(rpy),
            covariance_policy=COVARIANCE_POLICY,
            covariance_available=False,
            gyro_reliable=gyro_reliable,
            accel_reliable=accel_reliable,
            warnings=warnings,
            errors=[],
        )
    except Exception as exc:
        return _invalid(
            channel, receipt_monotonic_ns, receipt_wall_utc_ns, stamp_sec, stamp_nanosec,
            [f"{type(exc).__name__} raised during candidate validation; "
             f"treated as invalid"],
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

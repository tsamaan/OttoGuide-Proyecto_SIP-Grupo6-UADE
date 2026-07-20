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
    is_nonnegative_int,
    is_positive_int,
    normalize_finite_vector,
)


_IMU_MISSING = "MISSING"
_IMU_MALFORMED = "MALFORMED"
_IMU_NON_FINITE = "NON_FINITE"
_IMU_ALL_ZERO = "ALL_ZERO"
_IMU_RELIABLE = "RELIABLE"

_IMU_WARNING_TEMPLATES = {
    _IMU_MISSING: "imu {name} missing; not treated as reliable",
    _IMU_MALFORMED: (
        "imu {name} malformed (wrong type, shape, or non-numeric/bool "
        "component); not treated as reliable"
    ),
    _IMU_NON_FINITE: "imu {name} malformed (non-finite component); not treated as reliable",
    _IMU_ALL_ZERO: "imu {name} reads all-zero; not treated as reliable",
}


def _classify_imu_vector(values):
    """Classify an auxiliary IMU vector (gyroscope/accelerometer) as exactly
    one of MISSING / MALFORMED / NON_FINITE / ALL_ZERO / RELIABLE. Only
    RELIABLE means "safe to trust".

    This is the single place `len()`/iteration is attempted on `values` --
    no unsafe `len(values)` / `all_finite(values)` / `tuple(values)` on this
    same value is repeated anywhere else. The one narrow `try` below is what
    makes this fail-closed: an ordinary exception from a defective sequence
    (a broken `__len__` or `__iter__`) classifies as MALFORMED instead of
    propagating, so a pathological auxiliary vector degrades only this
    classification -- it can never reach a wider boundary and invalidate the
    whole candidate.
    """
    if values is None:
        return _IMU_MISSING
    try:
        if not isinstance(values, (list, tuple)):
            return _IMU_MALFORMED
        if len(values) != 3:
            return _IMU_MALFORMED
        components = list(values)
    except Exception:
        return _IMU_MALFORMED

    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in components):
        return _IMU_MALFORMED
    if not all_finite(components):
        return _IMU_NON_FINITE
    if all(v == 0.0 for v in components):
        return _IMU_ALL_ZERO
    return _IMU_RELIABLE


def _imu_reliability_and_warning(name, values):
    """Return `(reliable, warning)` for one auxiliary IMU vector from a
    single fail-closed classification. `reliable` is `True` only for
    `_IMU_RELIABLE`; `warning` is `None` in that case and a bounded,
    field-scoped message otherwise. `name` (e.g. "gyroscope") only feeds the
    warning text, never a `repr()` of `values` itself.
    """
    classification = _classify_imu_vector(values)
    if classification == _IMU_RELIABLE:
        return True, None
    return False, _IMU_WARNING_TEMPLATES[classification].format(name=name)


def _vector_error(name, normalized, length):
    """Bounded error message if `normalized` (the result of
    `normalize_finite_vector(value, length)`) is `None`; else `None`.

    R1D-R3: takes the already-normalized result, never the raw value --
    `normalize_finite_vector` is the only place that ever touches the raw
    value's own `len()`/iteration (see its docstring), so nothing here
    re-touches it.
    """
    if normalized is not None:
        return None
    return f"{name} must be a list/tuple of exactly {length} finite, non-bool numbers"


_INVALID_SOURCE_CHANNEL = "<invalid>"


def _invalid(source_channel, receipt_monotonic_ns, receipt_wall_utc_ns,
             message_stamp_sec, message_stamp_nanosec, errors, warnings=None):
    """Build an invalid candidate. Every field is normalized to a canonical,
    bounded, hashable, JSON-serializable value, no matter how malformed the
    input was.

    R1D-R1: `receipt_monotonic_ns` / `message_stamp_sec` /
    `message_stamp_nanosec` / `receipt_wall_utc_ns` are normalized through
    `is_nonnegative_int` (which excludes `bool`, unlike a bare
    `isinstance(x, int)`), so none of them can store a raw `bool` or an
    arbitrary object.

    R1D-R2: `source_channel` gets the same treatment. Only an allowed
    channel of exact type `str` is preserved; any other value -- wrong
    type, a hostile `str` subclass, an empty/whitespace/unknown string, or
    an object whose `__eq__`/`__str__` raises -- normalizes to the fixed
    sentinel `_INVALID_SOURCE_CHANNEL` instead of the raw value. This closes
    the gap R1D-R1's own audit found: `_invalid()` previously left
    `source_channel` completely untouched, so an invalid candidate could
    still carry a non-serializable, unhashable, or exception-raising object
    there even though every numeric field was already canonical.
    """
    normalized_source_channel = (
        source_channel
        if type(source_channel) is str and source_channel in ALLOWED_SOURCE_CHANNELS
        else _INVALID_SOURCE_CHANNEL
    )
    normalized_wall_utc_ns = (
        receipt_wall_utc_ns
        if receipt_wall_utc_ns is None or is_nonnegative_int(receipt_wall_utc_ns)
        else None
    )
    normalized_stamp_nanosec = (
        message_stamp_nanosec
        if is_nonnegative_int(message_stamp_nanosec) and message_stamp_nanosec <= 999_999_999
        else 0
    )
    return OdometryCandidate(
        valid=False,
        source_channel=normalized_source_channel,
        receipt_monotonic_ns=receipt_monotonic_ns if is_nonnegative_int(receipt_monotonic_ns) else 0,
        receipt_wall_utc_ns=normalized_wall_utc_ns,
        timestamp_policy=TIMESTAMP_POLICY,
        message_stamp_sec=message_stamp_sec if is_nonnegative_int(message_stamp_sec) else 0,
        message_stamp_nanosec=normalized_stamp_nanosec,
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
    rather than only being caught later by the readiness gate.

    R1D-R1: an independent pre-push audit of R1D found two residual defects,
    closed here. First, `_invalid()` no longer stores a raw `bool` or an
    arbitrary object in a timestamp field of an invalid candidate (see its
    docstring). Second, a pathological `imu_gyroscope`/`imu_accelerometer`
    (e.g. a value whose `__len__` or `__iter__` raises) is now classified by
    a single, narrow, fail-closed helper (`_classify_imu_vector` /
    `_imu_reliability_and_warning`) that degrades only that sensor's own
    reliability flag and warning -- it can no longer invalidate the whole
    candidate. The function-wide `except Exception` this checkpoint
    previously relied on as a catch-all safety net is removed: every
    payload-dependent operation (vector shape/finiteness via
    `_vector_error`/`is_finite_vector`, IMU classification via
    `_classify_imu_vector`) is protected at its own narrow, purpose-built
    helper instead, so a genuine internal programming bug elsewhere in this
    function is no longer silently converted into an "invalid candidate"
    result.

    R1D-R2: the R1D-R1 audit's own canary test (a hostile `channel`) found
    that `source_channel` was the one field left out of the "every invalid
    candidate is canonical and JSON-serializable" guarantee. `channel not in
    ALLOWED_SOURCE_CHANNELS` propagated whatever ordinary exception a hostile
    object's `__eq__` raised, and the old error message's f-string
    interpolation of `channel` did the same for a hostile `__str__`; neither
    is evaluated anymore. The check is now `type(channel) is str and channel
    in ALLOWED_SOURCE_CHANNELS` (type-gated before any comparison, rejecting
    a hostile `str` subclass too), the error message is a fixed constant, and
    `_invalid()` normalizes any disallowed/wrong-type channel to the fixed
    sentinel `_INVALID_SOURCE_CHANNEL` -- never the raw value. See
    `validate_candidate_sequence` for the matching defense against a
    manually-constructed candidate whose `source_channel` is unhashable.

    R1D-R3: a GitHub-side audit of the published R1D-R2 commit found two
    further residual defects. First, `position`/`velocity`/`imu_quaternion`/
    `imu_rpy` were each checked for shape/finiteness (one iteration) and then
    iterated AGAIN via `tuple(...)` when building the candidate (a third time
    for the quaternion, which was also re-iterated for its norm) -- a
    sequence whose `__iter__` starts raising only on its second call broke on
    that later pass. `normalize_finite_vector` (see `validation.py`) is now
    the single place any of these four raw values is ever touched: it
    validates and returns a canonical tuple in one pass, and every
    downstream use here (quaternion norm, candidate construction) uses only
    that tuple, never the raw value again. Second, the shared numeric
    helpers (`is_finite_number`, `is_positive_int`, `is_nonnegative_int`)
    used `isinstance()`, so an `int`/`float` SUBCLASS with a hostile
    comparison or conversion dunder (e.g. `__gt__`/`__float__` that raises)
    passed the type gate and then raised on the comparison itself; they now
    gate on `type(x) is int`/`float` exactly, rejecting any subclass (and
    `bool`, whose type is never `int`) before any dunder of the untrusted
    value is ever invoked.
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

    errors = []

    # R1D-R2: check the exact type FIRST, short-circuiting before any `in`/
    # `==` membership test. A hostile object (or a str subclass) whose
    # __eq__ raises would otherwise crash `channel in ALLOWED_SOURCE_CHANNELS`;
    # `type(channel) is str` rejects it (and any str subclass) without ever
    # touching __eq__. The message is a fixed constant -- never `str(channel)`
    # / `repr(channel)` / an f-string of `channel` -- so a hostile __str__
    # can't raise here either.
    if not (type(channel) is str and channel in ALLOWED_SOURCE_CHANNELS):
        errors.append(
            "source_channel missing, not a plain string, or outside allowed set"
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

    # R1D-R3: normalize each raw vector EXACTLY ONCE via
    # `normalize_finite_vector`; every check and the final candidate below
    # use only the resulting canonical tuple, never the raw value again.
    position_normalized = None
    velocity_normalized = None
    if position is None or velocity is None or yaw_speed is None:
        errors.append("position, velocity, or yaw_speed missing")
    else:
        position_normalized = normalize_finite_vector(position, 3)
        pos_error = _vector_error("position", position_normalized, 3)
        if pos_error:
            errors.append(pos_error)
        velocity_normalized = normalize_finite_vector(velocity, 3)
        vel_error = _vector_error("velocity", velocity_normalized, 3)
        if vel_error:
            errors.append(vel_error)
        if not is_finite_number(yaw_speed):
            errors.append("yaw_speed is not a finite number")

    # R1D: imu_quaternion / imu_rpy are required and validated with the
    # same fail-closed shape/finiteness check BEFORE any tuple()
    # conversion -- a bool, a wrong-length sequence, or a non-iterable
    # value must never reach tuple() and must never yield valid=True.
    quaternion_normalized = normalize_finite_vector(quaternion, 4)
    quat_error = _vector_error("imu_quaternion", quaternion_normalized, 4)
    if quat_error:
        errors.append(quat_error)
    elif sum(component * component for component in quaternion_normalized) <= 0.0:
        errors.append("imu_quaternion has zero norm")

    rpy_normalized = normalize_finite_vector(rpy, 3)
    rpy_error = _vector_error("imu_rpy", rpy_normalized, 3)
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

    # R1D-R1: a pathological gyro/accelerometer (missing, malformed, non-finite,
    # all-zero, or a defective sequence that raises during len()/iteration) is
    # classified by one fail-closed helper and only ever degrades that sensor's
    # own reliability flag and warning -- it can never invalidate the whole
    # candidate. position/velocity/yaw/orientation remain the only fields that
    # gate validity.
    gyro_reliable, gyro_warning = _imu_reliability_and_warning("gyroscope", gyroscope)
    accel_reliable, accel_warning = _imu_reliability_and_warning("accelerometer", accelerometer)
    if gyro_warning:
        warnings.append(gyro_warning)
    if accel_warning:
        warnings.append(accel_warning)

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
        # R1D-R3: reuse the tuples `normalize_finite_vector` already built --
        # never re-iterate the raw position/velocity/quaternion/rpy values.
        position_xyz=position_normalized,
        velocity_xyz=velocity_normalized,
        yaw_speed=float(yaw_speed),
        orientation_quaternion_xyzw=quaternion_normalized,
        rpy=rpy_normalized,
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

    R1D-R2: `to_odometry_candidate` always normalizes `source_channel` to a
    `str`, but this function does not assume every candidate came from the
    adapter -- a manually-constructed `OdometryCandidate` could carry an
    unhashable `source_channel` (a list or dict), which would otherwise
    crash `dict.setdefault` with `TypeError`. `type(source_channel) is str`
    is checked before ever using it as a key; anything else buckets under
    the same fixed sentinel `_INVALID_SOURCE_CHANNEL` the adapter itself
    uses, so `hash()` is never attempted on an arbitrary value.
    """
    by_channel: "dict[str, list[OdometryCandidate]]" = {}
    for c in candidates:
        channel_key = c.source_channel if type(c.source_channel) is str else _INVALID_SOURCE_CHANNEL
        by_channel.setdefault(channel_key, []).append(c)

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

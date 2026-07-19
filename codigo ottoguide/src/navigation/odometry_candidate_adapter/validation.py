"""Pure validation helpers for ODOM-R1.

No I/O, no ROS, no DDS, no network. Only math on plain Python values.
"""
import math

TIMESTAMP_POLICY = "MESSAGE_STAMP_ZERO_USE_RECEIPT_TIME_REQUIRED"
FRAME_ID = "unitree_odom_candidate"
COVARIANCE_POLICY = "NO_COVARIANCE_IN_SOURCE_DOCUMENT_GAP"

ALLOWED_SOURCE_CHANNELS = ("rt/odommodestate", "rt/lf/odommodestate")


def is_finite_number(x) -> bool:
    """True iff `x` is a real, finite `int`/`float`.

    R1D: `bool` is a subclass of `int` in Python, so `True`/`False` would
    otherwise pass `math.isfinite()` as `1`/`0`. A boolean is never a valid
    numeric value here.
    """
    if isinstance(x, bool):
        return False
    if not isinstance(x, (int, float)):
        return False
    try:
        return math.isfinite(x)
    except TypeError:
        return False


def all_finite(values) -> bool:
    """True iff every element of `values` is a finite, non-bool number.

    Fail-closed against a defective iterable: an ordinary exception raised
    while iterating `values` (e.g. a list subclass with a broken __iter__)
    yields False rather than propagating.
    """
    try:
        return all(is_finite_number(v) for v in values)
    except Exception:
        return False


def is_finite_vector(values, length) -> bool:
    """True iff `values` is a list/tuple of exactly `length` finite,
    non-bool int/float components.

    Fail-closed: a wrong type, wrong length, non-numeric/bool component, or
    a defective sequence that raises during `len()`/iteration all yield
    False, never an exception.
    """
    try:
        if not isinstance(values, (list, tuple)):
            return False
        if len(values) != length:
            return False
    except Exception:
        return False
    return all_finite(values)


def is_all_zero(values) -> bool:
    return all(v == 0.0 for v in values)


def is_positive_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x > 0


def is_nonnegative_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x >= 0

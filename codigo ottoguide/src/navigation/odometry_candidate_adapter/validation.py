"""Pure validation helpers for ODOM-R1.

No I/O, no ROS, no DDS, no network. Only math on plain Python values.
"""
import math

TIMESTAMP_POLICY = "MESSAGE_STAMP_ZERO_USE_RECEIPT_TIME_REQUIRED"
FRAME_ID = "unitree_odom_candidate"
COVARIANCE_POLICY = "NO_COVARIANCE_IN_SOURCE_DOCUMENT_GAP"

ALLOWED_SOURCE_CHANNELS = ("rt/odommodestate", "rt/lf/odommodestate")


def is_finite_number(x) -> bool:
    try:
        return math.isfinite(x)
    except TypeError:
        return False


def all_finite(values) -> bool:
    return all(is_finite_number(v) for v in values)


def is_all_zero(values) -> bool:
    return all(v == 0.0 for v in values)


def is_positive_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x > 0

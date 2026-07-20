"""Pure validation helpers for ODOM-R1.

No I/O, no ROS, no DDS, no network. Only math on plain Python values.
"""
import math

TIMESTAMP_POLICY = "MESSAGE_STAMP_ZERO_USE_RECEIPT_TIME_REQUIRED"
FRAME_ID = "unitree_odom_candidate"
COVARIANCE_POLICY = "NO_COVARIANCE_IN_SOURCE_DOCUMENT_GAP"

ALLOWED_SOURCE_CHANNELS = ("rt/odommodestate", "rt/lf/odommodestate")


def is_finite_number(x) -> bool:
    """True iff `x` is a real, finite, exact `int`/`float`.

    R1D-R3: gated on `type(x) is int or type(x) is float` -- an exact-type
    check, not `isinstance()`. This rejects `bool` (its type is `bool`,
    never `int`) and any int/float SUBCLASS in the same step, before ever
    invoking a subclass's own comparison/conversion dunders: a hostile
    numeric subclass whose `__gt__`/`__float__` raises must never reach
    that call here.
    """
    if type(x) is not int and type(x) is not float:
        return False
    try:
        return math.isfinite(x)
    except TypeError:
        return False


def all_finite(values) -> bool:
    """True iff every element of `values` is a finite, exact int/float.

    Fail-closed against a defective iterable: an ordinary exception raised
    while iterating `values` (e.g. a list subclass with a broken __iter__)
    yields False rather than propagating.
    """
    try:
        return all(is_finite_number(v) for v in values)
    except Exception:
        return False


def normalize_finite_vector(value, length):
    """Validate AND canonicalize `value` in a single pass; `None` if
    malformed.

    R1D-R3: closes `UNTRUSTED_VECTOR_REITERATION_CAN_PROPAGATE`. The
    previous shape check and its caller each iterated the same raw,
    untrusted `value` separately (once to check finiteness, again via
    `tuple(value)` to build the candidate) -- a sequence whose `__iter__`
    raises starting on its SECOND call broke on that second pass. This is
    now the only place `value`'s own `len()`/iteration is ever touched:
    `type(value) is list`/`tuple` is checked FIRST, before any method on it
    is invoked, so a list/tuple SUBCLASS (however hostile its own
    `__len__`/`__iter__`) is rejected without ever running its overridden
    methods. Every caller downstream must use only the canonical tuple
    this returns -- never the raw `value` again.
    """
    try:
        if type(value) is not list and type(value) is not tuple:
            return None
        if len(value) != length:
            return None
        components = tuple(value)
    except Exception:
        return None

    if len(components) != length:
        return None

    if not all(
        (type(v) is int or type(v) is float) and math.isfinite(v)
        for v in components
    ):
        return None

    return components


def is_all_zero(values) -> bool:
    return all(v == 0.0 for v in values)


def is_positive_int(x) -> bool:
    """True iff `x` is an exact, plain `int` and positive.

    R1D-R3: `type(x) is int` gates before any comparison is attempted, so
    an `int` SUBCLASS with a hostile `__gt__` (and `bool`, whose type is
    never `int`) never reaches that comparison at all.
    """
    return type(x) is int and x > 0


def is_nonnegative_int(x) -> bool:
    """True iff `x` is an exact, plain `int` and non-negative. Same
    exact-type gate as `is_positive_int`, before any comparison."""
    return type(x) is int and x >= 0

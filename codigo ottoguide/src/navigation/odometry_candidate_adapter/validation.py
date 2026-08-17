"""Pure validation helpers for ODOM-R1.

No I/O, no ROS, no DDS, no network. Only math on plain Python values.
"""
import math

TIMESTAMP_POLICY = "MESSAGE_STAMP_ZERO_USE_RECEIPT_TIME_REQUIRED"
FRAME_ID = "unitree_odom_candidate"
COVARIANCE_POLICY = "NO_COVARIANCE_IN_SOURCE_DOCUMENT_GAP"

ALLOWED_SOURCE_CHANNELS = ("rt/odommodestate", "rt/lf/odommodestate")

# R1D-R4: MAX_SIGNED_64 / MAX_MESSAGE_NANOSEC are internal storage and
# JSON-serialization limits for THIS offline model only -- they bound what
# an OdometryCandidate integer field may hold so every candidate (valid or
# invalid) stays representable and serializable. They do NOT resolve ROS
# Time mapping, message-to-ROS-clock conversion, or timestamp authority;
# RECEIPT_TIME_TO_ROS_TIME_UNRESOLVED and the other timestamp-related
# readiness blockers remain open regardless of these bounds.
MAX_SIGNED_64 = 9_223_372_036_854_775_807
MAX_MESSAGE_NANOSEC = 999_999_999


def normalize_finite_number(value):
    """Validate AND canonicalize `value` to a finite `float`, or `None` if
    malformed.

    R1D-R4: closes `HUGE_INT_MATH_ISFINITE_OVERFLOW`. `type(value) is int`
    or `type(value) is float` is checked FIRST -- rejecting `bool` (its type
    is `bool`, never `int`) and any int/float SUBCLASS, before any dunder of
    an untrusted value is invoked. `float(value)` is then attempted inside a
    `try` that also catches `OverflowError`: an arbitrary-precision `int`
    whose magnitude exceeds what a C double can represent (e.g. `10**10000`)
    raises `OverflowError` from `float()` (and would from `math.isfinite()`
    directly, which internally converts through the same path) -- that must
    yield `None` here, never propagate.
    """
    if type(value) is not int and type(value) is not float:
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(normalized):
        return None
    return normalized


def is_finite_number(x) -> bool:
    """True iff `x` is a real, finite, exact `int`/`float` that safely
    normalizes to a finite `float`.

    R1D-R4: reuses `normalize_finite_number`'s semantics rather than
    duplicating them, so this and every vector/scalar check share one
    single, exception-safe definition of "finite number".
    """
    return normalize_finite_number(x) is not None


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
    """Validate AND canonicalize `value` to a tuple of `length` finite,
    canonical `float`s in a single pass; `None` if malformed.

    R1D-R3: closes `UNTRUSTED_VECTOR_REITERATION_CAN_PROPAGATE`. This is the
    only place `value`'s own `len()`/iteration is ever touched:
    `type(value) is list`/`tuple` is checked FIRST, before any method on it
    is invoked, so a list/tuple SUBCLASS (however hostile its own
    `__len__`/`__iter__`) is rejected without ever running its overridden
    methods; the raw input is then copied ONCE into a plain tuple. Every
    caller downstream must use only the canonical tuple this returns --
    never the raw `value` again.

    R1D-R4: closes `HUGE_INT_MATH_ISFINITE_OVERFLOW` for vector components
    too -- each component is normalized through `normalize_finite_number`
    (never a bare `math.isfinite(v)`), so a component whose magnitude
    overflows a C double yields `None` (the whole vector rejected) instead
    of propagating `OverflowError`. The returned tuple holds canonical
    `float`s, never the raw component values.
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

    normalized_components = []
    for v in components:
        normalized_v = normalize_finite_number(v)
        if normalized_v is None:
            return None
        normalized_components.append(normalized_v)

    return tuple(normalized_components)


def is_all_zero(values) -> bool:
    return all(v == 0.0 for v in values)


def is_bounded_positive_int(x) -> bool:
    """True iff `x` is an exact, plain `int`, positive, and within
    `[1, MAX_SIGNED_64]`.

    R1D-R3: `type(x) is int` gates before any comparison is attempted, so
    an `int` SUBCLASS with a hostile `__gt__` (and `bool`, whose type is
    never `int`) never reaches that comparison at all.

    R1D-R4: adds the `MAX_SIGNED_64` upper bound -- closes
    `UNBOUNDED_TIMESTAMP_INT_BREAKS_JSON_SERIALIZATION`. This is an internal
    storage/serialization bound only (see the module-level note); it is not
    a resolution of ROS Time mapping or timestamp authority.
    """
    return type(x) is int and 1 <= x <= MAX_SIGNED_64


def is_bounded_nonnegative_int(x) -> bool:
    """True iff `x` is an exact, plain `int`, non-negative, and within
    `[0, MAX_SIGNED_64]`. Same exact-type gate and rationale as
    `is_bounded_positive_int`."""
    return type(x) is int and 0 <= x <= MAX_SIGNED_64

"""Pure, fail-closed validation helpers for ODOM/TF R2-P0 evidence ingestion.

No I/O, no ROS, no DDS, no network, no live SDK. Only checks on plain Python
values already read into memory by the caller. Every helper here rejects
malformed input by returning False / None / raising EvidenceValidationError
-- it never silently coerces (null -> 0, missing -> False verified,
empty string -> resolved value, nominal -> measured, operator annotation ->
metrological ground truth).
"""
import math
import re

from src.navigation.odometry_candidate_adapter.validation import (
    normalize_finite_number,
    normalize_finite_vector,
    is_finite_number,
    all_finite,
)

__all__ = [
    "EvidenceValidationError",
    "STATUS_VALUES",
    "GROUND_TRUTH_VALUES",
    "SESSION_TYPE_VALUES",
    "normalize_finite_number",
    "normalize_finite_vector",
    "is_finite_number",
    "all_finite",
    "is_sha256_hex",
    "is_relative_portable_path",
    "is_non_empty_str",
    "validate_status",
    "validate_ground_truth",
    "validate_session_type",
    "validate_no_unknown_fields",
    "validate_str_tuple",
    "validate_sha256_tuple",
    "is_bounded_int",
    "is_plain_bool",
]


class EvidenceValidationError(ValueError):
    """Raised for any malformed R2-P0 evidence input. Never caught silently
    by ingest logic to coerce a default -- either the record is rejected
    (fail-closed) or, for known-invalid physical segments, explicitly
    excluded and documented as such."""


# Status vocabulary shared by every evidence record (section 14.2).
STATUS_VALUES = frozenset({
    "VERIFIED",
    "SUPPORTED_INFERENCE",
    "PARTIAL",
    "UNRESOLVED",
    "NOT_AVAILABLE",
    "NOT_EXECUTED",
    "INVALID",
    "SUPERSEDED",
})

# Ground-truth constraint vocabulary (section 13.4 / 14).
GROUND_TRUTH_VALUES = frozenset({
    "MEASURED",
    "BEST_EFFORT_MEASURED",
    "NOMINAL",
    "OPERATOR_ANNOTATED",
    "NOT_AVAILABLE",
    "INVALID",
})

SESSION_TYPE_VALUES = frozenset({
    "R3C_MANUAL_PHYSICAL_ROUTE",
    "R4_FINAL_PHYSICAL_HARVEST",
    "R4B_FINAL_BEST_EFFORT_GROUND_TRUTH",
})

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_SIGNED_64 = 9_223_372_036_854_775_807


def is_plain_bool(x) -> bool:
    """True iff x is exactly a bool (used to REJECT bool where a number or
    int is expected -- bool is a subclass of int in Python and must never be
    silently accepted as one)."""
    return type(x) is bool


def is_bounded_int(x, *, minimum=None, maximum=None) -> bool:
    """True iff x is an exact, plain int (never bool) within [minimum, maximum]
    when those bounds are given."""
    if type(x) is not int:
        return False
    if minimum is not None and x < minimum:
        return False
    if maximum is not None and x > maximum:
        return False
    return True


def is_non_empty_str(x) -> bool:
    return type(x) is str and len(x) > 0


def is_sha256_hex(x) -> bool:
    """True iff x is a plain str of exactly 64 lowercase hex characters."""
    return type(x) is str and bool(_SHA256_RE.match(x))


def is_relative_portable_path(x) -> bool:
    """True iff x is a plain str, relative (no drive letter, no leading
    slash/backslash), and contains no '..' path-traversal segment. Rejects
    absolute paths and anything that would escape a staging root."""
    if type(x) is not str or len(x) == 0:
        return False
    normalized = x.replace("\\", "/")
    if normalized.startswith("/"):
        return False
    if re.match(r"^[A-Za-z]:", normalized):
        return False
    parts = normalized.split("/")
    if any(part == ".." for part in parts):
        return False
    if any(part == "" for part in parts[1:-1]):
        return False
    return True


def validate_status(value) -> str:
    if type(value) is not str or value not in STATUS_VALUES:
        raise EvidenceValidationError(f"invalid status: {value!r}")
    return value


def validate_ground_truth(value) -> str:
    if type(value) is not str or value not in GROUND_TRUTH_VALUES:
        raise EvidenceValidationError(f"invalid ground_truth constraint: {value!r}")
    return value


def validate_session_type(value) -> str:
    if type(value) is not str or value not in SESSION_TYPE_VALUES:
        raise EvidenceValidationError(f"invalid session_type: {value!r}")
    return value


def validate_no_unknown_fields(data: dict, allowed_fields) -> None:
    if type(data) is not dict:
        raise EvidenceValidationError("expected a plain dict")
    unknown = set(data.keys()) - set(allowed_fields)
    if unknown:
        raise EvidenceValidationError(f"unknown field(s): {sorted(unknown)}")


def validate_str_tuple(value, *, allow_empty_tuple=True) -> tuple:
    if type(value) is not tuple and type(value) is not list:
        raise EvidenceValidationError("expected a list/tuple of str")
    items = tuple(value)
    if not allow_empty_tuple and len(items) == 0:
        raise EvidenceValidationError("expected a non-empty list/tuple of str")
    for item in items:
        if not is_non_empty_str(item):
            raise EvidenceValidationError(f"non-string or empty element: {item!r}")
    return items


def validate_sha256_tuple(value) -> tuple:
    if type(value) is not tuple and type(value) is not list:
        raise EvidenceValidationError("expected a list/tuple of sha256 hex strings")
    items = tuple(value)
    for item in items:
        if not is_sha256_hex(item):
            raise EvidenceValidationError(f"not a sha256 hex digest: {item!r}")
    return items


def reject_nan_or_infinite(value, *, field_name="value") -> float:
    """Validate AND canonicalize a scalar via normalize_finite_number; raises
    EvidenceValidationError (fail-closed) instead of returning None, for use
    at construction boundaries where malformed input must abort the build."""
    normalized = normalize_finite_number(value)
    if normalized is None or not math.isfinite(normalized):
        raise EvidenceValidationError(f"{field_name} is not a finite number: {value!r}")
    return normalized

"""Pure, deterministic statistics helpers for ODOM/TF R2-P1.

No I/O. Reuses P0A's ``compute_scalar_stats``/``compute_vector_stats``
(unmodified) for simple mean/variance and adds the percentile/robust-jitter/
nearest-neighbor-pairing primitives P0A never needed.
"""
import math

from src.navigation.odometry_evidence_r2.statistics import (  # noqa: F401 (re-exported)
    compute_scalar_stats,
    compute_vector_stats,
)
from src.navigation.odometry_evidence_r2.validation import EvidenceValidationError, is_finite_number

GAP_THRESHOLD_METHOD = "MEDIAN_PLUS_6_MAD_OF_INTERVALS_FLOOR_10X_MEDIAN"


def percentile(values, fraction: float) -> float:
    """Deterministic linear-interpolation percentile (0<=fraction<=1) over a
    non-empty sequence of finite numbers. Never uses numpy (no dependency)."""
    if not (0.0 <= fraction <= 1.0):
        raise EvidenceValidationError(f"fraction must be in [0,1], got {fraction!r}")
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        raise EvidenceValidationError("cannot compute a percentile over 0 samples")
    if n == 1:
        return float(ordered[0])
    rank = fraction * (n - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return float(ordered[lower])
    weight = rank - lower
    return float(ordered[lower]) * (1 - weight) + float(ordered[upper]) * weight


def median(values) -> float:
    return percentile(values, 0.5)


def mad(values) -> float:
    """Median absolute deviation (robust dispersion), not scaled to a normal
    sigma-equivalent -- reported and documented as a raw MAD."""
    m = median(values)
    deviations = [abs(v - m) for v in values]
    return median(deviations)


def robust_gap_threshold(intervals) -> "tuple[float, str]":
    """Deterministic, data-derived gap threshold: median + 6*MAD of the
    session's own observed sample intervals, floored at 10x the median
    interval so a near-zero-jitter (near-perfectly-periodic) stream still
    gets a sane, non-degenerate threshold. Documented method + parameters
    per section 22 ('no debe ser una constante oculta arbitraria')."""
    if not intervals:
        raise EvidenceValidationError("cannot derive a gap threshold from 0 intervals")
    med = median(intervals)
    deviation = mad(intervals)
    threshold = med + 6.0 * deviation
    floor = med * 10.0
    return max(threshold, floor), GAP_THRESHOLD_METHOD


def modal_positive_step(sorted_sequences) -> int:
    """The most common strictly-positive delta between consecutive elements
    of an already-sorted sequence list -- the session's own OBSERVED step,
    never assumed to be 1 (the raw sequence counter is shared across all
    recorder topics, so per-channel deltas are naturally > 1)."""
    if len(sorted_sequences) < 2:
        raise EvidenceValidationError("need >= 2 sequence values to derive a modal step")
    deltas = {}
    for a, b in zip(sorted_sequences, sorted_sequences[1:]):
        d = b - a
        if d > 0:
            deltas[d] = deltas.get(d, 0) + 1
    if not deltas:
        raise EvidenceValidationError("no strictly-positive deltas found")
    return max(deltas.items(), key=lambda kv: (kv[1], -kv[0]))[0]


def nearest_neighbor_pairing(primary_times, secondary_times, tolerance: float):
    """One-to-one nearest-neighbor pairing of two sorted lists of monotonic
    times (seconds), never reusing a secondary index twice. Returns a list
    of (primary_index, secondary_index, offset_seconds) tuples where
    offset = secondary_time - primary_time, restricted to |offset| <=
    tolerance. Greedy forward-scan two-pointer algorithm; deterministic for
    a given input (no randomness, no wall-clock)."""
    pairs = []
    j = 0
    n_secondary = len(secondary_times)
    for i, t_primary in enumerate(primary_times):
        while j + 1 < n_secondary and abs(secondary_times[j + 1] - t_primary) <= abs(secondary_times[j] - t_primary):
            j += 1
        if n_secondary == 0:
            break
        offset = secondary_times[j] - t_primary
        if abs(offset) <= tolerance:
            pairs.append((i, j, offset))
            j = min(j + 1, n_secondary - 1) if j + 1 < n_secondary else j
    # Deduplicate any accidental double-use of a secondary index (keep the
    # closest match) -- guarantees strict one-to-one pairing.
    best_for_secondary = {}
    for i, j2, offset in pairs:
        key = j2
        if key not in best_for_secondary or abs(offset) < abs(best_for_secondary[key][2]):
            best_for_secondary[key] = (i, j2, offset)
    result = sorted(best_for_secondary.values(), key=lambda t: t[0])
    seen_i = set()
    deduped = []
    for i, j2, offset in result:
        if i in seen_i:
            continue
        seen_i.add(i)
        deduped.append((i, j2, offset))
    return deduped


def mean_absolute_error(errors) -> float:
    if not errors:
        raise EvidenceValidationError("cannot compute MAE over 0 errors")
    return sum(abs(e) for e in errors) / len(errors)


def root_mean_square_error(errors) -> float:
    if not errors:
        raise EvidenceValidationError("cannot compute RMSE over 0 errors")
    return math.sqrt(sum(e * e for e in errors) / len(errors))


def pearson_correlation(xs, ys) -> "float | None":
    n = len(xs)
    if n != len(ys) or n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return None
    value = cov / math.sqrt(var_x * var_y)
    return value if is_finite_number(value) else None


def unwrap_angles(angles):
    """Standard 2*pi unwrap over a sequence of angles already in radians.
    Returns (unwrapped_list, wrap_event_count)."""
    if not angles:
        return [], 0
    two_pi = 2.0 * math.pi
    unwrapped = [angles[0]]
    offset = 0.0
    wrap_events = 0
    for idx in range(1, len(angles)):
        raw = angles[idx] - angles[idx - 1]
        if raw > math.pi:
            offset -= two_pi
            wrap_events += 1
        elif raw < -math.pi:
            offset += two_pi
            wrap_events += 1
        unwrapped.append(angles[idx] + offset)
    return unwrapped, wrap_events

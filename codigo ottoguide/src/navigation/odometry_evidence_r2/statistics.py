"""Deterministic, pure statistics helpers for ODOM/TF R2-P0.

No I/O. Computes descriptive statistics ONLY -- these functions never
compare against ground truth (that distinction belongs to the caller) and
never invent a covariance value.
"""
import math

from .validation import EvidenceValidationError, all_finite, is_finite_number


def _mean(values):
    return sum(values) / len(values)


def _variance(values, mean_value):
    if len(values) < 2:
        return 0.0
    return sum((v - mean_value) ** 2 for v in values) / (len(values) - 1)


def compute_scalar_stats(values) -> dict:
    """Mean/variance/stddev/range for a 1-D sequence of finite numbers.
    Fail-closed: raises EvidenceValidationError on empty input or any
    non-finite element."""
    try:
        values = list(values)
    except Exception as exc:
        raise EvidenceValidationError("values is not iterable") from exc
    if len(values) == 0:
        raise EvidenceValidationError("cannot compute statistics over 0 samples")
    if not all_finite(values):
        raise EvidenceValidationError("non-finite value present in samples")

    mean_value = _mean(values)
    variance_value = _variance(values, mean_value)
    stddev_value = math.sqrt(variance_value)
    value_range = max(values) - min(values)
    return {
        "sample_count": len(values),
        "mean": mean_value,
        "variance": variance_value,
        "stddev": stddev_value,
        "range": value_range,
    }


def compute_vector_stats(vectors, dimensions: int) -> dict:
    """Per-axis mean/variance/stddev/range across a sequence of fixed-length
    vectors (e.g. position samples). Fail-closed on ragged/malformed input."""
    try:
        vectors = list(vectors)
    except Exception as exc:
        raise EvidenceValidationError("vectors is not iterable") from exc
    if len(vectors) == 0:
        raise EvidenceValidationError("cannot compute statistics over 0 samples")

    per_axis = [[] for _ in range(dimensions)]
    for vector in vectors:
        if type(vector) is not tuple and type(vector) is not list:
            raise EvidenceValidationError(f"malformed vector sample: {vector!r}")
        if len(vector) != dimensions:
            raise EvidenceValidationError(
                f"expected {dimensions}-dimensional vector, got {len(vector)}"
            )
        for axis_index, component in enumerate(vector):
            if not is_finite_number(component):
                raise EvidenceValidationError(
                    f"non-finite vector component: {component!r}"
                )
            per_axis[axis_index].append(float(component))

    means, variances, stddevs, ranges = [], [], [], []
    for axis_values in per_axis:
        stats = compute_scalar_stats(axis_values)
        means.append(stats["mean"])
        variances.append(stats["variance"])
        stddevs.append(stats["stddev"])
        ranges.append(stats["range"])

    return {
        "sample_count": len(vectors),
        "mean": tuple(means),
        "variance": tuple(variances),
        "stddev": tuple(stddevs),
        "range": tuple(ranges),
    }


ROBUST_METHOD = "SAMPLE_MEAN_AND_SAMPLE_STDDEV_NO_TRIMMING"
OUTLIER_RULE = "NONE_APPLIED_P0_DESCRIPTIVE_ONLY"

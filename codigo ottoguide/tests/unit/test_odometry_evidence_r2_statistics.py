"""Unit tests for src.navigation.odometry_evidence_r2.statistics."""
import unittest

from src.navigation.odometry_evidence_r2.statistics import (
    compute_scalar_stats,
    compute_vector_stats,
)
from src.navigation.odometry_evidence_r2.validation import EvidenceValidationError


class TestComputeScalarStats(unittest.TestCase):
    def test_basic_stats(self):
        stats = compute_scalar_stats([1.0, 2.0, 3.0])
        self.assertEqual(stats["sample_count"], 3)
        self.assertAlmostEqual(stats["mean"], 2.0)
        self.assertAlmostEqual(stats["range"], 2.0)

    def test_single_sample_zero_variance(self):
        stats = compute_scalar_stats([5.0])
        self.assertEqual(stats["variance"], 0.0)
        self.assertEqual(stats["stddev"], 0.0)

    def test_empty_input_fails_closed(self):
        with self.assertRaises(EvidenceValidationError):
            compute_scalar_stats([])

    def test_nan_fails_closed(self):
        with self.assertRaises(EvidenceValidationError):
            compute_scalar_stats([1.0, float("nan"), 2.0])

    def test_infinity_fails_closed(self):
        with self.assertRaises(EvidenceValidationError):
            compute_scalar_stats([1.0, float("inf")])

    def test_broken_iterable_fails_closed(self):
        class Hostile:
            def __iter__(self):
                raise RuntimeError("boom")

        with self.assertRaises(EvidenceValidationError):
            compute_scalar_stats(Hostile())

    def test_deterministic_across_calls(self):
        values = [0.1, 0.2, 0.3, 0.15, 0.25]
        first = compute_scalar_stats(values)
        second = compute_scalar_stats(values)
        self.assertEqual(first, second)


class TestComputeVectorStats(unittest.TestCase):
    def test_basic_3d_stats(self):
        vectors = [(1.0, 2.0, 3.0), (1.0, 2.0, 5.0)]
        stats = compute_vector_stats(vectors, 3)
        self.assertEqual(stats["sample_count"], 2)
        self.assertEqual(stats["range"], (0.0, 0.0, 2.0))

    def test_ragged_vector_fails_closed(self):
        with self.assertRaises(EvidenceValidationError):
            compute_vector_stats([(1.0, 2.0, 3.0), (1.0, 2.0)], 3)

    def test_non_vector_element_fails_closed(self):
        with self.assertRaises(EvidenceValidationError):
            compute_vector_stats([(1.0, 2.0, 3.0), "not-a-vector"], 3)

    def test_non_finite_component_fails_closed(self):
        with self.assertRaises(EvidenceValidationError):
            compute_vector_stats([(1.0, float("nan"), 3.0)], 3)

    def test_empty_input_fails_closed(self):
        with self.assertRaises(EvidenceValidationError):
            compute_vector_stats([], 3)


if __name__ == "__main__":
    unittest.main()

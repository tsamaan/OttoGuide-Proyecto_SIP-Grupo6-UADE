"""Unit tests for src.navigation.odometry_evidence_r2.validation (fail-closed
primitives). unittest-based per checkpoint section 27."""
import math
import unittest

from src.navigation.odometry_evidence_r2 import validation as v


class TestSha256Hex(unittest.TestCase):
    def test_valid_sha256_accepted(self):
        self.assertTrue(v.is_sha256_hex("a" * 64))

    def test_uppercase_rejected(self):
        self.assertFalse(v.is_sha256_hex("A" * 64))

    def test_wrong_length_rejected(self):
        self.assertFalse(v.is_sha256_hex("a" * 63))
        self.assertFalse(v.is_sha256_hex("a" * 65))

    def test_non_hex_rejected(self):
        self.assertFalse(v.is_sha256_hex("g" * 64))

    def test_non_string_rejected(self):
        self.assertFalse(v.is_sha256_hex(12345))
        self.assertFalse(v.is_sha256_hex(None))
        self.assertFalse(v.is_sha256_hex(b"a" * 64))


class TestPortablePath(unittest.TestCase):
    def test_relative_path_accepted(self):
        self.assertTrue(v.is_relative_portable_path("10_r4b/R4B_RESULT.json"))

    def test_absolute_windows_path_rejected(self):
        self.assertFalse(v.is_relative_portable_path(r"C:\Users\someone\file.json"))

    def test_absolute_posix_path_rejected(self):
        self.assertFalse(v.is_relative_portable_path("/etc/passwd"))

    def test_path_traversal_rejected(self):
        self.assertFalse(v.is_relative_portable_path("../../etc/passwd"))
        self.assertFalse(v.is_relative_portable_path("a/../../b"))

    def test_empty_segment_rejected(self):
        self.assertFalse(v.is_relative_portable_path("a//b"))

    def test_empty_string_rejected(self):
        self.assertFalse(v.is_relative_portable_path(""))

    def test_non_string_rejected(self):
        self.assertFalse(v.is_relative_portable_path(None))
        self.assertFalse(v.is_relative_portable_path(123))


class TestBoolRejection(unittest.TestCase):
    def test_is_plain_bool_true_for_bool(self):
        self.assertTrue(v.is_plain_bool(True))
        self.assertTrue(v.is_plain_bool(False))

    def test_is_plain_bool_false_for_int(self):
        self.assertFalse(v.is_plain_bool(1))
        self.assertFalse(v.is_plain_bool(0))

    def test_is_bounded_int_rejects_bool(self):
        # bool is a subclass of int in Python; is_bounded_int must reject it
        # via `type(x) is not int` rather than isinstance().
        self.assertFalse(v.is_bounded_int(True, minimum=0, maximum=10))
        self.assertFalse(v.is_bounded_int(False, minimum=0, maximum=10))

    def test_is_bounded_int_accepts_plain_int(self):
        self.assertTrue(v.is_bounded_int(5, minimum=0, maximum=10))

    def test_is_bounded_int_rejects_out_of_range(self):
        self.assertFalse(v.is_bounded_int(11, minimum=0, maximum=10))
        self.assertFalse(v.is_bounded_int(-1, minimum=0, maximum=10))


class TestFiniteNumberRejection(unittest.TestCase):
    def test_nan_rejected(self):
        self.assertFalse(v.is_finite_number(float("nan")))

    def test_positive_infinity_rejected(self):
        self.assertFalse(v.is_finite_number(float("inf")))

    def test_negative_infinity_rejected(self):
        self.assertFalse(v.is_finite_number(float("-inf")))

    def test_bool_rejected_as_number(self):
        # bool is an int subclass; normalize_finite_number must reject it via
        # an exact-type gate (imported from R1's validation module).
        self.assertFalse(v.is_finite_number(True))

    def test_huge_int_overflow_rejected(self):
        self.assertFalse(v.is_finite_number(10 ** 10000))

    def test_ordinary_float_accepted(self):
        self.assertTrue(v.is_finite_number(1.5))

    def test_all_finite_rejects_hostile_iterable(self):
        class Hostile:
            def __iter__(self):
                raise RuntimeError("boom")

        self.assertFalse(v.all_finite(Hostile()))


class TestStatusVocabulary(unittest.TestCase):
    def test_all_status_values_accepted(self):
        for status in v.STATUS_VALUES:
            self.assertEqual(v.validate_status(status), status)

    def test_unknown_status_rejected(self):
        with self.assertRaises(v.EvidenceValidationError):
            v.validate_status("MOSTLY_TRUE")

    def test_non_string_status_rejected(self):
        with self.assertRaises(v.EvidenceValidationError):
            v.validate_status(None)


class TestGroundTruthVocabulary(unittest.TestCase):
    def test_all_ground_truth_values_accepted(self):
        for gt in v.GROUND_TRUTH_VALUES:
            self.assertEqual(v.validate_ground_truth(gt), gt)

    def test_unknown_ground_truth_rejected(self):
        with self.assertRaises(v.EvidenceValidationError):
            v.validate_ground_truth("PROBABLY_MEASURED")

    def test_nominal_never_auto_promoted_to_measured(self):
        # NOMINAL and MEASURED are distinct constants; validate_ground_truth
        # must not silently coerce one into the other.
        self.assertEqual(v.validate_ground_truth("NOMINAL"), "NOMINAL")
        self.assertNotEqual("NOMINAL", "MEASURED")


class TestUnknownFieldRejection(unittest.TestCase):
    def test_known_fields_pass(self):
        v.validate_no_unknown_fields({"a": 1, "b": 2}, {"a", "b", "c"})

    def test_unknown_field_raises(self):
        with self.assertRaises(v.EvidenceValidationError):
            v.validate_no_unknown_fields({"a": 1, "z": 99}, {"a", "b"})

    def test_non_dict_raises(self):
        with self.assertRaises(v.EvidenceValidationError):
            v.validate_no_unknown_fields(["a", "b"], {"a"})


class TestSha256Tuple(unittest.TestCase):
    def test_valid_tuple_accepted(self):
        result = v.validate_sha256_tuple(("a" * 64, "b" * 64))
        self.assertEqual(result, ("a" * 64, "b" * 64))

    def test_invalid_element_rejected(self):
        with self.assertRaises(v.EvidenceValidationError):
            v.validate_sha256_tuple(("a" * 64, "not-a-hash"))

    def test_non_iterable_rejected(self):
        with self.assertRaises(v.EvidenceValidationError):
            v.validate_sha256_tuple(42)


if __name__ == "__main__":
    unittest.main()

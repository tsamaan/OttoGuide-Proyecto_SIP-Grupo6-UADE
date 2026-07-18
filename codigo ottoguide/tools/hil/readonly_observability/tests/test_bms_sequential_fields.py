#!/usr/bin/env python3
"""FASE A2 (R0B hotfix) - pruebas puras del manejo de bmsvoltage escalar/secuencia,
filtrado de celdas para validacion fisica, y relative_cell_sum_error (sin DDS, sin robot).
Ejecutar: python tests/test_bms_sequential_fields.py
"""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "companion"))
from ottoguide_common import bmsvoltage_or_none, positive_numeric_or_empty, relative_cell_sum_error
import ottoguide_readonly_bridge as bridge


class TestBmsvoltageOrNone(unittest.TestCase):
    def test_scalar_used_directly(self):
        self.assertEqual(bmsvoltage_or_none(54.2), 54.2)

    def test_scalar_used_as_is_even_if_zero_or_negative(self):
        # Spec: "bmsvoltage escalar: usar el valor" -- sin filtro de signo. El filtro de
        # positividad aplica SOLO al caso secuencia (elegir el primer candidato).
        self.assertEqual(bmsvoltage_or_none(0), 0)
        self.assertEqual(bmsvoltage_or_none(-1.0), -1.0)

    def test_sequence_first_positive_candidate(self):
        self.assertEqual(bmsvoltage_or_none([0, -3, None, "x", 54.1, 55.0]), 54.1)

    def test_sequence_all_non_positive_returns_none(self):
        self.assertIsNone(bmsvoltage_or_none([0, -1, -2]))

    def test_sequence_empty_returns_none(self):
        self.assertIsNone(bmsvoltage_or_none([]))

    def test_non_numeric_returns_none(self):
        self.assertIsNone(bmsvoltage_or_none("54.0"))
        self.assertIsNone(bmsvoltage_or_none(None))

    def test_bool_is_not_numeric(self):
        self.assertIsNone(bmsvoltage_or_none(True))


class TestPositiveNumericOrEmpty(unittest.TestCase):
    def test_ignores_non_numeric_zero_and_negative(self):
        self.assertEqual(positive_numeric_or_empty([3.6, 0, -1, None, "x", 3.7]), [3.6, 3.7])

    def test_empty_input(self):
        self.assertEqual(positive_numeric_or_empty([]), [])
        self.assertEqual(positive_numeric_or_empty(None), [])


class TestRelativeCellSumError(unittest.TestCase):
    def test_matching_pack_and_cells(self):
        # 3 celdas de 3.6V ~ 10.8V pack -> error relativo pequeno
        err = relative_cell_sum_error(10.8, [3.6, 3.6, 3.6])
        self.assertAlmostEqual(err, 0.0, places=4)

    def test_mismatched_scale_flagged(self):
        # Si la escala de celdas fuera incorrecta (10x), el error relativo debe ser grande.
        err = relative_cell_sum_error(10.8, [36.0, 36.0, 36.0])
        self.assertGreater(err, 5.0)

    def test_none_when_pack_missing(self):
        self.assertIsNone(relative_cell_sum_error(None, [3.6, 3.6]))

    def test_none_when_cells_empty(self):
        self.assertIsNone(relative_cell_sum_error(10.8, []))


class TestCanonicalBmsCellFiltering(unittest.TestCase):
    def setUp(self):
        bridge._bms_ok = True
        bridge._bms_cfg = {"voltage_field": "bmsvoltage", "voltage_scale": 0.001,
                           "current_scale": 0.001, "cell_scale": 0.001, "temperature_scale": 1.0}

    def test_zero_and_negative_cells_excluded_from_canonical_output(self):
        raw = {"raw_voltage": 10800, "raw_current": 1000, "soc": 90,
               "raw_cells": [3600, 0, -50, 3600, 3600], "raw_temps": [25]}
        bms, _, _ = bridge.canonical_bms(raw)
        self.assertEqual(bms["cell_vol_v"], [3.6, 3.6, 3.6])  # padding/invalido descartado

    def test_relative_cell_sum_error_present_when_comparable(self):
        raw = {"raw_voltage": 10800, "raw_current": 1000, "soc": 90,
               "raw_cells": [3600, 3600, 3600], "raw_temps": [25]}
        bms, _, _ = bridge.canonical_bms(raw)
        self.assertIsNotNone(bms["relative_cell_sum_error"])
        self.assertAlmostEqual(bms["relative_cell_sum_error"], 0.0, places=4)


if __name__ == "__main__":
    unittest.main(verbosity=2)

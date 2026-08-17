#!/usr/bin/env python3
"""FASE C/L — pruebas puras del contrato canonico BMS del bridge (sin DDS ni robot).
Importa el modulo del bridge (sus imports top-level son stdlib + common), configura las
escalas del probe y verifica la conversion fisica y power_w = voltage_v*current_a (con signo).
Ejecutar: python tests/test_bms_canonical.py
"""
import os, sys, unittest

RT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "companion")
sys.path.insert(0, RT)
import ottoguide_readonly_bridge as bridge


class TestCanonicalBms(unittest.TestCase):
    def setUp(self):
        bridge._bms_ok = True
        bridge._bms_cfg = {"voltage_field": "bmsvoltage", "voltage_scale": 0.001,
                           "current_scale": 0.001, "cell_scale": 0.001, "temperature_scale": 1.0}

    def test_scaling_and_power_sign_discharge(self):
        raw = {"raw_voltage": 54000, "raw_current": -3200, "soc": 87, "soh": 99,
               "raw_cells": [3600, 3605, 3598], "raw_temps": [31, 32], "cycle": 12}
        bms, pv, pa = bridge.canonical_bms(raw)
        self.assertAlmostEqual(bms["voltage_v"], 54.0, places=3)
        self.assertAlmostEqual(bms["current_a"], -3.2, places=3)
        self.assertAlmostEqual(bms["power_w"], 54.0 * -3.2, places=2)  # signo conservado (descarga)
        self.assertLess(bms["power_w"], 0)
        self.assertEqual(bms["cell_vol_v"], [3.6, 3.605, 3.598])
        self.assertEqual(bms["temperature_c"], [31.0, 32.0])
        self.assertEqual(pv, 54.0)
        self.assertEqual(pa, -3.2)

    def test_power_sign_charge(self):
        raw = {"raw_voltage": 55000, "raw_current": 2000, "soc": 90, "raw_cells": [3660],
               "raw_temps": [30]}
        bms, _, _ = bridge.canonical_bms(raw)
        self.assertGreater(bms["power_w"], 0)  # carga -> potencia positiva

    def test_absent_fields_stay_null(self):
        raw = {"raw_voltage": None, "raw_current": None, "soc": None, "raw_cells": [], "raw_temps": []}
        bms, pv, pa = bridge.canonical_bms(raw)
        self.assertIsNone(bms["voltage_v"])
        self.assertIsNone(bms["current_a"])
        self.assertIsNone(bms["power_w"])  # no se inventa 0.0
        self.assertEqual(bms["cell_vol_v"], [])
        self.assertIsNone(pv)
        self.assertIsNone(pa)

    def test_not_accepted_returns_none(self):
        bridge._bms_ok = False
        bms, pv, pa = bridge.canonical_bms({"raw_voltage": 54000, "raw_current": 1000})
        self.assertIsNone(bms)
        self.assertIsNone(pv)
        self.assertIsNone(pa)


if __name__ == "__main__":
    unittest.main(verbosity=2)

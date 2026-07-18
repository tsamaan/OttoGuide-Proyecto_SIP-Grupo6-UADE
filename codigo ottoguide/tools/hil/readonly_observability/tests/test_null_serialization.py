#!/usr/bin/env python3
"""FASE B/L — pruebas puras de serializacion null-real (sin DDS, sin robot).
Verifican: ausente -> None; presente y fisicamente cero -> 0; no sustituir con 0.0.
Ejecutar: python tests/test_null_serialization.py
"""
import json, os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "companion"))
from ottoguide_common import number_or_none, scalar_or_none, round_or_none


class Obj:
    pass


class TestNullReal(unittest.TestCase):
    def test_absent_is_none(self):
        o = Obj()
        self.assertIsNone(number_or_none(o, "dq"))
        self.assertIsNone(number_or_none(o, "tau_est"))

    def test_present_zero_is_zero(self):
        o = Obj(); o.dq = 0.0; o.ddq = 0; o.tau_est = -0.0
        self.assertEqual(number_or_none(o, "dq"), 0.0)
        self.assertEqual(number_or_none(o, "ddq"), 0)
        self.assertEqual(number_or_none(o, "tau_est"), -0.0)

    def test_present_value(self):
        o = Obj(); o.yaw_speed = -0.0064
        self.assertEqual(number_or_none(o, "yaw_speed"), -0.0064)

    def test_bool_is_not_number(self):
        o = Obj(); o.flag = True
        self.assertIsNone(number_or_none(o, "flag"))  # bool no es dato fisico numerico

    def test_scalar_or_none_array(self):
        self.assertEqual(scalar_or_none([25, 26]), 25)     # temperatura como array -> primer valido
        self.assertEqual(scalar_or_none(37), 37)           # escalar directo
        self.assertIsNone(scalar_or_none([]))              # vacio -> None
        self.assertIsNone(scalar_or_none(None))
        self.assertEqual(scalar_or_none([None, 0]), 0)     # cero fisico dentro del array

    def test_round_or_none(self):
        self.assertIsNone(round_or_none(None, 5))
        self.assertEqual(round_or_none(0.0, 5), 0.0)
        self.assertEqual(round_or_none(1.234567, 2), 1.23)

    def test_json_roundtrip_preserves_null(self):
        # Un motor sin dq/tau se serializa con null, no con 0.0.
        o = Obj(); o.q = 0.0  # articulacion fisicamente en cero
        motor = {
            "q_rad": round_or_none(number_or_none(o, "q"), 5),
            "dq": round_or_none(number_or_none(o, "dq"), 5),
            "tau_est": round_or_none(number_or_none(o, "tau_est"), 5),
        }
        s = json.dumps(motor)
        back = json.loads(s)
        self.assertEqual(back["q_rad"], 0.0)     # cero fisico preservado
        self.assertIsNone(back["dq"])            # ausente = null
        self.assertIsNone(back["tau_est"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""FASE A1 (R0B hotfix) - prueba pura de persistencia de latest_odom (sin DDS, sin robot).

Escenario exigido:
  odom recibido -> iteracion sin odom -> nube con desplazamiento acumulado -> trigger dpos disponible.

Antes del hotfix, `latest_odom` se reiniciaba a None al comienzo de cada iteracion del
bucle principal, así que si la nube LiDAR llegaba en una iteracion SIN muestra nueva de
rt/odommodestate, `pos` era None y el trigger "dpos" nunca podia dispararse aunque hubiera
desplazamiento acumulado real. El hotfix declara latest_odom fuera del while y solo lo
actualiza cuando llega una muestra nueva.

Ejecutar: python tests/test_odom_persistence.py
"""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "companion"))
from ottoguide_common import decide_keyframe_trigger

KF_DT_S, KF_DPOS_M, KF_DYAW_DEG = 2.0, 0.05, 5.0


class FakeRecorderLoop:
    """Reproduce el patron de estado del recorder (post-hotfix A1): latest_odom vive
    fuera del bucle y solo se actualiza cuando `feed_odom` trae una muestra nueva."""

    def __init__(self):
        self.latest_odom = None          # FASE A1: vive fuera del while, nunca se resetea a None por iteracion
        self.last_cloud_t = 0.0
        self.last_cloud_pos = None
        self.last_cloud_imu_yaw = None
        self.latest_imu_yaw_rad = None

    def feed_odom(self, position):
        self.latest_odom = {"position": position}

    def iterate_no_odom(self):
        """Una iteracion del bucle principal SIN mensaje nuevo de rt/odommodestate."""
        pass  # FASE A1: a proposito no se toca self.latest_odom aqui

    def cloud_arrives(self, now, phase_changed=False):
        pos = self.latest_odom["position"] if self.latest_odom else None
        return decide_keyframe_trigger(now, phase_changed, self.last_cloud_t, pos,
                                        self.last_cloud_pos, self.latest_imu_yaw_rad,
                                        self.last_cloud_imu_yaw, KF_DT_S, KF_DPOS_M, KF_DYAW_DEG)


class TestOdomPersistence(unittest.TestCase):
    def test_dpos_trigger_survives_iteration_without_new_odom(self):
        loop = FakeRecorderLoop()
        # t=0: primer keyframe establece la posicion base del cloud.
        loop.feed_odom([0.0, 0.0, 0.0])
        trig0 = loop.cloud_arrives(now=0.1)
        self.assertEqual(trig0, "dt")  # primer keyframe siempre dispara (last_cloud_t == 0.0)
        loop.last_cloud_t = 0.1
        loop.last_cloud_pos = loop.latest_odom["position"]

        # odom recibido con desplazamiento real (0.08 m > KF_DPOS_M) ...
        loop.feed_odom([0.08, 0.0, 0.0])
        # ... pero luego una o mas iteraciones SIN odom nuevo antes de que llegue la nube.
        loop.iterate_no_odom()
        loop.iterate_no_odom()

        # La nube llega en una iteracion sin odom nuevo, dentro de la ventana KF_DT_S.
        trig1 = loop.cloud_arrives(now=0.9)
        self.assertEqual(trig1, "dpos")  # debe seguir viendo el ultimo odom conocido, no None

    def test_bug_reproduction_if_odom_reset_each_iteration(self):
        """Reproduce el bug pre-hotfix: si latest_odom se resetea a None cada iteracion
        (patron viejo), el trigger dpos se pierde aunque haya desplazamiento acumulado."""
        last_cloud_t, last_cloud_pos = 0.1, [0.0, 0.0, 0.0]
        latest_odom_buggy = None  # reset a None en la iteracion sin odom (comportamiento viejo)
        pos = latest_odom_buggy["position"] if latest_odom_buggy else None
        trig = decide_keyframe_trigger(now=0.9, phase_changed=False, last_cloud_t=last_cloud_t,
                                        pos=pos, last_cloud_pos=last_cloud_pos, imu_yaw=None,
                                        last_cloud_imu_yaw=None, dt_s=KF_DT_S, dpos_m=KF_DPOS_M,
                                        dyaw_deg=KF_DYAW_DEG)
        self.assertIsNone(trig)  # confirma que el bug viejo perdia el trigger dpos disponible


if __name__ == "__main__":
    unittest.main(verbosity=2)

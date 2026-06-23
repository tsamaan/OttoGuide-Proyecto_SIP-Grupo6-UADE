"""
Fuente de telemetria. Decide de donde salen las metricas:
- MOCK_MODE=true  -> datos simulados (mock_telemetry).
- MOCK_MODE=false -> datos reales del robot via DDS (unitree_sdk2py).
  Si el SDK no esta instalado, la interfaz es invalida o no llegan paquetes
  en DDS_TIMEOUT_S segundos, cae al mock como fallback sin romper el arranque.
"""
import logging
import math
import threading
import time

from app.config import settings
from app.mock.mock_telemetry import mock

log = logging.getLogger("ottoguide")

# ---------------------------------------------------------------------------
# Mapa de joints del G1 — 29 motores (indices 0-28).
# Definido inline para no importar nada de reference/ en runtime.
# ---------------------------------------------------------------------------
_G1_JOINT_MAP = {
    0:  {"name": "L_Hip_Pitch",      "group": "Pierna Izquierda"},
    1:  {"name": "L_Hip_Roll",       "group": "Pierna Izquierda"},
    2:  {"name": "L_Hip_Yaw",        "group": "Pierna Izquierda"},
    3:  {"name": "L_Knee",           "group": "Pierna Izquierda"},
    4:  {"name": "L_Ankle_Pitch",    "group": "Pierna Izquierda"},
    5:  {"name": "L_Ankle_Roll",     "group": "Pierna Izquierda"},
    6:  {"name": "R_Hip_Pitch",      "group": "Pierna Derecha"},
    7:  {"name": "R_Hip_Roll",       "group": "Pierna Derecha"},
    8:  {"name": "R_Hip_Yaw",        "group": "Pierna Derecha"},
    9:  {"name": "R_Knee",           "group": "Pierna Derecha"},
    10: {"name": "R_Ankle_Pitch",    "group": "Pierna Derecha"},
    11: {"name": "R_Ankle_Roll",     "group": "Pierna Derecha"},
    12: {"name": "Waist_Yaw",        "group": "Cintura"},
    13: {"name": "Waist_Roll",       "group": "Cintura"},
    14: {"name": "Waist_Pitch",      "group": "Cintura"},
    15: {"name": "L_Shoulder_Pitch", "group": "Brazo Izquierdo"},
    16: {"name": "L_Shoulder_Roll",  "group": "Brazo Izquierdo"},
    17: {"name": "L_Shoulder_Yaw",   "group": "Brazo Izquierdo"},
    18: {"name": "L_Elbow",          "group": "Brazo Izquierdo"},
    19: {"name": "L_Wrist_Roll",     "group": "Mano Izquierda"},
    20: {"name": "L_Wrist_Pitch",    "group": "Mano Izquierda"},
    21: {"name": "L_Wrist_Yaw",      "group": "Mano Izquierda"},
    22: {"name": "R_Shoulder_Pitch", "group": "Brazo Derecho"},
    23: {"name": "R_Shoulder_Roll",  "group": "Brazo Derecho"},
    24: {"name": "R_Shoulder_Yaw",   "group": "Brazo Derecho"},
    25: {"name": "R_Elbow",          "group": "Brazo Derecho"},
    26: {"name": "R_Wrist_Roll",     "group": "Mano Derecha"},
    27: {"name": "R_Wrist_Pitch",    "group": "Mano Derecha"},
    28: {"name": "R_Wrist_Yaw",      "group": "Mano Derecha"},
}
_G1_NUM_MOTORS = 29


# ---------------------------------------------------------------------------
# Lector DDS (solo se instancia cuando MOCK_MODE=false)
# ---------------------------------------------------------------------------
class _DDSReader:
    """Suscribe a rt/lowstate por DDS y cachea el ultimo frame recibido."""

    def __init__(self):
        self._lock = threading.Lock()
        self._last_frame: dict | None = None
        self._last_ts: float = 0.0  # timestamp del ultimo frame recibido
        self._ok = False

    def start(self) -> bool:
        """Intenta inicializar DDS. Devuelve True si salio bien."""
        try:
            from unitree_sdk2py.core.channel import (
                ChannelSubscriber,
                ChannelFactoryInitialize,
            )
            from unitree_sdk2py.idl.unitree_hg.msg.dds_ import (
                LowState_ as LowState,
            )

            ChannelFactoryInitialize(0, settings.DDS_INTERFACE)

            sub = ChannelSubscriber("rt/lowstate", LowState)
            sub.Init(self._handler, 10)

            self._ok = True
            log.info(
                "Lector DDS iniciado en interfaz '%s', suscripto a rt/lowstate.",
                settings.DDS_INTERFACE,
            )
            return True

        except ImportError:
            log.warning(
                "unitree_sdk2py no esta instalado; la telemetria real no esta disponible."
            )
        except Exception as exc:
            log.warning(
                "No se pudo inicializar DDS en interfaz '%s': %s. "
                "Cayendo al mock.",
                settings.DDS_INTERFACE,
                exc,
            )
        return False

    # -- handler llamado por el subscriber de DDS (en su hilo interno) ------

    def _handler(self, msg):
        """Convierte el LowState DDS al dict con el mismo schema que el mock."""
        try:
            frame = self._build_frame(msg)
            with self._lock:
                self._last_frame = frame
                self._last_ts = time.time()
        except Exception:
            log.exception("Error procesando paquete DDS lowstate")

    def _build_frame(self, msg) -> dict:
        """Arma el dict de telemetria a partir del mensaje DDS."""
        motors = []
        for idx in range(_G1_NUM_MOTORS):
            ms = msg.motor_state[idx]

            q    = ms.q           if not callable(ms.q)           else ms.q()
            dq   = ms.dq          if not callable(ms.dq)          else ms.dq()
            ddq  = ms.ddq         if not callable(ms.ddq)         else ms.ddq()
            tau  = ms.tau_est     if not callable(ms.tau_est)      else ms.tau_est()
            temp = ms.temperature if not callable(ms.temperature)  else ms.temperature()

            info = _G1_JOINT_MAP.get(idx, {"name": f"Motor_{idx}", "group": "Otro"})

            motors.append({
                "index":       idx,
                "name":        info["name"],
                "group":       info["group"],
                "q_rad":       round(float(q), 4),
                "q_deg":       round(math.degrees(float(q)), 2),
                "dq":          round(float(dq), 4),
                "ddq":         round(float(ddq), 4),
                "tau_est":     round(float(tau), 4),
                "temperature": int(temp) if isinstance(temp, (int, float)) else 0,
            })

        # Power
        try:
            pv = msg.power_v
            power_v = float(pv() if callable(pv) else pv)
        except Exception:
            power_v = 0.0
        try:
            pa = msg.power_a
            power_a = float(pa() if callable(pa) else pa)
        except Exception:
            power_a = 0.0

        # IMU
        try:
            imu   = msg.imu_state   if not callable(msg.imu_state)   else msg.imu_state()
            quat  = imu.quaternion  if not callable(imu.quaternion)  else imu.quaternion()
            gyro  = imu.gyroscope   if not callable(imu.gyroscope)   else imu.gyroscope()
            accel = imu.accelerometer if not callable(imu.accelerometer) else imu.accelerometer()
            rpy   = imu.rpy         if not callable(imu.rpy)         else imu.rpy()
            imu_data = {
                "quaternion":    [round(float(quat[i]), 4)  for i in range(4)],
                "gyroscope":     [round(float(gyro[i]), 4)  for i in range(3)],
                "accelerometer": [round(float(accel[i]), 4) for i in range(3)],
                "rpy_deg":       [round(math.degrees(float(rpy[i])), 2) for i in range(3)],
            }
        except Exception:
            imu_data = {
                "quaternion": [0, 0, 0, 0],
                "gyroscope": [0, 0, 0],
                "accelerometer": [0, 0, 0],
                "rpy_deg": [0, 0, 0],
            }

        # Foot force
        foot_force = [0, 0, 0, 0]
        try:
            ff = msg.foot_force if not callable(msg.foot_force) else msg.foot_force()
            foot_force = [int(ff[i]) for i in range(4)]
        except Exception:
            pass

        # BMS
        try:
            bms = msg.bms_state
            bms_data = {
                "soc":      int(bms.soc),
                "cycle":    int(bms.cycle),
                "current":  int(bms.current),
                "status":   int(bms.status),
                "mcu_ntc":  list(bms.mcu_ntc),
                "bq_ntc":   list(bms.bq_ntc),
                "cell_vol": list(bms.cell_vol),
            }
        except Exception:
            bms_data = {
                "soc": 0, "cycle": 0, "current": 0,
                "status": 0, "mcu_ntc": [], "bq_ntc": [], "cell_vol": [],
            }

        return {
            "robot":      "G1",
            "timestamp":  time.time(),
            "power_v":    round(power_v, 2),
            "power_a":    round(power_a, 2),
            "motors":     motors,
            "imu":        imu_data,
            "foot_force": foot_force,
            "bms":        bms_data,
        }

    def get_frame(self) -> dict | None:
        """Devuelve el ultimo frame cacheado, o None si no hay o si expiro el timeout."""
        with self._lock:
            if self._last_frame is None:
                return None
            age = time.time() - self._last_ts
            if age > settings.DDS_TIMEOUT_S:
                return None
            return self._last_frame


# ---------------------------------------------------------------------------
# Singleton del lector DDS (se inicializa lazy, una sola vez)
# ---------------------------------------------------------------------------
_dds_reader: _DDSReader | None = None
_dds_init_done = False


def _ensure_dds():
    """Inicializa el lector DDS una sola vez. No lanza excepciones."""
    global _dds_reader, _dds_init_done
    if _dds_init_done:
        return
    _dds_init_done = True

    reader = _DDSReader()
    if reader.start():
        _dds_reader = reader


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------
def get_frame() -> dict:
    """Devuelve un frame de telemetria. Mismo schema que mock_telemetry."""
    if settings.MOCK_MODE:
        return mock.frame()

    # Modo real: intentar leer DDS
    _ensure_dds()

    if _dds_reader is not None:
        frame = _dds_reader.get_frame()
        if frame is not None:
            return frame

    # Fallback: DDS no arranco, no hay frame o timeout -> devolver mock.
    log.debug(
        "Telemetria DDS no disponible (interfaz=%s, timeout=%ss); "
        "usando mock como fallback.",
        settings.DDS_INTERFACE,
        settings.DDS_TIMEOUT_S,
    )
    return mock.frame()

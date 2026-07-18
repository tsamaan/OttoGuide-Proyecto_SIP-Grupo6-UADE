#!/usr/bin/env python3
"""OttoGuide NB-HIL-WEB-R0 — utilidades compartidas del runtime remoto (read-only).

STRICTLY PASSIVE. Este modulo NO crea entidades DDS de escritura, NO importa LocoClient,
SportClient ni MotionSwitcher, y NO envia comandos de movimiento. Solo resuelve el SDK,
configura CycloneDDS sobre eth0 y provee el mapa de 29 articulaciones y helpers de tiempo.
"""
from __future__ import annotations
import glob, math, os, sys, time

# ---- CycloneDDS: eth0 explicito, sin autodeteccion (fail-closed de interfaz) ----
os.environ.setdefault(
    "CYCLONEDDS_URI",
    "<CycloneDDS><Domain><General><Interfaces>"
    '<NetworkInterface name="eth0" priority="default" multicast="default"/>'
    "</Interfaces></General></Domain></CycloneDDS>",
)


def resolve_sdk_path():
    """Detecta dinamicamente unitree_sdk2_python (FASE O: no asumir la ruta historica).

    Orden: variable de entorno OTTOGUIDE_SDK_PATH, luego rutas conocidas de deployments,
    luego busqueda acotada bajo /home/unitree. Devuelve la ruta o None.
    """
    env = os.environ.get("OTTOGUIDE_SDK_PATH")
    candidates = []
    if env:
        candidates.append(env)
    candidates += [
        "/home/unitree/unitree_sdk2_python",
        "/home/unitree/ottoguide/codigo ottoguide/libs/unitree_sdk2_python",
    ]
    # deployments historicos: */codigo ottoguide/libs/unitree_sdk2_python
    candidates += sorted(glob.glob("/home/unitree/ottoguide_deployments/*/codigo ottoguide/libs/unitree_sdk2_python"))
    # busqueda acotada de respaldo
    candidates += sorted(glob.glob("/home/unitree/**/unitree_sdk2_python", recursive=True))
    for c in candidates:
        if c and os.path.isdir(c) and os.path.isdir(os.path.join(c, "unitree_sdk2py")):
            return c
    return None


def ensure_sdk_on_path():
    p = resolve_sdk_path()
    if p and p not in sys.path:
        sys.path.insert(0, p)
    return p


# 29-index reference joint map (semantic, G1 EDU — igual al bridge R2 y al frontend).
JOINTS = [
    (0, "L_Hip_Pitch", "Pierna Izquierda"), (1, "L_Hip_Roll", "Pierna Izquierda"),
    (2, "L_Hip_Yaw", "Pierna Izquierda"), (3, "L_Knee", "Pierna Izquierda"),
    (4, "L_Ankle_Pitch", "Pierna Izquierda"), (5, "L_Ankle_Roll", "Pierna Izquierda"),
    (6, "R_Hip_Pitch", "Pierna Derecha"), (7, "R_Hip_Roll", "Pierna Derecha"),
    (8, "R_Hip_Yaw", "Pierna Derecha"), (9, "R_Knee", "Pierna Derecha"),
    (10, "R_Ankle_Pitch", "Pierna Derecha"), (11, "R_Ankle_Roll", "Pierna Derecha"),
    (12, "Waist_Yaw", "Cintura"), (13, "Waist_Roll", "Cintura"), (14, "Waist_Pitch", "Cintura"),
    (15, "L_Shoulder_Pitch", "Brazo Izquierdo"), (16, "L_Shoulder_Roll", "Brazo Izquierdo"),
    (17, "L_Shoulder_Yaw", "Brazo Izquierdo"), (18, "L_Elbow", "Brazo Izquierdo"),
    (19, "L_Wrist_Roll", "Mano Izquierda"), (20, "L_Wrist_Pitch", "Mano Izquierda"),
    (21, "L_Wrist_Yaw", "Mano Izquierda"),
    (22, "R_Shoulder_Pitch", "Brazo Derecho"), (23, "R_Shoulder_Roll", "Brazo Derecho"),
    (24, "R_Shoulder_Yaw", "Brazo Derecho"), (25, "R_Elbow", "Brazo Derecho"),
    (26, "R_Wrist_Roll", "Mano Derecha"), (27, "R_Wrist_Pitch", "Mano Derecha"),
    (28, "R_Wrist_Yaw", "Mano Derecha"),
]


def number_or_none(obj, field):
    """FASE B: null real. Devuelve el valor SOLO si es numerico; ausencia -> None.
    Regla: ausente = None; presente y fisicamente cero = 0 (nunca sustituir ausencia por 0.0).
    """
    value = getattr(obj, field, None)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def scalar_or_none(value):
    """Como number_or_none pero para un valor ya extraido (o primer elemento de array)."""
    if isinstance(value, (list, tuple)):
        for v in value:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return v
        return None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def round_or_none(value, ndigits):
    """Redondea solo si es numerico; conserva None (no lo convierte en 0.0)."""
    return round(value, ndigits) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def monotonic_ns():
    return time.monotonic_ns()


def read_phase(phase_file):
    """Lee el marcador de fase actual (escrito por mark_phase.ps1). Vacio si no existe."""
    try:
        with open(phase_file, "r", encoding="utf-8") as f:
            return f.read().strip() or "UNMARKED"
    except OSError:
        return "UNMARKED"


def bmsvoltage_or_none(value):
    """FASE A2: bmsvoltage puede llegar como escalar o como secuencia (schema real por
    descubrir en campo). Escalar numerico -> usar el valor tal cual. Secuencia -> primer
    candidato numerico POSITIVO (ignora no numericos, cero y negativos, que no son un
    voltaje de pack fisicamente valido)."""
    if isinstance(value, (list, tuple)):
        for v in value:
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                return v
        return None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def positive_numeric_or_empty(values):
    """FASE A2: para VALIDACION fisica de cell_vol, ignora valores no numericos, cero y
    negativos (una celda de Li-ion nunca es <=0V en operacion). No filtra la persistencia
    cruda -- solo se usa para decidir escala/coherencia."""
    if not values:
        return []
    return [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0]


def relative_cell_sum_error(pack_voltage, cells):
    """FASE A2: cuando el voltaje de pack y las celdas son comparables (ambos presentes),
    error relativo entre la suma de celdas y el voltaje de pack. Sirve como chequeo
    independiente de que la escala elegida no sea correcta solo por casualidad de rango."""
    if not isinstance(pack_voltage, (int, float)) or isinstance(pack_voltage, bool) or not cells:
        return None
    if pack_voltage == 0:
        return None
    cell_sum = sum(cells)
    return round(abs(cell_sum - pack_voltage) / abs(pack_voltage), 4)


def angle_wrap(rad):
    """Normaliza un angulo a [-pi, pi]."""
    return math.atan2(math.sin(rad), math.cos(rad))


def decide_keyframe_trigger(now, phase_changed, last_cloud_t, pos, last_cloud_pos,
                             imu_yaw, last_cloud_imu_yaw, dt_s, dpos_m, dyaw_deg):
    """FASE D1/A1 (pura, sin DDS): decide si toca un keyframe LiDAR completo.

    `pos` es la ULTIMA odometria conocida (puede venir de una iteracion anterior:
    ver FASE A1 en ottoguide_remote_recorder — latest_odom no se reinicia a None
    por iteracion, asi que un desplazamiento acumulado a lo largo de varias
    iteraciones sin muestra de odom nueva sigue pudiendo disparar "dpos").
    """
    if phase_changed:
        return "phase"
    if last_cloud_t == 0.0 or (now - last_cloud_t) >= dt_s:
        return "dt"
    if pos and last_cloud_pos and len(pos) >= 2 and None not in pos[:2] and None not in last_cloud_pos[:2]:
        if math.dist(pos[:2], last_cloud_pos[:2]) >= dpos_m:
            return "dpos"
    if imu_yaw is not None and last_cloud_imu_yaw is not None:
        dyaw = abs(angle_wrap(imu_yaw - last_cloud_imu_yaw)) * 180.0 / math.pi
        if dyaw >= dyaw_deg:
            return "dyaw"
    return None

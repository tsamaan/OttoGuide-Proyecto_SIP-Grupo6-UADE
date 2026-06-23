"""
Generador de telemetria simulada para el robot G1 (29 motores).
Reproduce el tipo de datos que en produccion vendrian del lowstate por DDS:
energia, motores (angulo/velocidad/torque/temperatura), IMU, fuerza en patas y bateria.
"""
import math
import random
import time

# Mapa de motores del G1 (indice -> nombre, grupo)
G1_JOINT_MAP = [
    ("L_Hip_Pitch", "Pierna Izquierda"), ("L_Hip_Roll", "Pierna Izquierda"),
    ("L_Hip_Yaw", "Pierna Izquierda"), ("L_Knee", "Pierna Izquierda"),
    ("L_Ankle_Pitch", "Pierna Izquierda"), ("L_Ankle_Roll", "Pierna Izquierda"),
    ("R_Hip_Pitch", "Pierna Derecha"), ("R_Hip_Roll", "Pierna Derecha"),
    ("R_Hip_Yaw", "Pierna Derecha"), ("R_Knee", "Pierna Derecha"),
    ("R_Ankle_Pitch", "Pierna Derecha"), ("R_Ankle_Roll", "Pierna Derecha"),
    ("Waist_Yaw", "Cintura"), ("Waist_Roll", "Cintura"), ("Waist_Pitch", "Cintura"),
    ("L_Shoulder_Pitch", "Brazo Izquierdo"), ("L_Shoulder_Roll", "Brazo Izquierdo"),
    ("L_Shoulder_Yaw", "Brazo Izquierdo"), ("L_Elbow", "Brazo Izquierdo"),
    ("L_Wrist_Roll", "Mano Izquierda"), ("L_Wrist_Pitch", "Mano Izquierda"),
    ("L_Wrist_Yaw", "Mano Izquierda"),
    ("R_Shoulder_Pitch", "Brazo Derecho"), ("R_Shoulder_Roll", "Brazo Derecho"),
    ("R_Shoulder_Yaw", "Brazo Derecho"), ("R_Elbow", "Brazo Derecho"),
    ("R_Wrist_Roll", "Mano Derecha"), ("R_Wrist_Pitch", "Mano Derecha"),
    ("R_Wrist_Yaw", "Mano Derecha"),
]
NUM_MOTORS = len(G1_JOINT_MAP)


class MockTelemetry:
    def __init__(self):
        self._start = time.time()
        # angulo base fijo por motor
        self._base = [random.uniform(-15, 15) for _ in range(NUM_MOTORS)]

    def frame(self) -> dict:
        elapsed = time.time() - self._start
        t = elapsed
        freq = 1.0
        motors = []
        for idx, (name, group) in enumerate(G1_JOINT_MAP):
            base = self._base[idx]
            phase = idx * (2 * math.pi / NUM_MOTORS)
            tw = 2 * math.pi * freq * t
            angle = base + 10 * math.sin(tw + phase)
            vel = 10 * 2 * math.pi * freq * math.cos(tw + phase)
            torque = 5 * math.sin(tw + phase) + random.uniform(-1, 1)

            # La rodilla izquierda (idx 3) oscila un poco mas caliente para mostrar
            # los colores de temperatura y el banner de aviso de vez en cuando.
            if idx == 3:
                temp = int(44 + 6 * math.sin(elapsed / 8.0) + random.uniform(-1, 1))
            else:
                temp = random.randint(30, 41)

            motors.append({
                "index": idx,
                "name": name,
                "group": group,
                "q_rad": round(math.radians(angle), 4),
                "q_deg": round(angle, 2),
                "dq": round(vel, 4),
                "ddq": 0.0,
                "tau_est": round(torque, 4),
                "temperature": temp,
            })

        v = round(27.5 + random.uniform(-0.3, 0.3), 2)
        a = round(3.5 + random.uniform(-0.5, 0.5), 2)

        return {
            "robot": "G1",
            "timestamp": time.time(),
            "power_v": v,
            "power_a": a,
            "motors": motors,
            "imu": {
                "quaternion": [1, 0, 0, 0],
                "gyroscope": [round(random.uniform(-0.05, 0.05), 4) for _ in range(3)],
                "accelerometer": [
                    round(random.uniform(-0.3, 0.3), 4),
                    round(random.uniform(-0.3, 0.3), 4),
                    round(9.8 + random.uniform(-0.05, 0.05), 4),
                ],
                "rpy_deg": [
                    round(random.uniform(-3, 3), 2),
                    round(random.uniform(-3, 3), 2),
                    round(random.uniform(-10, 10), 2),
                ],
            },
            "foot_force": [random.randint(15, 55) for _ in range(4)],
            "bms": {
                "soc": max(0, 75 - int(elapsed / 60)),
                "cycle": 20,
                "current": -3500,
                "status": 0,
                "mcu_ntc": [30, 31],
                "bq_ntc": [29, 30],
                "cell_vol": [
                    3520 + random.randint(-4, 4), 3518 + random.randint(-4, 4),
                    3525 + random.randint(-4, 4), 3530 + random.randint(-4, 4),
                    3522 + random.randint(-4, 4), 3519 + random.randint(-4, 4),
                ],
            },
        }


mock = MockTelemetry()

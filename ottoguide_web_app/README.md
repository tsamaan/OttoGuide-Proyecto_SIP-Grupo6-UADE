# OttoGuide — Panel de control y métricas

Monorepo con dos partes que corren en máquinas distintas:

- **`backend/`** → corre **dentro del robot** (Unitree G1-EDU), en **Docker**, puerto **8000**. Expone el control de los procesos (recorrido / charla / parada) y la telemetría del robot.
- **`frontend/`** → corre en una **notebook**, con **`npm run dev`**, puerto **3001**. Le pega al backend del robot por el **cable RJ45**.

```
robot (G1-EDU)                      notebook
┌───────────────────────┐  RJ45    ┌───────────────────────┐
│ backend (Docker:8000) │◄────────►│ frontend (Vite:3001)  │
│  FastAPI + telemetría │  HTTP/WS │  React + dashboard     │
└───────────────────────┘          └───────────────────────┘
```

El objetivo es **no tirar comandos por consola**: desde la web se inicia el recorrido, se inicia la charla (IA) y se termina la ejecución con botones, y se ven las métricas del robot en tiempo real.

---

## Flujo de uso

1. **En el robot**, levantar el backend una vez y que quede prendido siempre (ver abajo). Queda escuchando en el puerto 8000.
2. Conectar la **notebook al robot por RJ45** y configurar la IP de la notebook en la misma red del robot (`192.168.123.0/24`).
3. **En la notebook**, levantar el frontend con `npm run dev` (puerto 3001).
4. En el panel, desactivar **Modo simulación** y poner la URL del robot (ej. `http://192.168.123.164:8000`).
5. Usar los botones: **Iniciar recorrido**, **Iniciar charla**, **Terminar ejecución**.

> El panel arranca en **Modo simulación** (datos falsos), así se puede desarrollar y mostrar sin el robot.

---

## Backend (en el robot, Docker)

Requisitos: Docker + Docker Compose en el robot.

```bash
cd backend
docker compose up -d --build      # levanta el backend en el puerto 8000
docker compose logs -f            # ver logs
```

Para que **arranque solo al encender el robot**:
- El `docker-compose.yaml` ya usa `restart: always` (vuelve a levantar el contenedor al iniciar Docker y si se cae).
- Habilitar el daemon de Docker en el arranque del robot:
  ```bash
  sudo systemctl enable docker
  ```

Probar que responde:
```bash
curl http://localhost:8000/health        # {"status":"ok"}
```

### Endpoints (backend canónico — FastAPI :8000)

| Método | Ruta | Botón / uso |
|---|---|---|
| POST | `/tour/start` | Iniciar recorrido (orquestador: movimiento + recorrido) |
| POST | `/tour/pause` | Pausar recorrido |
| GET | `/content/script` | Obtener script conversacional activo |
| POST | `/content/script/reload` | Recargar contenido del script de IA |
| POST | `/emergency` | Terminar ejecución (`terminal_safe`; responde 200, 503 o 504) |
| GET | `/status` | Estado del sistema (`{mode, running, llm_enabled, conversation_state}`) |
| WS | `/ws/telemetry` | Telemetría en tiempo real (~10 Hz) |

> **Nota:** Los endpoints `/chat/start` y `GET /telemetry` (fallback HTTP) han sido descartados. La telemetría se obtiene exclusivamente por WebSocket. En modo real, `SILENT_REAL_FALLBACK = PROHIBITED`.

### Modo simulación del backend
Por defecto `MOCK_MODE=true`: el backend genera telemetría simulada y acepta los comandos (los registra), para probar todo el flujo sin sensores. Cambiar a `MOCK_MODE=false` en producción.

### Integración real con el robot
- **Control**: El `TourOrchestrator` del backend canónico maneja los efectos (lanzar `ottoguide-map`, `otto_pipeline`, etc.).
- **Telemetría**: El lector DDS (`unitree_sdk2py`) lee `rt/lowstate` y lo expone vía el WebSocket `/ws/telemetry`.
- El contenedor usa `network_mode: host` para acceso a DDS.

---

## Frontend (en la notebook)

Requisitos: Node.js 18+.

```bash
cd frontend
npm install
npm run dev        # http://localhost:3001
```

Configuración (opcional) en `frontend/.env` (copiar de `.env.example`):
```
VITE_ROBOT_BASE_URL=http://192.168.123.164:8000
VITE_MOCK_MODE=true
```
La URL del robot y el modo simulación también se cambian **desde la propia interfaz**.

### Qué muestra
- **Tarjetas:** Energía (V/A/W), Batería/BMS (SOC, corriente, NTC, ciclos, celdas), IMU (roll/pitch/yaw, aceleración, giroscopio), Fuerza en patas.
- **Tabla de motores:** ángulo, velocidad, torque y temperatura (con color: verde <40 °C, amarillo 40–60, rojo >60).
- **Gráficos en tiempo real** (se muestran/ocultan): ángulo por motor (con selector de grupo), temperatura, corriente, tensión, SOC y tensión de celdas.
- **Banner de alerta** de temperatura.
- **Botones de control:** Iniciar recorrido · Iniciar charla · Terminar ejecución, con estado del sistema (modo, estado del diálogo y si el LLM está habilitado).

---

## Estructura

```
ottoguide-panel/
├── backend/                 # corre en el robot (Docker, puerto 8000)
│   ├── docker-compose.yaml
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py
│       ├── config.py
│       ├── routers/         # control.py (botones) + telemetry.py (WS/GET)
│       ├── services/        # process_manager, robot_state, telemetry_source
│       └── mock/            # telemetría simulada
└── frontend/                # corre en la notebook (Vite, puerto 3001)
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── config.js        # URL del robot + endpoints (único lugar a tocar)
        ├── services/        # robotApi (HTTP) + telemetry (WS/polling)
        ├── mock/            # telemetría simulada del navegador
        ├── hooks/           # useTelemetry, useRobotStatus
        ├── data/            # mapas de motores (G1 / Go2)
        ├── components/       # tarjetas, tabla, gráficos, botones, header
        └── styles/theme.css
```

# Runbook: Web UI React (notebook) ↔ FastAPI (companion PC)

## 1. Proposito y alcance

Este runbook cubre exclusivamente la operacion del panel web React contra el backend
FastAPI ya integrado (CORS, WebSocket Origin, inicio de recorrido, estado y telemetria).

No cubre:

- Interaccion por voz / NLP (pendiente de Fase 2 de interaccion).
- Paneles de control adicionales no expuestos por el contrato HTTP actual (el contrato
  vigente es `/status`, `/tour/start`, `/tour/pause`, `/emergency`, `/content/script`,
  `/content/script/reload`, `WS /ws/telemetry`, `/dashboard`).
- Validacion HIL del robot. Este documento NO declara `HIL_VALIDATED` ni `ROBOT_READY`;
  describe unicamente la conectividad operador↔backend.

## 2. Topologia

```text
┌────────────────────────┐        HTTP :8000        ┌──────────────────────────┐
│ Notebook (operador)     │ ───────────────────────> │ Companion PC             │
│ React dev server :3001  │ <─────────────────────── │ FastAPI/uvicorn :8000    │
│                          │      WS /ws/telemetry    │ get_hardware_adapter()   │
└────────────────────────┘                            └──────────┬───────────────┘
                                                                   │ DDS / eth0
                                                                   ▼
                                                        Locomocion Unitree G1
                                                        192.168.123.161
```

- React (Vite dev server) corre en la **notebook**, puerto **3001**.
- FastAPI (uvicorn) corre en el **companion PC**, puerto **8000**.
- El companion PC habla con la locomocion Unitree G1 en `192.168.123.161` via DDS/eth0
  solo cuando `ROBOT_MODE=real`. Esta capa no se modifica en este runbook.

## 3. Configuracion de red (companion PC, RJ45)

Verificar antes de cualquier sesion:

```bash
ip addr show eth0
ip route show
ping -c 3 192.168.123.161
```

- La interfaz `eth0` del companion PC debe estar en la misma subred que la locomocion
  (`192.168.123.0/24`).
- No reasignar IPs sin evidencia fisica fuerte (ver
  `docs/Operaciones_HIL/RUNBOOK_OPERACIONES_HIL_OTTOGUIDE.md` seccion 3 para el estado de
  red vigente del robot).
- Si la notebook y el companion PC estan en redes distintas, confirmar que la notebook
  puede alcanzar el puerto 8000 del companion PC (`curl http://<companion-ip>:8000/status`
  fallara con 503 sin orquestador, pero confirma conectividad TCP/HTTP).

## 4. Variables de entorno — backend (companion PC)

Archivo: `codigo ottoguide/.env` (copiar desde `.env.example`). **El `.env.example` deja
`WEB_UI_ALLOWED_ORIGINS`, `WEB_UI_PUBLIC_URL` y `WEB_UI_ALLOW_MISSING_ORIGIN` vacios/false a
proposito (fail-closed): copiar el archivo sin editar estas variables NO produce una
allow-list utilizable en `ROBOT_MODE=real`.**

### 4.1 Configuracion mock/sim/demo (panel de pruebas, sin robot)

```bash
ROBOT_MODE=mock                # mock|sim|demo
API_HOST=0.0.0.0
API_PORT=8000

# --- Web UI React ---
WEB_UI_ALLOWED_ORIGINS=
WEB_UI_PUBLIC_URL=http://localhost:3001
WEB_UI_ALLOW_MISSING_ORIGIN=false
```

Con `WEB_UI_ALLOWED_ORIGINS` vacio, el runtime aplica automaticamente los origenes locales
efectivos (`http://localhost:3001`, `http://127.0.0.1:3001`). No es necesario editarla para
pruebas locales de panel; solo configurar `WEB_UI_PUBLIC_URL` si se quiere que `/dashboard`
redirija a React.

### 4.2 Configuracion real (HIL, robot fisico)

```bash
ROBOT_MODE=real
ROBOT_NETWORK_INTERFACE=eth0
API_HOST=0.0.0.0
API_PORT=8000

# --- Web UI React ---
WEB_UI_ALLOWED_ORIGINS=http://<ip-notebook>:3001
WEB_UI_PUBLIC_URL=http://<ip-notebook>:3001
WEB_UI_ALLOW_MISSING_ORIGIN=false
```

`WEB_UI_ALLOWED_ORIGINS` **debe configurarse explicitamente** con la IP real de la notebook
en la red del companion PC (ej. `http://192.168.123.101:3001`). Dejarla vacia o en `*`
bloquea el arranque del backend con
`WEB_UI_CONFIG_INVALID:WEB_UI_ALLOWED_ORIGINS_empty_in_real_mode` o
`WEB_UI_CONFIG_INVALID:wildcard_origin_prohibited_in_real_mode`.

### 4.3 Reglas obligatorias (ambos casos)

- `WEB_UI_PUBLIC_URL` es la URL a la que `/` y `/dashboard` redirigen. Sin configurar, el
  backend sirve el dashboard HTML legacy como fallback transicional.
- `WEB_UI_ALLOW_MISSING_ORIGIN` debe permanecer `false`. Solo se usa en pruebas
  controladas; nunca habilitarlo en una sesion con red real.
- Nunca usar wildcard `"*"` en `ROBOT_MODE=real`.

## 5. Variables de entorno — frontend (notebook)

Archivo: `ottoguide_web_app/frontend/.env` (copiar desde `.env.example`).

```bash
VITE_ROBOT_BASE_URL=http://192.168.123.164:8000   # IP del companion PC, puerto 8000
VITE_MOCK_MODE=true                                # true = datos simulados sin robot
```

- `VITE_ROBOT_BASE_URL` debe apuntar a la IP real del companion PC en la red en la que
  esta conectada la notebook, no a `localhost`, salvo que ambos procesos corran en la
  misma maquina.
- `VITE_MOCK_MODE=false` solo cuando el backend este corriendo y accesible; de lo
  contrario el panel mostrara errores de conexion.

## 6. Comandos de arranque

### 6.1 Backend (companion PC)

```bash
cd "codigo ottoguide"
cp .env.example .env   # si no existe; luego editar segun seccion 4
python main.py
```

Equivalente explicito con uvicorn (igual a lo que ejecuta `main.py`):

```bash
uvicorn main:create_app --factory --host 0.0.0.0 --port 8000
```

### 6.2 Frontend (notebook)

```bash
cd ottoguide_web_app/frontend
cp .env.example .env   # si no existe; luego editar segun seccion 5
npm ci
npm run dev
```

El servidor de desarrollo Vite expone el panel en `http://localhost:3001` (o
`http://<ip-notebook>:3001` si Vite esta configurado con `--host`).

## 7. Validacion de conectividad

### 7.1 `/status`

```bash
curl -s http://<companion-ip>:8000/status | python -m json.tool
```

- **200**: sistema inicializado; revisar `operational_ready` y `readiness_errors` en el
  body antes de continuar.
- **503**: `TourOrchestrator` no disponible (backend no termino de arrancar, o fallo el
  lifespan). Revisar logs del proceso `main.py`/`uvicorn` en el companion PC.

### 7.2 `/dashboard`

```bash
curl -sI http://<companion-ip>:8000/dashboard
```

- **307** con header `location`: redirige a `WEB_UI_PUBLIC_URL` (React es la interfaz
  principal). Confirmar que la URL en `location` es alcanzable desde la notebook.
- **200** con header `X-OttoGuide-Dashboard: legacy-fallback`: `WEB_UI_PUBLIC_URL` no esta
  configurado; se sirvio el dashboard HTML legacy.
- **404**: `WEB_UI_PUBLIC_URL` vacio y no existe `static/dashboard.html` en este checkout.

### 7.3 WebSocket `/ws/telemetry`

Desde el navegador (consola JS) o con una herramienta de WS:

```js
const ws = new WebSocket("ws://<companion-ip>:8000/ws/telemetry");
ws.onopen = () => console.log("conectado");
ws.onmessage = (e) => console.log("telemetria:", e.data);
ws.onclose = (e) => console.log("cerrado", e.code);
```

- Conexion aceptada y primer mensaje recibido (snapshot inicial del estado FSM): origen
  autorizado.
- Cierre inmediato con codigo **1008** (policy violation): el header `Origin` de la
  conexion no esta en `WEB_UI_ALLOWED_ORIGINS` (o la lista efectiva). Revisar que la
  notebook este accediendo al panel desde un origen incluido en la configuracion del
  companion PC (seccion 4).

## 8. Prueba de inicio de recorrido

```bash
curl -s -X POST http://<companion-ip>:8000/tour/start \
  -H "Content-Type: application/json" \
  -d '{
    "tour_id": "smoke-test",
    "waypoints": [
      {"x": 1.0, "y": 0.0, "yaw_rad": 0.0, "frame_id": "map"}
    ]
  }'
```

- **202 Accepted**: tour aceptado, transicion `idle -> navigating` confirmada por el
  orquestador.
- **409 Conflict**: la FSM rechazo la transicion (estado actual no permite iniciar tour).
- **503 Service Unavailable**: el sistema no esta listo (ver `readiness_errors` del body).

En `ROBOT_MODE=mock|sim|demo` este endpoint es seguro de usar repetidamente. En
`ROBOT_MODE=real` solo ejecutar con el entorno fisico despejado y bajo el protocolo HIL
vigente (`docs/Operaciones_HIL/HIL_TESTING_PROTOCOL.md`).

## 9. Prueba de emergencia desde el panel web

```bash
curl -s -X POST http://<companion-ip>:8000/emergency \
  -H "Content-Type: application/json" \
  -d '{"reason": "web_operator"}'
```

### Interpretacion de codigos HTTP

| HTTP | Significado |
|---|---|
| **200** | `emergency_stop()` confirmo `terminal_safe=True` (incluye `damp_succeeded=True`). |
| **503** | La secuencia de emergencia corrio pero **no** confirmo seguridad terminal (`terminal_safe=False`); revisar el campo `errors` del body. |
| **504** | Timeout (5s) esperando `emergency_stop()`. Tratar como emergencia no confirmada: verificar el robot fisicamente. |
| **500** | Excepcion no controlada en el endpoint. Tratar como emergencia no confirmada. |

**Critico**: el campo que confirma seguridad fisica es `terminal_safe` en el body de la
respuesta, **no** el campo `executed`. `executed=true` solo indica que la llamada se
realizo sin excepcion; no implica que el robot haya quedado en `damp()` seguro. Ante
cualquier respuesta que no sea HTTP 200 con `terminal_safe=true`, verificar el estado
fisico del robot antes de continuar la sesion.

## 10. Limitaciones del contrato actual

- El panel web no expone paneles de configuracion adicionales mas alla de los endpoints
  listados en la seccion 1; cualquier control no listado ahi no existe en el backend.
- La interaccion por voz (wake word, STT, TTS, NLP) no esta conectada al panel web; es
  alcance de la Fase 2 de interaccion, no de este runbook.
- Este runbook no valida HIL ni declara el robot listo para operacion real.

## 11. Procedimiento de cierre

1. Confirmar que no hay un tour activo (`GET /status` → `state` distinto de
   `navigating`/`interacting`) o ejecutar `/emergency` si es necesario.
2. Detener el frontend (`Ctrl+C` en la terminal de `npm run dev`).
3. Detener el backend (`Ctrl+C` en la terminal de `python main.py` / `uvicorn`); el
   `lifespan` ejecuta la secuencia de apagado HIL-safe (`EventBus -> FSM EMERGENCY ->
   MotionCommand(0) -> damp()`). La secuencia siempre se ejecuta (esta en el `finally` del
   lifespan), pero **ejecutarse no es lo mismo que tener exito**: cada paso interno puede
   fallar o hacer timeout sin que eso interrumpa el procedimiento (ver paso 4).
4. Revisar los logs y distinguir explicitamente dos cosas distintas:

   - **El procedimiento termino.** El log
     `[SHUTDOWN] === SECUENCIA HIL-SAFE COMPLETADA ===` confirma **unicamente** que la
     funcion `_run_shutdown_sequence()` llego al final de su ejecucion. **Por si solo NO
     confirma que `damp()` haya tenido exito ni que el robot este fisicamente seguro.**
   - **La seguridad terminal fue confirmada.** Esto requiere ver en los logs **alguna** de
     estas dos confirmaciones explicitas:
     - `ORCHESTRATOR_EMERGENCY_COMPLETED` (el `TourOrchestrator` confirmo
       `terminal_safe=True`, lo cual implica `damp_succeeded=True`), o
     - el log `[SHUTDOWN] STEP 4: damp() ejecutado correctamente.` (fallback directo de
       hardware cuando no hubo orquestador activo).

   Si en su lugar aparece `DIRECT_HARDWARE_FALLBACK_USED`, un `TIMEOUT en damp()`, o
   `Fallo CRITICO en damp()`, la seguridad terminal **no esta confirmada** aunque el log
   `SECUENCIA HIL-SAFE COMPLETADA` se haya emitido igual. Ante esto:

   1. Verificar el estado fisico del robot antes de alejarse o dar la sesion por cerrada.
   2. Si el robot sigue activo o en una postura no segura, activar **L1+A** en el mando
      fisico para forzar el corte de motores.
   3. No continuar la sesion ni reiniciar el backend hasta confirmar visualmente que el
      robot quedo en un estado seguro.

## 12. Troubleshooting

| Sintoma | Causa probable | Accion |
|---|---|---|
| El navegador reporta error CORS en consola al llamar `/status` desde React | El origen desde el que se sirve React no esta en `WEB_UI_ALLOWED_ORIGINS` efectivo | Agregar el origen exacto (protocolo+host+puerto) a `WEB_UI_ALLOWED_ORIGINS` en el `.env` del companion PC y reiniciar el backend |
| WebSocket se cierra inmediatamente con codigo 1008 | Header `Origin` de la conexion WS no autorizado | Mismo fix que CORS: ambos comparten `Settings.web_ui_allowed_origins_list` |
| Backend no arranca en `ROBOT_MODE=real`, log muestra `WEB_UI_CONFIG_INVALID:WEB_UI_ALLOWED_ORIGINS_empty_in_real_mode` | `WEB_UI_ALLOWED_ORIGINS` vacio en modo real (comportamiento esperado, fail-closed) | Establecer explicitamente la allow-list real antes de arrancar |
| Backend no arranca en `ROBOT_MODE=real`, log muestra `wildcard_origin_prohibited_in_real_mode` | `WEB_UI_ALLOWED_ORIGINS=*` en modo real (prohibido sin excepcion) | Reemplazar `*` por la lista explicita de origenes confiables |
| React no puede conectar al companion PC | IP incorrecta en `VITE_ROBOT_BASE_URL`, companion PC inalcanzable, o puerto 8000 cerrado/firewall | Verificar `ping`/`curl` desde la notebook al companion PC; revisar reglas de firewall en companion PC para el puerto 8000 |
| `/dashboard` devuelve 404 | `WEB_UI_PUBLIC_URL` vacio y no existe `static/dashboard.html` | Configurar `WEB_UI_PUBLIC_URL` apuntando a React, o restaurar el dashboard legacy si se requiere como fallback |
| Notebook y companion PC no se ven en red | Subredes distintas, RJ45 mal configurado, o IP estatica incorrecta | Verificar `ip addr show eth0` / `ipconfig` en ambas maquinas; confirmar que estan en la misma subred o que hay ruteo entre ellas |

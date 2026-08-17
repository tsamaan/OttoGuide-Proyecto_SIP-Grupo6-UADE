# OFFLINE-R3 — Flujo de tour mock completo habilitado explícitamente

## Problema detectado en OFFLINE-R1

`POST /tour/start` en `ROBOT_MODE=mock` era rechazado con `503` (`"navigation backend stub: autonomous tours disabled"`). El backend, el WebSocket de telemetría y el frontend ya estaban validados offline por separado, pero el flujo funcional completo de un tour (transición de FSM `idle → navigating`, pausa por interacción, cierre) nunca se había ejercitado de punta a punta sin robot.

## Diseño del interlock (ya existente, solo validado en este checkpoint)

El repositorio ya implementaba el interlock necesario antes de este checkpoint — no se modificó ningún archivo de código:

- `config/settings.py`: `NAVIGATION_ALLOW_STUB_TOURS: bool = False` (default cerrado).
- `main.py` (lifespan): expone `app.state.navigation_stub_tours_allowed = settings.NAVIGATION_ALLOW_STUB_TOURS`.
- `api/router.py::_resolve_readiness_errors`: bloquea `/tour/start` con `backend_resolved == "stub" and not stub_tours_allowed`; con el flag en `true` y backend `stub`, el gate de readiness queda limpio.
- Cobertura unitaria ya existente: `tests/unit/test_navigation_runtime_selection.py::test_stub_with_allow_flag_in_mock_permits` / `::test_stub_without_allow_flag_blocks`; `tests/integration/test_api_router_canonical.py` ya fija `navigation_stub_tours_allowed=True` en su fixture.

## Qué permite `NAVIGATION_ALLOW_STUB_TOURS=true`

Con `ROBOT_MODE` en `mock|sim|demo` y el backend de navegación resuelto en `stub`, habilita que `/tour/start` acepte el tour (`202`) y que el `TourOrchestrator` transicione `idle → navigating`, ejecute el loop de navegación contra `_MinimalNavStub` (que no simula desplazamiento real, pero tampoco aborta el tour ante sus resultados `False`) y cierre el tour normalmente (`finish_tour()` → `idle`). Habilita también, dentro de ese flujo, `POST /tour/pause` (pausa por interacción) y `POST /emergency`.

## Por qué no afecta `ROBOT_MODE=real`

- `_resolve_navigation_backend()` resuelve `auto` a `legacy` cuando `ROBOT_MODE=real`, nunca a `stub`.
- Solicitar `NAVIGATION_BACKEND=stub` explícito con `ROBOT_MODE=real` sigue lanzando `RuntimeError("NAVIGATION_STUB_FORBIDDEN_IN_REAL_MODE")`.
- El chequeo de readiness solo se activa cuando `backend_resolved == "stub"`; en modo real el backend nunca resuelve a `stub`, así que `NAVIGATION_ALLOW_STUB_TOURS=true` no tiene ningún efecto observable en real.

## Endpoints validados (offline, `ROBOT_MODE=mock`, sin robot, sin SSH)

`GET /status`, `POST /tour/start` (202, transición `idle→navigating` confirmada en `/status` inmediatamente después), `POST /tour/pause` (202, `navigating→interacting`), `POST /emergency` (200, `terminal_safe=true`), `WS /ws/telemetry` (snapshot inicial + broadcast de cada transición: `NAVIGATING → INTERACTING → NAVIGATING → EMERGENCY`).

## Resultados de tests

- Tests focalizados: `test_navigation_runtime_selection.py` (48), `test_api_router_canonical.py` (20), `test_tour_orchestrator.py` (17), `test_web_ui_cors_and_origin.py` (24) — todos en verde.
- Suite completa offline: 1256 passed / 120 skipped / 7 failed (6 por `piper-tts` no instalado, 1 por fuga de estado entre tests preexistente y no relacionada con navegación, reproducida solo en la suite completa y ausente en ejecución aislada). Cero fallos nuevos relacionados con navegación, router u orquestador.
- Frontend: `npm ci`/`test` (27/27)/`build` en verde; servido en `:3001` y consumiendo el backend mock real en `:8000` con CORS confirmado.

## Límites

Este checkpoint **no** valida Nav2 real, odometría/TF reales, ni el robot físico. `_MinimalNavStub` sigue sin simular desplazamiento (`navigate_to_waypoints`/`send_goal` retornan `False`); el tour se completa igual porque el orquestador no aborta ante ese resultado. El interlock habilita el *flujo* de tour para demos y desarrollo offline, no una simulación físicamente representativa de navegación.

## Próximo checkpoint recomendado

`OFFLINE-R2_DEMO_READINESS_AND_SCRIPT_ALIGNMENT` (ensayo de demo en navegador real con el flujo ya desbloqueado) o `NAV-R1_READ_ONLY_MAP_ODOM_TF_AUTONOMY_FEASIBILITY_AUDIT_NO_MOTION` para el gap de navegación autónoma real.

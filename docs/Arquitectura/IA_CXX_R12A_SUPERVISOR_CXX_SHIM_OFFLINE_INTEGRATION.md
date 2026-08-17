# IA-CXX-R12A — Integración offline: supervisor Python ↔ `otto_jsonl_shim` (C++)

## Objetivo

Validar que `JsonlInteractionWorkerSupervisor` (Python, control plane real) puede supervisar
el binario C++ real `otto_jsonl_shim` (IA-CXX-R11, dispatch loop mockeado) como child process,
completamente offline: sin robot, sin SSH, sin audio real, sin Unitree, sin
Whisper/Ollama/Piper reales.

Este checkpoint NO reemplaza `otto_pipeline.cpp`. Confirma que el rol de Python como plano de
control (`PYTHON_ROLE = supervisor_control_plane`) funciona end-to-end contra un binario C++
real, en lugar de solo contra dobles de prueba en memoria.

## Archivos modificados

- `codigo ottoguide/tests/integration/test_u3d_cxx_jsonl_shim_supervisor.py` (nuevo) — 4 tests
  de integración offline.
- `docs/Arquitectura/IA_CXX_R12A_SUPERVISOR_CXX_SHIM_OFFLINE_INTEGRATION.md` (este documento).

Ningún archivo de producción Python (`runtime_port.py`, `jsonl_worker_supervisor.py`,
`worker_supervisor.py`) fue modificado. Ningún archivo bajo `docs/legacy/**` fue tocado.

## Patrón reutilizado

Este test replica exactamente el patrón ya validado en producción por
`codigo ottoguide/tests/integration/test_u3c_cxx_loopback_worker_supervisor.py` (IA-CXX-R8/U3C),
que ya conecta el mismo supervisor con otro binario C++ real
(`otto_jsonl_loopback_worker`). Se reutilizan los mismos timeouts cortos y finitos, el mismo
uso de `pytest.mark.skipif` para saltar limpiamente si el binario no está compilado, y la
misma estructura de assertions basada en `next_event()`.

Única diferencia relevante: la variable de entorno que localiza el binario es
`OTTO_JSONL_SHIM_BIN` (en vez de `OTTOGUIDE_CXX_LOOPBACK_WORKER`), apuntando al binario
`otto_jsonl_shim` (IA-CXX-R11) en vez de `otto_jsonl_loopback_worker` (IA-CXX-R8).

## Comandos ejercitados

- `start` → `ready` con las 9 capabilities en `false` (shim mockeado, ninguna real).
- `health` → `command_accepted`, estado permanece `READY`.
- `activate` → secuencia completa: `command_accepted → wake_word_confirmed →
  capture_started → transcript_ready("hola otto") → response_ready("respuesta mock") →
  playback_started → playback_completed`; supervisor vuelve a `READY`.
- `close` → `command_accepted → closed`; supervisor llega a `CLOSED`.

## No ejercitado en este checkpoint (gap conocido, no bloqueante)

- `interaction_timeout` y el mapeo `ERR_SEMANTIC_REJECTED` (decisión de R11) no se ejercitan
  aquí — el shim mockeado no tiene lógica para producirlos de forma determinística sin
  entrada especial. Documentado como candidato para `OPTION_B` de un checkpoint futuro
  (`IA-CXX-R12` propuso esta opción explícitamente).
- `pause`/`resume`/`stop`/`emergency_stop` no se ejercitan en un test dedicado en R12A porque
  ya están cubiertos en el smoke test C++ standalone de R11
  (`shim_mock_protocol_smoke.cpp`) y no son necesarios para validar la integración
  supervisor↔proceso real, que es el objetivo específico de este checkpoint.

## Confirmación de alcance

- No se modificó `runtime_port.py`, `jsonl_worker_supervisor.py` ni `worker_supervisor.py`.
- No se modificó `otto_pipeline.cpp` ni ningún archivo bajo `docs/legacy/**`.
- No se usó robot, SSH, audio real, Unitree, ni modelos reales (Whisper/Ollama/Piper).
- No se publicó `/cmd_vel`, `/odom` ni `/tf`.
- El binario `otto_jsonl_shim` usado en la ejecución de estos tests fue compilado
  offline en un directorio de build aislado dentro de la evidencia del checkpoint, y no fue
  instalado ni dejado en el árbol del repositorio.

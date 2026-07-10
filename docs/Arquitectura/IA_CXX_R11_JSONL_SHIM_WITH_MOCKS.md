# IA-CXX-R11 — JSONL shim with mocks

## 1. Objetivo

Implementar la primera versión no-stub de `otto_jsonl_shim.cpp`: un dispatch loop C++ real que
lee comandos JSONL por stdin y emite eventos JSONL por stdout, con comportamiento
completamente mockeado (sin audio, sin red, sin modelos, sin Unitree), siguiendo el diseño de
`docs/Arquitectura/IA_CXX_R10_DETAILED_ADAPTER_DESIGN_OFFLINE_NO_CODE_NO_ROBOT.md`. Este
checkpoint valida el dispatch loop y el contrato JSONL contra mocks determinísticos — no
integra la lógica física real de `otto_pipeline.cpp`.

## 2. Archivos modificados

```
M  codigo ottoguide/src/interaction/cxx_runtime/src/otto_jsonl_shim.cpp
A  codigo ottoguide/src/interaction/cxx_runtime/tests/shim_mock_protocol_smoke.cpp
M  codigo ottoguide/src/interaction/cxx_runtime/CMakeLists.txt
A  docs/Arquitectura/IA_CXX_R11_JSONL_SHIM_WITH_MOCKS.md
```

`otto_jsonl_shim.cpp` deja de ser el stub dummy de R5 (que solo imprimía una línea a stderr) y
pasa a ser el dispatch loop mockeado descrito abajo. `CMakeLists.txt` se modificó únicamente
para: (a) declarar el nuevo target `shim_mock_protocol_smoke`, y (b) enlazar
`Threads::Threads` contra el target `otto_jsonl_shim` (ya existente, sin cambios de nombre),
porque la nueva implementación usa un hilo de heartbeat. Ningún otro target existente cambió.

## 3. Decisión de protocolo sobre rechazo semántico

Ver `IA_CXX_R11_PROTOCOL_DECISION.md` (evidencia de checkpoint). Resumen:
`SEMANTIC_REJECTION_MAPPING = failed` con `SEMANTIC_REJECTION_CODE = ERR_SEMANTIC_REJECTED`,
sin cambio de protocolo. No se modificó `runtime_port.py`.

## 4. Comandos soportados

Los 8 comandos de `WorkerCommandType`: `start`, `health`, `activate`, `pause`, `resume`,
`stop`, `emergency_stop`, `close`.

## 5. Eventos emitidos

`ready`, `heartbeat` (periódico, cada ~1s, vía hilo dedicado), `command_accepted`,
`wake_word_confirmed` (nuevo respecto a R8 — emitido al inicio de cada `activate`),
`capture_started`, `transcript_ready`, `response_ready`, `playback_started`,
`playback_completed`, `cancelled`, `stopped`, `closed`, `failed` (rutas de error de framing).
No se ejercitan en los smoke tests de este checkpoint: `interaction_timeout` (requeriría un
mock de timeout de larga duración, diferido a un checkpoint futuro).

## 6. Límites conocidos

- El parser de entrada (`ExtractStringField`) es deliberadamente mínimo, igual que en el
  worker loopback de R8 — no es un parser JSON general.
- `pause`/`resume` responden `command_accepted` sin ningún efecto adicional simulado (el
  diseño de R10 §13 identifica que introducir puntos de pausa seguros reales requiere
  decisiones adicionales, diferidas a un checkpoint posterior).
- El heartbeat usa un hilo con `std::condition_variable` para poder detenerse limpiamente sin
  esperar el intervalo completo; se detiene explícitamente en `close` y `emergency_stop`.
- No se ejercita el camino de `ERR_SEMANTIC_REJECTED` en los smoke tests (ver §3 y la
  decisión de protocolo).

## 7. No integración real

Este shim no incluye, invoca, ni enlaza contra `otto_pipeline.cpp`. No abre sockets, micrófono,
ni accede a red real. No invoca Whisper, Ollama, Piper, ni el SDK Unitree. No publica
`/cmd_vel`, `/odom` ni `/tf` — estos tópicos no tienen relación alguna con el dominio de este
shim.

## 8. No robot

Ninguna acción de este checkpoint accede al robot físico, usa SSH, ni requiere ningún hardware.
Toda ejecución (si autorizada) corre completamente offline con timeout estricto.

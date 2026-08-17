# IA-CXX-R8 — protocol-compliant C++ loopback worker

## 1. Objetivo

Implementar el primer worker C++ que habla el protocolo JSONL real declarado en
`codigo ottoguide/src/interaction/runtime_port.py` por stdin/stdout, como doble de prueba
offline (sin audio, sin red, sin modelos, sin Unitree), siguiendo la decisión de R7
(`NEXT_IMPLEMENTATION_STRATEGY = CXX_PROTOCOL_COMPLIANT_LOOPBACK_WORKER_FIRST`). Este worker
reemplaza el rol que hasta ahora solo cumplía `tests/support/u3a_loopback_worker.py` (Python),
proporcionando un análogo C++ directo, sin tocar `otto_pipeline.cpp` ni el runtime físico
final.

## 2. Archivos modificados

```
A  codigo ottoguide/src/interaction/cxx_runtime/src/otto_jsonl_loopback_worker.cpp
A  codigo ottoguide/src/interaction/cxx_runtime/tests/loopback_worker_protocol_smoke.cpp
A  codigo ottoguide/tests/integration/test_u3c_cxx_loopback_worker_supervisor.py
A  docs/Arquitectura/IA_CXX_R8_PROTOCOL_COMPLIANT_LOOPBACK_WORKER.md
M  codigo ottoguide/src/interaction/cxx_runtime/CMakeLists.txt
```

`CMakeLists.txt` fue modificado únicamente para declarar dos nuevos targets
(`otto_jsonl_loopback_worker`, `loopback_worker_protocol_smoke`); no se tocó ningún target
existente ni se introdujo ninguna dependencia nueva.

## 3. Comandos implementados

Los 8 comandos de `WorkerCommandType`: `start`, `health`, `activate`, `pause`, `resume`,
`stop`, `emergency_stop`, `close`.

## 4. Eventos emitidos

`ready`, `command_accepted`, `capture_started`, `transcript_ready`, `response_ready`,
`playback_started`, `playback_completed`, `cancelled`, `stopped`, `closed`, `failed`. El
evento `heartbeat` está implementado (`EmitHeartbeat`) pero no se emite en un loop periódico
propio en esta versión inicial — el worker es de un solo hilo, sin heartbeat asíncrono en
background, para mantener la implementación mínima verificable. Esto se documenta como gap
explícito en la sección 10.

## 5. Validación contra `runtime_port.py`

Todos los wire strings de comandos y eventos provienen directamente de
`otto_jsonl_protocol.hpp` (ya verificado byte a byte contra `runtime_port.py` en R5), sin
redefinir ningún literal nuevo en el archivo del worker. El envelope de cada evento emitido
contiene exactamente las 6 claves requeridas por `WorkerEventEnvelope`
(`protocol_version`, `message_id`, `interaction_id`, `event`, `sequence`,
`emitted_at_monotonic_s`, `payload`). `protocol_version` usa `kProtocolVersion` (1), igual que
`INTERACTION_PROTOCOL_VERSION`.

## 6. Validación contra `JsonlInteractionWorkerSupervisor`

`test_u3c_cxx_loopback_worker_supervisor.py` instancia
`JsonlInteractionWorkerSupervisor` sin modificarlo, apuntando su `argv` al binario C++
compilado (localizado vía la variable de entorno `OTTOGUIDE_CXX_LOOPBACK_WORKER`), y valida:
`start` → `ready`, `activate` → secuencia completa hasta `playback_completed`, `stop` →
`stopped`, `emergency_stop` → terminación limpia, `close` → estado `CLOSED`. El test hace skip
limpio si la variable de entorno no está definida o el binario no existe, sin fallo silencioso
ni bloqueo de la suite general.

## 7. Qué no se toca

- `otto_pipeline.cpp`: no incluido, no invocado, no enlazado.
- `docs/legacy/**`: sin modificaciones.
- `runtime_port.py`, `jsonl_worker_supervisor.py`, `worker_supervisor.py`: sin modificaciones;
  el worker C++ se adapta al contrato Python existente.
- `tests/support/u3a_loopback_worker.py`, `test_u3a_jsonl_worker_supervisor.py`: sin
  modificaciones; cobertura Python existente preservada intacta como referencia y regresión.

## 8. Resultados de build

g++ 15.2.0 (fallback, CMake no disponible en este entorno), `-std=c++17 -Wall -Wextra`. Ambos
binarios (`otto_jsonl_loopback_worker`, `loopback_worker_protocol_smoke`) compilaron con exit
code 0, sin warnings. Detalle completo en `IA_CXX_R8_CXX_BUILD_STDOUT.txt` /
`IA_CXX_R8_CXX_BUILD_STDERR.txt` / `IA_CXX_R8_CXX_BUILD_EXIT_CODE.txt` (evidencia externa al
repositorio).

## 9. Resultados de ejecución dummy y tests Python

Ejecución con timeout estricto de 3s: `loopback_worker_protocol_smoke` (exit 0, sin salida),
secuencia `start → emergency_stop` (exit 0, termina en `stopped`), secuencia
`start → activate → close` (exit 0, secuencia completa de interacción hasta `playback_completed`,
luego `closed`). Ninguna ejecución se acercó al timeout. Detalle en `IA_CXX_R8_CXX_EXECUTION_*`.

Tests Python offline: `test_u3c_cxx_loopback_worker_supervisor.py` (nuevo) 5/5 passed contra el
worker C++ real, vía `JsonlInteractionWorkerSupervisor` sin modificar. Regresión
`test_u3a_jsonl_worker_supervisor.py` (sin cambios) 106/106 passed contra el worker Python de
referencia. Un test del archivo nuevo (`stop` tras interacción completa) requirió una
corrección de expectativa tras su primer intento: el worker C++ completa `activate` de forma
síncrona antes de que el supervisor drene el primer evento, por lo que al momento de llamar
`stop()` el estado ya volvió a `READY` (comportamiento correcto y documentado del supervisor,
no un bug del worker ni del supervisor). Detalle en `IA_CXX_R8_TEST_SUMMARY.md`.

## 10. Gaps

- El heartbeat periódico no se emite automáticamente en background; el worker es
  single-threaded y solo reacciona a líneas de stdin. Un checkpoint futuro que necesite
  heartbeat real periódico (por ejemplo, para ejercitar `heartbeat_timeout_s` del supervisor)
  deberá añadir un hilo o mecanismo de temporización dedicado.
- El parser de JSON de entrada (`ExtractStringField`) es deliberadamente mínimo: extrae solo
  los campos string de nivel superior que el worker necesita (`command`, `message_id`,
  `interaction_id`), no es un parser JSON general ni valida el resto del envelope
  (`protocol_version`, `sequence`, `emitted_at_monotonic_s`, `payload`) recibido desde el
  supervisor. Esto es suficiente porque el supervisor Python ya es la fuente de verdad que
  genera envelopes válidos; un parser completo queda fuera de alcance de este checkpoint.
- No se implementó soporte para escenarios de error/adversariales (JSON malformado real,
  líneas oversized, secuencia fuera de orden) como sí los cubre
  `u3a_loopback_worker.py` vía sus parámetros de `scenario`. Este worker C++ solo cubre el
  camino feliz (`normal`).

## 11. Próximo checkpoint recomendado

`IA-CXX-R8B_PRE_PUSH_REVIEW_PROTOCOL_COMPLIANT_LOOPBACK_WORKER_NO_RUNTIME_NO_PUSH`.

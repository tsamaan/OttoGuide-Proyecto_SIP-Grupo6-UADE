# IA-CXX-R7 — plan: dispatch loop JSONL real vs. worker dummy C++ protocol-compliant

```
R7_PLANNING_ONLY = true
R7_CODE_CHANGES = false
R7_CXX_BUILD = false
R7_CXX_EXECUTION = false
R7_ROBOT_ACCESS = false
R7_BACKEND_RUNTIME = false
R7_FRONTEND_RUNTIME = false
NEXT_IMPLEMENTATION_STRATEGY = CXX_PROTOCOL_COMPLIANT_LOOPBACK_WORKER_FIRST
NEXT_CHECKPOINT = IA-CXX-R8_CREATE_CXX_JSONL_LOOPBACK_WORKER_AND_SUPERVISOR_INTEGRATION_TESTS_NO_ROBOT_NO_PUSH
CXX_PIPELINE_PRIMARY = true
PYTHON_ROLE = supervisor_control_plane
CXX_ROLE = physical_conversation_runtime
OTTO_PIPELINE_CPP_TOUCH = prohibited
DOCS_LEGACY_TOUCH = prohibited
```

## 1. Dictamen R7

Este checkpoint es exclusivamente de planificación. Compara dos caminos posibles para el
siguiente avance de código C++ real — implementar directamente un dispatch loop JSONL en
`otto_jsonl_shim.cpp`, o crear primero un worker C++ dummy protocol-compliant que hable el
protocolo real por stdin/stdout — y documenta por qué el segundo camino es el correcto en este
punto de la secuencia. No se crea, modifica ni ejecuta código C++ ni Python. No se compila. No
hay push. El único artefacto de este checkpoint es el presente documento.

## 2. Estado heredado R1-R6

- **R1**: decisión de arquitectura — `CXX_PIPELINE_PRIMARY = true`,
  `PYTHON_REIMPLEMENTATION_PRIMARY = false`, `PYTHON_ROLE = supervisor_control_plane`,
  `CXX_ROLE = physical_conversation_runtime`. `InteractionRuntimePort` (`runtime_port.py`) y
  `JsonlInteractionWorkerSupervisor` (`jsonl_worker_supervisor.py`) ya existían, completos, sin
  contraparte C++.
- **R2**: diseñó el layout no compilado del shim JSONL C++ bajo `docs/legacy/.../cpp/`
  (`otto_jsonl_protocol.hpp`, `otto_jsonl_shim.cpp`), skeleton documental intacto hasta hoy.
- **R3 (R3→R3F)**: estabilizó `JsonlInteractionWorkerSupervisor` (dos condiciones de carrera
  corregidas), sin tocar C++. Confirmó que `test_u3a_jsonl_worker_supervisor.py` +
  `tests/support/u3a_loopback_worker.py` ya validan el contrato completo del supervisor contra
  un worker de prueba Python — 106/106 tests.
- **R4 (R4→R4E-FAST)**: planificó la ubicación productiva
  (`codigo ottoguide/src/interaction/cxx_runtime/`) y los gates de build/test/safety.
- **R5 (R5→R5E-FAST)**: creó y compiló offline la primera estructura C++ productiva real:
  `include/otto_jsonl_protocol.hpp` (enums, wire-string mapping, verificado byte a byte contra
  `runtime_port.py`), `src/otto_jsonl_shim.cpp` (entrypoint dummy, sin I/O real),
  `tests/protocol_contract_smoke.cpp` (`static_assert` de paridad completa),
  `CMakeLists.txt` aislado, `README.md`. Promovido y alineado en canónico y mirror
  (`e20afc37e0dd2cddd1f593bd48f814035b031814`).
- **R6**: ejecutó por primera vez, de forma controlada, los dos binarios dummy compilados en
  R5. Validó únicamente ciclo de vida de proceso — build limpio, spawn, exit code 0 en ambos,
  stdout vacío en ambos, stderr del shim coincidiendo exactamente con la línea dummy
  documentada. No modificó el repositorio; no hubo commit.
- `otto_pipeline.cpp` permanece sin modificar en todo el ciclo, hash forense estable
  (`0d1cc4567387f4bc41e3705d95c16d80be2e61d76fe2ea99dbe8a9fa6a926bcf`), confirmado antes y
  después de este checkpoint.

## 3. Qué validó R6

- Que el toolchain (g++ 15.2.0, fallback sin CMake) compila ambos binarios de R5 sin
  warnings bajo `-Wall -Wextra`.
- Que el proceso `otto_jsonl_shim` arranca, termina limpio (exit code 0) y no cuelga bajo un
  timeout estricto de 3 segundos.
- Que la única salida del shim es la línea dummy documentada a `stderr`, sin efectos de lado,
  sin stdout, sin lectura de stdin.
- Que `otto_jsonl_protocol_smoke` compila y ejecuta sus `static_assert`/`assert` sin fallar,
  confirmando en tiempo de compilación y de ejecución la paridad de wire-strings ya verificada
  manualmente en R5.

## 4. Qué queda fuera de R6

- **No validó protocolo real**: el shim no lee comandos JSONL de stdin ni escribe eventos
  JSONL a stdout. R6 solo confirmó que el proceso arranca y termina — no que hable el
  protocolo.
- **No validó integración con el supervisor**: `JsonlInteractionWorkerSupervisor` nunca fue
  apuntado al binario C++. No hay evidencia de que el supervisor pueda siquiera completar su
  `startup_timeout_s` contra este binario, porque el shim nunca emite un evento `ready`.
- **No validó heartbeat real, `emergency_stop` real, ni ningún comando/evento de interacción**
  (`activate`, `pause`, `resume`, `stop`, `capture_started`, `transcript_ready`,
  `response_ready`, etc.).
- **No validó nada relacionado con audio, modelos, red, ni el SDK Unitree** — explícitamente
  fuera de alcance de R6 y de este documento.

## 5. Opciones de avance

**Opción A — Dispatch loop JSONL real directamente en `otto_jsonl_shim.cpp`.**
Implementar de una vez, en el shim ya existente, un loop real de lectura de stdin, parseo
JSON, validación de envelope, y escritura de eventos JSONL a stdout, apuntando directamente a
convertirlo en el runtime C++ final que eventualmente envuelva a `otto_pipeline.cpp`.

**Opción B — Worker C++ dummy protocol-compliant primero (loopback).**
Crear un binario C++ nuevo (o convertir el shim en uno) que hable el protocolo JSONL real por
stdin/stdout de forma completa pero con comportamiento simulado/loopback — sin audio, sin
modelos, sin Unitree — análogo en propósito a `tests/support/u3a_loopback_worker.py`
(Python), y validarlo primero de forma aislada y luego integrado con
`JsonlInteractionWorkerSupervisor` mediante tests offline, antes de acercarse a
`otto_pipeline.cpp`.

## 6. Comparación técnica

| Criterio | Opción A (dispatch loop real ya apuntando al pipeline) | Opción B (loopback worker dummy primero) |
|---|---|---|
| Riesgo de acoplar protocolo y audio/modelos en el mismo cambio | Alto — mezcla parsing/framing JSONL con la futura integración de `otto_pipeline.cpp` | Bajo — el protocolo se valida en aislamiento total, sin ninguna dependencia real |
| Cobertura de prueba disponible hoy | Ninguna — no existe ningún test C++ de framing/dispatch | Alta por analogía — `u3a_loopback_worker.py` ya demuestra qué comportamiento satisface al supervisor, sirviendo de referencia de comportamiento esperado |
| Resultado si algo falla | Falla combinada (protocolo + futura integración de audio), difícil de diagnosticar | Falla aislada de protocolo, con causa raíz clara (framing, timing, o lógica de eventos) |
| Alineación con gate de build 9.1 (R4) — paridad automatizada | Cumplido igual en ambas opciones (ya cumplido desde R5) | Cumplido igual |
| Alineación con gate de safety 11.2 (R4) — `emergency_stop` validado offline antes de HIL | Requiere que el propio pipeline ya esté parcialmente integrado para probarlo | Se puede validar `emergency_stop` en el loopback sin ningún riesgo de tocar audio real |
| Reusabilidad como fixture de test futuro | Baja — un shim ya acoplado a lógica real es más difícil de usar como doble de prueba | Alta — el mismo loopback worker sirve como fixture de integración C++↔Python de forma indefinida, igual que su análogo Python ya sirve hoy |
| Cambio incremental / revisable en checkpoints pequeños | Difícil de dividir sin dejar el shim en un estado a medio implementar y roto | Natural — leer un comando, emitir `command_accepted`, luego `ready`, etc., cada paso es verificable por separado |

## 7. Decisión recomendada

`NEXT_IMPLEMENTATION_STRATEGY = CXX_PROTOCOL_COMPLIANT_LOOPBACK_WORKER_FIRST` (Opción B).

El shim actual (R5/R6) no habla JSONL y no debe tratarse como un worker real. Integrarlo
directamente con `JsonlInteractionWorkerSupervisor` en su estado actual solo demostraría una
falla conocida: el supervisor espera un evento `ready` por stdout dentro de
`startup_timeout_s`, y el shim actual nunca lo emite — no valida nada nuevo, solo reproduce el
comportamiento ya documentado en R5/R6 (stdout vacío por diseño).

Antes de tocar el runtime físico, debe existir un worker C++ dummy que: lea comandos JSONL
desde stdin; emita eventos JSONL a stdout; respete `runtime_port.py` byte a byte (framing,
validación de envelope, partición proceso/interacción); no use audio; no use red; no use
modelos; no use Unitree; no toque `otto_pipeline.cpp`; y permita pruebas end-to-end con el
supervisor Python sin robot. Este worker es el análogo C++ directo de
`tests/support/u3a_loopback_worker.py`, cuyo comportamiento ya está probado como suficiente
para satisfacer al supervisor (106/106 tests en R3/R4).

## 8. Arquitectura objetivo de R8

```
┌──────────────────────────────┐     JSONL (stdin/stdout)      ┌───────────────────────────────────┐
│ Python control-plane           │ ──────────────────────────────▶│ C++ loopback worker (R8, nuevo)     │
│ JsonlInteractionWorkerSupervisor│                                │ codigo ottoguide/src/interaction/    │
│ (ya funcional, sin cambios)     │◀────────────────────────────── │ cxx_runtime/ (binario nuevo o        │
└──────────────────────────────┘        eventos JSONL             │ evolución de otto_jsonl_shim)        │
                                                                    │ Sin audio. Sin modelos. Sin Unitree. │
                                                                    │ Sin dependencia de otto_pipeline.cpp.│
                                                                    └───────────────────────────────────┘
```

El worker de R8 es un doble de prueba (test double) del lado C++, equivalente en propósito al
`u3a_loopback_worker.py` existente del lado Python, no una implementación parcial del runtime
físico final.

## 9. Alcance permitido para R8

- Implementar en C++ un dispatch loop real: lectura línea a línea de stdin, parseo JSON,
  validación de envelope (versión de protocolo, `message_id`, `interaction_id`, `sequence`,
  `emitted_at_monotonic_s`, payload), y escritura de eventos JSONL a stdout con flush
  explícito.
- Implementar respuestas simuladas/loopback para los 8 comandos (`start`, `health`,
  `activate`, `pause`, `resume`, `stop`, `emergency_stop`, `close`), análogas a las que ya
  produce `u3a_loopback_worker.py` (p.ej. `activate` → `command_accepted` →
  `capture_started` → `transcript_ready` → `response_ready` → `playback_started` →
  `playback_completed`, con contenido de payload simulado, no real).
- Implementar heartbeat periódico simulado tras `ready`.
- Implementar `emergency_stop` con transición a `stopped` y terminación limpia del proceso.
- Crear tests C++ de framing/protocolo dentro de `cxx_runtime/tests/` que no dependan de
  Python, red, robot ni de ninguna dependencia real.
- Crear (o extender) tests de integración Python que apunten `JsonlInteractionWorkerSupervisor`
  contra el binario C++ nuevo, ejecutados offline, análogos en estructura a
  `test_u3a_jsonl_worker_supervisor.py` pero usando el worker C++ como `argv` en lugar del
  worker Python.
- Ubicar todo el código nuevo bajo `codigo ottoguide/src/interaction/cxx_runtime/` (o
  `codigo ottoguide/tests/` para los tests de integración Python), nunca bajo `docs/`.

## 10. Alcance prohibido para R8

- No debe incluir, invocar, ni enlazar contra `otto_pipeline.cpp`.
- No debe abrir sockets, micrófono, ni acceder a red real.
- No debe invocar Whisper, Ollama, Piper, ni el SDK Unitree.
- No debe acceder al robot bajo ninguna circunstancia.
- No debe modificar `docs/legacy/**`, el `CMakeLists.txt` legacy, ni `otto_say.sh`.
- No debe modificar `runtime_port.py`, `jsonl_worker_supervisor.py`, ni `worker_supervisor.py`
  — el worker C++ debe adaptarse al contrato Python existente, no al revés.
- No debe requerir cambios en `test_u3a_jsonl_worker_supervisor.py` ni en
  `u3a_loopback_worker.py` — ambos permanecen como referencia/cobertura Python existente, no a
  duplicar ni modificar.
- No implica todavía ninguna decisión sobre cómo el worker C++ eventualmente envolverá o
  invocará a `otto_pipeline.cpp` — esa decisión queda para un checkpoint posterior dedicado.

## 11. Build gates

Heredados de IA-CXX-R4 §9, aplicables sin cambios a R8:

1. Paridad de protocolo verificada de forma automatizada (ya cumplido desde R5 vía
   `static_assert`; R8 debe extenderlo a la lógica de framing/serialización, no solo a los
   enums).
2. Aislamiento de build: el `CMakeLists.txt` de `cxx_runtime/` sigue sin depender del legacy.
3. Sin dependencias no autorizadas (Whisper/Ollama/Piper/Unitree) introducidas en el worker
   loopback.
4. Compilación solo en entorno de desarrollo explícitamente autorizado, nunca contra el robot.
5. Hash forense de `otto_pipeline.cpp` verificado inmediatamente antes de cualquier build de
   R8.

## 12. Execution gates

- Cualquier ejecución del worker C++ en R8 requiere autorización explícita separada, con el
  mismo patrón de confirmación usado en R6.
- Ejecución con timeout estricto, sin robot, sin red, sin audio.
- Primero pruebas de framing aisladas (sin supervisor Python); solo después, si esas pasan,
  pruebas integradas con `JsonlInteractionWorkerSupervisor`.
- Ninguna ejecución de R8 puede invocar `otto_pipeline.cpp` ni ningún binario fuera de
  `cxx_runtime/`.

## 13. Python supervisor integration gates

- `JsonlInteractionWorkerSupervisor` no debe modificarse para acomodar al worker C++ — si el
  worker C++ no satisface el contrato ya validado contra el worker Python, el error está en el
  worker C++, no en el supervisor.
- Los tests de integración Python↔C++ deben poder ejecutarse completamente offline (sin red,
  sin robot) y deben poder señalarse explícitamente como dependientes de un binario C++
  compilado (skip limpio si el binario no existe, sin fallo silencioso).
- La cobertura existente (`test_u3a_jsonl_worker_supervisor.py` contra el worker Python) debe
  seguir pasando sin cambios — R8 añade cobertura nueva, no reemplaza la existente.

## 14. Safety gates

Heredados de IA-CXX-R4 §11:

1. Fail-closed obligatorio: si en un checkpoint posterior el worker C++ detecta dependencias
   reales faltantes, debe fallar explícitamente (`failed` o `ready=false`), nunca simular una
   respuesta real como si fuera genuina.
2. `emergency_stop` debe validarse contra el worker loopback dummy de R8 antes de cualquier
   prueba HIL futura — este es precisamente el propósito de construir el loopback antes que el
   dispatch real.
3. Autorización HIL separada y explícita: nada en R7 ni en el R8 propuesto implica
   autorización para tocar el robot.
4. Reversibilidad: el worker loopback no reemplaza ninguna ruta existente; `otto_pipeline.cpp`
   permanece como único camino físico validado hasta una integración futura explícita.

## 15. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| El worker loopback C++ diverge del comportamiento ya validado del worker loopback Python, ocultando bugs de protocolo en vez de exponerlos | R8 debe comparar explícitamente su secuencia de eventos contra `u3a_loopback_worker.py` para los mismos escenarios, no solo contra `runtime_port.py` en abstracto |
| Se confunde el worker loopback de R8 con una implementación parcial del runtime físico final | Este documento y el `README.md`/reporte de R8 deben declarar explícitamente que el loopback es un doble de prueba, no una implementación parcial de `otto_pipeline.cpp` |
| El dispatch loop introduce manejo de errores/framing distinto al ya validado en `JsonlInteractionWorkerSupervisor` (líneas demasiado largas, JSON inválido, secuencia fuera de orden) | R8 debe usar como referencia los mismos escenarios ya cubiertos por `test_u3a_jsonl_worker_supervisor.py` (framing, UTF-8 inválido, líneas oversized, JSON malformado) antes de darse por completo |
| Se intenta saltar directamente a integrar `otto_pipeline.cpp` aprovechando que ya existe un dispatch loop funcional | Fuera de alcance explícito de R8 (§10); cualquier integración con `otto_pipeline.cpp` requiere su propio checkpoint dedicado con su propia autorización |

## 16. Criterios de aceptación

- Este documento existe bajo `docs/Arquitectura/` y no introduce código `.cpp`/`.hpp`/`.py`
  nuevo en ninguna ubicación.
- No se modificó ningún archivo bajo `codigo ottoguide/src/interaction/cxx_runtime/**`,
  `runtime_port.py`, `jsonl_worker_supervisor.py`, `worker_supervisor.py`,
  `codigo ottoguide/tests/**`, `docs/legacy/**`, `otto_pipeline.cpp`, `CMakeLists.txt` legacy,
  ni `otto_say.sh`.
- `otto_pipeline.cpp` mantiene su hash forense sin cambios.
- La decisión `NEXT_IMPLEMENTATION_STRATEGY = CXX_PROTOCOL_COMPLIANT_LOOPBACK_WORKER_FIRST`
  queda registrada explícitamente junto con su justificación técnica.
- El alcance permitido/prohibido de R8 queda definido con precisión suficiente para que ese
  checkpoint pueda auto-verificarse contra este documento.

## 17. Plan de checkpoints futuros

- **R7** (este checkpoint): planificación, sin código nuevo, sin build, sin ejecución, sin
  robot, con un único commit local documental.
- **R7B**: pre-push review de este documento de planificación (sin runtime, sin push).
- **R7C–R7F**: staging a mirror, análisis read-only, promoción canónica, verificación final de
  alineación — mismo patrón de gates ya usado en los ciclos R1, R3, R4 y R5.
- **R8**: `IA-CXX-R8_CREATE_CXX_JSONL_LOOPBACK_WORKER_AND_SUPERVISOR_INTEGRATION_TESTS_NO_ROBOT_NO_PUSH`
  — implementación real del worker loopback C++ protocol-compliant descrito en §8-§10, con
  tests de framing aislados y tests de integración offline con
  `JsonlInteractionWorkerSupervisor`, compile-only o con ejecución dummy controlada según su
  propio prompt autocontenido.
- **Posterior a R8** (sin numerar aún): decisión explícita, en un checkpoint dedicado, sobre
  cómo y cuándo el runtime C++ eventualmente envuelve o invoca a `otto_pipeline.cpp`, seguida
  eventualmente de validación HIL con el robot real bajo autorización separada.

## 18. Resultado esperado

```
RESULT = OTTOGUIDE_IA_CXX_R7_JSONL_LOOPBACK_WORKER_PLAN_COMMIT_READY_NO_PUSH
```

Un documento de planificación completo, sin código funcional nuevo, sin build, sin ejecución y
sin push, que resuelve explícitamente la disyuntiva entre implementar un dispatch loop real
directamente o construir primero un worker loopback C++ protocol-compliant, decidiéndose por
esta última opción con su justificación técnica completa, listo para su propio ciclo de
revisión pre-push/staging/promoción (R7B en adelante) siguiendo el mismo patrón de gates ya
validado en los ciclos IA-CXX-R1, R3, R4 y R5.

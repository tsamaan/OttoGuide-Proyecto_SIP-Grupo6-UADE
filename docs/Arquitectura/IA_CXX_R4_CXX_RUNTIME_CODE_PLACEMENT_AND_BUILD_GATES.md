# IA-CXX-R4 — CXX runtime code placement and build gates

```
DOCS_RUNTIME_CODE = prohibited
CODIGO_OTTOGUIDE_RUNTIME_CODE = required
CXX_PIPELINE_PRIMARY = true
PYTHON_REIMPLEMENTATION_PRIMARY = false
PYTHON_ROLE = supervisor_control_plane
CXX_ROLE = physical_conversation_runtime
AUDIO_PRIMARY_PATH = CXX_UDP_AUDIO_LOOP
R4_CXX_BUILD = false
R4_CXX_EXECUTION = false
R4_ROBOT_ACCESS = false
R4_FILE_MOVES = false
R4_RUNTIME_CODE_CREATION = false
NEXT_CHECKPOINT = IA-CXX-R4B_PRE_PUSH_REVIEW_CXX_RUNTIME_CODE_PLACEMENT_PLAN_NO_RUNTIME_NO_PUSH
```

## 1. Dictamen R4

Este checkpoint es exclusivamente de planificación arquitectónica. Define dónde debe vivir el
runtime C++ productivo una vez que deje de ser un skeleton documental, qué gates de build/test/
safety deben superarse antes de compilarlo o ejecutarlo, y cómo se ordenan los checkpoints
futuros hasta llegar a una validación HIL con el robot físico. No se crea código C++ funcional,
no se mueven archivos, no se compila, no se ejecuta nada, y no hay push. El único artefacto de
este checkpoint es el presente documento.

Nota de renumeración: el diseño de IA-CXX-R2 (§25) usó informalmente la etiqueta "R4" para
referirse a un futuro checkpoint "compile-only offline". Ese contenido corresponde en la
secuencia real de checkpoints a **IA-CXX-R5** (ver §12), no al IA-CXX-R4 aquí ejecutado, que es
puramente de planificación de ubicación y gates. Este documento reemplaza esa referencia
informal con la secuencia definitiva R4→R5→R6→R7.

## 2. Estado heredado

- **IA-CXX-R1**: decisión de arquitectura cerrada — `CXX_PIPELINE_PRIMARY = true`,
  `PYTHON_REIMPLEMENTATION_PRIMARY = false`. Confirmó que `InteractionRuntimePort`
  (`runtime_port.py`) y `JsonlInteractionWorkerSupervisor` (`jsonl_worker_supervisor.py`) ya
  existen, completos, del lado Python, sin usar hasta que exista una contraparte C++.
- **IA-CXX-R2**: diseñó el layout del shim JSONL C++ (`otto_jsonl_protocol.hpp`,
  `otto_jsonl_shim.cpp`, `README_JSONL_SHIM.md`) como skeleton no compilado/no ejecutado bajo
  `docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/`. Identificó 10 funciones
  "puras" en `otto_pipeline.cpp` como candidatas de extracción futura. Decidió que C++
  conserva la captura/reproducción de audio vía UDP (Opción 1); Python nunca transporta audio.
- **IA-CXX-R3 (R3→R3F)**: corrigió dos condiciones de carrera preexistentes en
  `JsonlInteractionWorkerSupervisor` (capa Python control-plane), sin tocar C++. Commit
  `86857d9c111f8ce116c2a50934b491cf03f7a6f0` alineado bit-a-bit entre canónico y mirror (tree
  hash `29c45ddc07ff4ed07d9e5baa1382d097ed393305`). Confirmó que la suite
  `test_u3a_jsonl_worker_supervisor.py` (106 tests, con fake-worker
  `u3a_loopback_worker.py`) ya satisface la validación de protocolo contra un worker de
  prueba — cobertura existente, no a recrear.
- `otto_pipeline.cpp` permanece sin modificar en todo el ciclo, hash forense estable
  (`0d1cc4567387f4bc41e3705d95c16d80be2e61d76fe2ea99dbe8a9fa6a926bcf`).

## 3. Política de ubicación

- `docs/` contiene exclusivamente documentación, arquitectura, evidencia y artefactos
  skeleton no operativos (no compilables, no testeables, no ejecutables como parte del
  proyecto real).
- `codigo ottoguide/` contiene todo el código funcional, testeable o ejecutable del proyecto,
  tanto Python como, en el futuro, C++.
- El skeleton C++ creado en R2 bajo `docs/legacy/...` sigue siendo válido únicamente como
  artefacto de diseño — nunca debe compilarse ni ejecutarse desde esa ubicación.
- En el momento en que el shim C++ pase a ser compilable, testeable o funcional de cualquier
  forma, su código fuente debe vivir (migrado o recreado) bajo `codigo ottoguide/`, nunca bajo
  `docs/`.
- Esta política ya fue aplicada de forma consistente en R3: el fix del supervisor JSONL vive
  enteramente bajo `codigo ottoguide/src/interaction/`, no bajo `docs/`.

## 4. Mapa actual de artefactos

| Artefacto | Ubicación actual | Estado | Tipo |
|---|---|---|---|
| Pipeline físico histórico | `docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/otto_pipeline.cpp` | Validado en robot, no modificado desde su importación | C++ funcional legacy, fuera de `codigo ottoguide/` por decisión histórica de archivo, no de código nuevo |
| Build legacy | `docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/CMakeLists.txt` | Sin modificar | Build config legacy |
| Script de audio legacy | `docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/scripts/otto_say.sh` | Sin modificar | Script legacy |
| Skeleton JSONL C++ (R2) | `docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/otto_jsonl_protocol.hpp`, `otto_jsonl_shim.cpp`, `README_JSONL_SHIM.md` | No compilado, no ejecutado, stubs con TODO | Skeleton documental, no operativo |
| Supervisor Python (control-plane) | `codigo ottoguide/src/interaction/jsonl_worker_supervisor.py`, `runtime_port.py`, `worker_supervisor.py` | Funcional, estabilizado en R3, 106/106 tests | Código funcional Python |
| Fallback HIL Python legacy | `codigo ottoguide/src/interaction/conversation_manager.py`, `audio_bridge.py`, `stt_whisper_client.py`, `tts_unitree_client.py`, `wake_word_detector.py` | Preexistente, no tocado por el ciclo IA-CXX | Fallback, no ruta primaria |
| Tests/fake-worker de protocolo | `codigo ottoguide/tests/integration/test_u3a_jsonl_worker_supervisor.py`, `codigo ottoguide/tests/support/u3a_loopback_worker.py` | Estable, 106/106 | Código funcional Python (test) |
| Runtime C++ productivo | **No existe todavía** | — | Objeto de este documento (§5) |

## 5. Ubicación productiva propuesta

Propuesta de arquitectura únicamente — **ningún archivo se crea ni se mueve en R4**:

```
codigo ottoguide/src/interaction/cxx_runtime/
codigo ottoguide/src/interaction/cxx_runtime/include/
codigo ottoguide/src/interaction/cxx_runtime/src/
codigo ottoguide/src/interaction/cxx_runtime/tests/
codigo ottoguide/src/interaction/cxx_runtime/CMakeLists.txt
```

Justificación de la ubicación:

- Es hermano directo de `jsonl_worker_supervisor.py`/`runtime_port.py` dentro de
  `codigo ottoguide/src/interaction/`, reflejando que ambos lados (Python control-plane, C++
  runtime) pertenecen al mismo subsistema de interacción, no a módulos separados.
- Un `CMakeLists.txt` propio y aislado dentro de `cxx_runtime/` evita cualquier interferencia
  con el `CMakeLists.txt` legacy bajo `docs/legacy/...`, que permanece intacto.
- `include/`/`src/` separan cabeceras declarativas (como `otto_jsonl_protocol.hpp`, que R2 ya
  diseñó sin I/O) de la implementación con efectos de lado, facilitando que tests de protocolo
  puedan incluir solo las cabeceras sin arrastrar dependencias de proceso.
- `tests/` interno permite tests de protocolo en C++ (o bindings) sin mezclarlos con
  `codigo ottoguide/tests/integration/`, que hoy es exclusivamente Python.

No implica que la estructura final deba ser idéntica — queda sujeta a validación en R4B y en
el checkpoint que efectivamente cree los primeros archivos (ver §12).

## 6. Arquitectura objetivo

```
┌─────────────────────────────┐        JSONL over stdin/stdout        ┌──────────────────────────────┐
│  Python control-plane        │ ─────────────────────────────────────▶│  C++ runtime (cxx_runtime/)   │
│  codigo ottoguide/src/        │                                       │  codigo ottoguide/src/         │
│  interaction/                 │◀───────────────────────────────────── │  interaction/cxx_runtime/      │
│  jsonl_worker_supervisor.py   │        eventos JSONL                  │  (futuro shim compilado)       │
└─────────────────────────────┘                                        └───────────┬──────────────────┘
                                                                                      │ envuelve, no reemplaza
                                                                                      ▼
                                                                        ┌──────────────────────────────┐
                                                                        │  Pipeline físico histórico     │
                                                                        │  docs/legacy/.../otto_pipeline.cpp │
                                                                        │  (validado en robot, intacto)  │
                                                                        └──────────────────────────────┘
```

El runtime C++ productivo en `cxx_runtime/` no reemplaza a `otto_pipeline.cpp` — lo envuelve
o lo invoca (según decisión de un checkpoint posterior de integración), preservando el camino
de audio ya validado físicamente (Opción 1 de R2: C++ conserva UDP/audio).

## 7. Qué se permite migrar

En un checkpoint futuro dedicado (no en R4):

- El **contenido de diseño** de `otto_jsonl_protocol.hpp` (constantes, enums, mapeo de wire
  strings) puede recrearse como código real bajo `cxx_runtime/include/`, validado línea por
  línea contra `runtime_port.py` antes de considerarse completo.
- El **esqueleto de dispatch** de `otto_jsonl_shim.cpp` puede recrearse bajo
  `cxx_runtime/src/`, reemplazando los stubs `TODO` por implementación real, de forma
  incremental y con tests de protocolo acompañando cada comando/evento implementado.
- Un `CMakeLists.txt` nuevo y aislado bajo `cxx_runtime/`, sin tocar el `CMakeLists.txt`
  legacy.

## 8. Qué no se debe tocar todavía

- `otto_pipeline.cpp`: no se modifica sin un checkpoint específico dedicado a esa decisión
  (extracción de funciones puras, integración con el shim, etc.).
- `CMakeLists.txt` legacy bajo `docs/legacy/.../cpp/`: no se modifica; el build del runtime
  productivo usa su propio `CMakeLists.txt` aislado en `cxx_runtime/`.
- `otto_say.sh`: no se modifica.
- El fallback HIL Python (`conversation_manager.py` y módulos asociados): no se extiende ni se
  usa como base del runtime C++.
- Los archivos skeleton bajo `docs/legacy/.../cpp/otto_jsonl_*`: permanecen como artefacto
  documental; no se eliminan ni se mueven en R4 (una migración futura los recreará bajo
  `codigo ottoguide/`, no los moverá literalmente, para preservar la evidencia histórica del
  diseño R2 en `docs/`).

## 9. Build gates

Antes de que cualquier checkpoint futuro compile código C++ real bajo `cxx_runtime/`:

1. **Paridad de protocolo**: los wire strings de comandos/eventos en el código C++ real deben
   coincidir byte a byte con `WorkerCommandType`/`WorkerEventType` de `runtime_port.py`,
   verificado de forma automatizada (no solo revisión manual).
2. **Aislamiento de build**: el `CMakeLists.txt` de `cxx_runtime/` debe poder configurarse y
   compilarse sin depender del `CMakeLists.txt` legacy ni de artefactos bajo `docs/`.
3. **Sin dependencias no autorizadas**: ninguna dependencia de Whisper/Ollama/Piper/Unitree
   SDK puede introducirse en el shim sin una decisión explícita de checkpoint separada — el
   shim inicial debe poder compilar y correr sus tests de protocolo sin esas dependencias.
4. **Entorno explícito**: la compilación solo puede ejecutarse en un entorno de desarrollo
   explícitamente autorizado para build (nunca contra el robot físico ni como parte de un
   checkpoint que también solicite acceso a robot).
5. **Hash forense previo**: `otto_pipeline.cpp` debe verificarse con hash forense inmediatamente
   antes de cualquier build, para confirmar que el checkpoint de build no lo tocó por error.

## 10. Test gates

Antes de que cualquier checkpoint futuro ejecute un binario C++ real (incluso en modo dummy/smoke):

1. **Cobertura de protocolo existente reconocida**: `test_u3a_jsonl_worker_supervisor.py` +
   `u3a_loopback_worker.py` ya validan el contrato del lado Python contra un worker de
   prueba — un checkpoint de build/test C++ debe documentar cómo su propia suite se relaciona
   con esa cobertura existente, no duplicarla.
2. **Tests de protocolo C++ aislados**: cualquier test nuevo en `cxx_runtime/tests/` debe
   poder ejecutarse sin robot, sin micrófono, sin red, sin Whisper/Ollama/Piper reales.
3. **Comparación cruzada opcional**: si se extraen funciones "puras" de `otto_pipeline.cpp`
   (§16 del diseño R2) a una librería compartida, sus outputs deben compararse explícitamente
   contra el comportamiento del pipeline original antes de considerarse equivalentes.
4. **0 fallos como condición de avance**: ningún checkpoint de test puede avanzar al
   siguiente si deja tests fallando, siguiendo el mismo patrón estricto ya aplicado en el
   ciclo R3 (bloqueo literal ante fallos, sin excepciones de conveniencia).

## 11. Safety gates

Antes de cualquier acceso al robot físico:

1. **Fail-closed obligatorio**: si el shim detecta que Whisper, el modelo, Ollama, Piper o el
   SDK Unitree no están disponibles, debe fallar el arranque explícitamente (evento `failed` o
   `ready=false`), nunca degradar a una respuesta simulada — regla ya fijada en R1/R2.
2. **Emergency stop verificado offline primero**: el comportamiento de `emergency_stop` (
   detener audio, abortar captura, transición a estado seguro) debe validarse contra un
   binario dummy/smoke test antes de cualquier prueba HIL.
3. **Autorización HIL separada y explícita**: ningún checkpoint de build, test o smoke test
   implica autorización para tocar el robot — el checkpoint HIL (R7 en este plan) requiere su
   propio prompt autocontenido con confirmación explícita del usuario, igual que los pushes
   canónico/mirror del ciclo R3.
4. **Reversibilidad**: cualquier cambio de comportamiento del shim respecto al pipeline
   original validado en robot debe ser reversible (posibilidad de volver a
   `otto_pipeline.cpp` sin el shim) hasta que el shim tenga su propia validación HIL exitosa.

## 12. Plan de checkpoints futuros

- **R4** (este checkpoint): planificación de ubicación y gates, sin código C++ nuevo, sin
  build, sin ejecución, sin robot.
- **R4B**: pre-push review de este documento de planificación (sin runtime, sin push).
- **R4C–R4F**: staging a mirror, análisis read-only, promoción canónica, verificación final de
  alineación — mismo patrón de gates ya usado en los ciclos R1 y R3.
- **R5**: recreación real (no simple movimiento) del contenido de diseño de
  `otto_jsonl_protocol.hpp`/`otto_jsonl_shim.cpp` bajo `codigo ottoguide/src/interaction/cxx_runtime/`,
  compile-only offline, en un entorno con el SDK disponible pero sin robot conectado, sin
  ejecución del binario resultante.
- **R6**: smoke test con binario dummy — ejecución controlada sin robot, validando ciclo de
  vida del proceso (spawn, heartbeat, terminate, emergency_stop) sin dependencias reales de
  Whisper/Ollama/Piper/Unitree.
- **R7**: validación HIL con robot real, exclusivamente bajo autorización explícita y
  separada del resto del ciclo, con su propio prompt autocontenido y confirmación del usuario.

Esta secuencia reemplaza la mención informal de "R4" en el §25 de
`IA_CXX_R2_CXX_JSONL_SHIM_DESIGN.md` (que hoy correspondería a R5 en esta numeración
definitiva).

## 13. Criterios de aceptación

- Este documento existe bajo `docs/Arquitectura/` y no introduce código `.cpp`/`.hpp`/`.py`/
  `.sh`/`CMakeLists.txt` nuevo en ninguna ubicación.
- No se movió ni se modificó ningún archivo existente fuera de este documento nuevo.
- `otto_pipeline.cpp`, `CMakeLists.txt` legacy y `otto_say.sh` mantienen su hash/contenido sin
  cambios.
- Ningún archivo bajo `codigo ottoguide/src/**`, `codigo ottoguide/tests/**`,
  `codigo ottoguide/api/**`, `codigo ottoguide/main.py` ni `ottoguide_web_app/**` fue tocado.
- La política de ubicación (`docs/` = documentación, `codigo ottoguide/` = código funcional)
  queda reafirmada y detallada para el caso específico del runtime C++.

## 14. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| La ubicación propuesta (`cxx_runtime/`) resulta inadecuada una vez que se intente compilar realmente | R4B/R5 pueden ajustar la estructura antes de crear código real; nada en R4 es definitivo, es propuesta sujeta a validación |
| Confusión entre la numeración informal de R2 ("R4" = compile-only) y este R4 (planificación) | Resuelta explícitamente en §1 y §12: la secuencia definitiva es R4(plan)→R5(compile-only)→R6(smoke)→R7(HIL) |
| Un futuro checkpoint compila accidentalmente desde `docs/legacy/...` en vez de recrear bajo `codigo ottoguide/` | Gate de build §9.2 exige aislamiento explícito del `CMakeLists.txt` de `cxx_runtime/` respecto al legacy |
| Se introduce una dependencia real (Whisper/Ollama/Piper/Unitree) antes de tener gates de test que la cubran | Gate de build §9.3 y gate de test §10.2 bloquean esa introducción sin decisión explícita de checkpoint |
| Se pierde trazabilidad del diseño R2 si el skeleton documental se elimina al migrar | §8 fija explícitamente que el skeleton bajo `docs/legacy/...` no se mueve ni se borra; se recrea, no se traslada |

## 15. Resultado esperado

```
RESULT = OTTOGUIDE_IA_CXX_R4_CXX_RUNTIME_CODE_PLACEMENT_PLAN_COMMIT_READY_NO_PUSH
```

Un documento de planificación completo, sin código funcional nuevo, sin movimientos de
archivos, sin build, sin ejecución y sin push, listo para su propio ciclo de revisión
pre-push/staging/promoción (R4B en adelante) siguiendo el mismo patrón de gates ya validado en
los ciclos IA-CXX-R1 y IA-CXX-R3.

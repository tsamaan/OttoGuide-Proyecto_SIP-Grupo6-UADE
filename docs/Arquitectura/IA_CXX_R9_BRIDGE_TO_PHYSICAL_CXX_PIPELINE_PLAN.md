# IA-CXX-R9 — Bridge to physical C++ pipeline plan

## 1. Dictamen

Este documento es puramente de planificación técnica offline. No implementa código, no
modifica `otto_pipeline.cpp` ni ningún archivo bajo `docs/legacy/**`, no compila, no ejecuta,
no toca robot. Define cómo, en checkpoints futuros y bajo sus propios gates y confirmaciones
explícitas, se podría conectar el plano de control Python (`JsonlInteractionWorkerSupervisor`)
con el pipeline C++ físico ya probado (`otto_pipeline.cpp`), sin reescribirlo en Python y sin
degradarlo a implementación secundaria.

## 2. Estado actual confirmado

- Canónico y mirror alineados en `33d7038d69440ce9dbe227a191b6d270248a5ef4` (IA-CXX-R8D,
  verificado independientemente en este checkpoint vía `git ls-remote` propio).
- Ciclo IA-CXX-R8 cerrado: worker C++ loopback protocol-compliant (test double) implementado,
  validado contra `JsonlInteractionWorkerSupervisor` real (5/5 tests), sin regresión en la
  suite Python existente (106/106).
- `otto_pipeline.cpp` con hash forense estable
  (`0d1cc4567387f4bc41e3705d95c16d80be2e61d76fe2ea99dbe8a9fa6a926bcf`) desde su importación,
  reverificado en este checkpoint.
- `otto_jsonl_shim.cpp` sigue siendo el stub vacío original de R5 (solo imprime una línea a
  stderr y retorna 0); ningún dispatch loop real fue implementado todavía en ningún archivo.

## 3. Principio CXX-first

```text
CXX_PIPELINE_PRIMARY = true
PYTHON_REIMPLEMENTATION_PRIMARY = false
PYTHON_ROLE = supervisor_control_plane
CXX_ROLE = physical_conversation_runtime
```

`otto_pipeline.cpp` es un **activo histórico funcional**: ya fue validado físicamente en el
robot (Unitree G1 EDU) con Whisper STT, Ollama LLM y Piper TTS reales. El objetivo de cualquier
bridge futuro es **envolverlo**, no reemplazarlo. El worker C++ loopback de R8 es un **test
double** que valida el contrato de protocolo, no una alternativa al runtime físico.

## 4. Contrato Python existente

`codigo ottoguide/src/interaction/runtime_port.py` (stdlib-only, sin efectos de lado) define:

- `INTERACTION_PROTOCOL_VERSION = 1`.
- 8 comandos (`WorkerCommandType`): `start`, `health`, `activate`, `pause`, `resume`, `stop`,
  `emergency_stop`, `close`.
- 14 eventos (`WorkerEventType`): `ready`, `heartbeat`, `command_accepted`,
  `wake_word_confirmed`, `capture_started`, `transcript_ready`, `response_ready`,
  `playback_started`, `playback_completed`, `interaction_timeout`, `cancelled`, `failed`,
  `stopped`, `closed`.
- Envelope validado estrictamente: `protocol_version`, `message_id`, `interaction_id`,
  `sequence`, `emitted_at_monotonic_s`, `payload`, más `command`/`event`.

`codigo ottoguide/src/interaction/jsonl_worker_supervisor.py`
(`JsonlInteractionWorkerSupervisor`) spawnea exactamente un proceso hijo, trata `stdout` como
protocolo JSONL exclusivo y `stderr` como tail de logs no-protocolo, y aplica una máquina de
estados estricta (`NOT_STARTED → STARTING → READY → ACTIVE/PAUSED → ... → CLOSED`, más
`FAILED`/`EMERGENCY`) con timeouts configurables de arranque, heartbeat, escritura y cierre.

Este contrato es la fuente de verdad; cualquier worker (Python o C++) debe adaptarse a él, no
al revés.

## 5. Worker C++ loopback validado en R8

`otto_jsonl_loopback_worker.cpp` demuestra que un proceso C++ puede hablar el protocolo JSONL
completo por stdin/stdout y ser supervisado exitosamente por
`JsonlInteractionWorkerSupervisor` sin modificar ese supervisor. Es de un solo hilo, procesa
cada comando de forma síncrona, y **simula** capture/transcript/response/playback con datos
fijos (`"hola"`, `"respuesta"`) — no hay audio, STT, LLM ni TTS reales. Su valor es probar el
mecanismo de transporte y framing, no la lógica de conversación.

## 6. Capacidades actuales de `otto_pipeline.cpp`

Proceso standalone monolítico y bloqueante (879 líneas), ya funcional en el robot:

- Captura de audio por UDP multicast (`capture_thread`, socket dedicado).
- VAD/RMS propio (`tomar_utterance`, `calcular_rms`, umbral configurable).
- STT in-process con Whisper (`whisper_full`, modelo GPU `ggml-large-v3-turbo.bin`), con
  filtros de alucinación y validación semántica en español (`es_alucinacion`,
  `es_texto_valido`, `es_consulta_coherente`).
- LLM vía Ollama, HTTP crudo sobre socket TCP local (`ollama_query`, puerto 11434, parsing
  manual de la respuesta JSON, sin librería HTTP).
- TTS vía Piper invocado con `system()` (archivos temporales en `/tmp`, pipeline con `ffmpeg`).
- Reproducción física por chunks vía `unitree::robot::g1::AudioClient::PlayStream`/`PlayStop`.
- Máquina de estados interna propia (`HIBERNACION → ESCUCHANDO → PROCESANDO → ESCUCHANDO`),
  wake word ("hola otto" y variantes), detección de despedida, timeout de inactividad (30s).
- Configuración totalmente hardcodeada por macros: rutas de modelo/voz específicas del
  filesystem del robot, IP/puerto multicast, IP local, umbrales RMS.

## 7. Gap entre loopback y pipeline físico

| Aspecto | Loopback worker (R8) | `otto_pipeline.cpp` |
|---|---|---|
| Protocolo JSONL stdin/stdout | Sí, completo | No — ninguno |
| Canal de comandos | stdin (líneas JSONL) | Ninguno (bucle interno autónomo) |
| Canal de eventos | stdout (líneas JSONL) | Logs humanos con color ANSI a stdout/stderr |
| `interaction_id`/`message_id`/`sequence` | Sí | No existen en el código |
| Captura de audio | Simulada (sin audio real) | UDP multicast real |
| STT | Simulado (`"hola"` fijo) | Whisper real, GPU |
| LLM | Simulado (`"respuesta"` fija) | Ollama real, HTTP |
| TTS/playback | Simulado (evento inmediato) | Piper + AudioClient real |
| Control de pause/resume | Command handler trivial | No existe (bucle continuo, sin pausa) |
| Emergency stop | Cierra proceso limpiamente | No existe ningún mecanismo de parada externa |
| Configuración | N/A (sin config real) | Hardcodeada por macros de compilación |

El worker de R8 prueba que el *transporte* funciona; `otto_pipeline.cpp` prueba que la
*conversación física* funciona. Ningún archivo hoy conecta ambos.

## 8. Diseño objetivo del bridge futuro

Un adapter/shim C++ que:

1. Se ejecute como el único proceso hijo que el supervisor Python spawnea (mismo modelo de
   transporte que R8: un proceso, stdin/stdout JSONL, stderr = logs).
2. Traduzca comandos JSONL entrantes (`start`, `activate`, `pause`, `resume`, `stop`,
   `emergency_stop`, `close`, `health`) a control sobre una instancia embebida (o refactorizada
   como librería) de la lógica de `otto_pipeline.cpp`, sin reescribir su lógica de audio/STT/
   LLM/TTS en Python.
3. Traduzca las transiciones internas del pipeline físico (wake word detectada, utterance
   capturada, respuesta lista, reproducción iniciada/terminada) a los eventos JSONL
   correspondientes (`wake_word_confirmed`, `capture_started`, `transcript_ready`,
   `response_ready`, `playback_started`, `playback_completed`) hacia stdout.
4. Preserve el hash forense de `otto_pipeline.cpp` en el primer paso — el adapter debe **leer y
   envolver**, no modificar el archivo original, hasta que un checkpoint futuro explícitamente
   autorizado decida refactorizarlo en una librería enlazable.

## 9. Adapter/shim propuesto por etapas

- **Etapa 1 (futura, no en R9):** extraer la lógica de `otto_pipeline.cpp` en funciones/clases
  reutilizables sin cambiar su comportamiento (refactor mecánico, mismo hash de comportamiento
  verificado por comparación funcional, no por hash de archivo — el hash de archivo
  necesariamente cambiará si se toca el archivo, lo cual requiere su propia autorización
  explícita separada).
- **Etapa 2:** implementar el dispatch loop real en `otto_jsonl_shim.cpp` (hoy un stub),
  reutilizando `otto_jsonl_protocol.hpp` ya validado, siguiendo el mismo patrón de framing que
  el loopback worker de R8.
- **Etapa 3:** conectar el dispatch loop con la lógica extraída del pipeline, primero en modo
  "compile-only" (sin ejecución), luego con ejecución local sin hardware (mocks de
  AudioClient/Whisper/Ollama/Piper), y solo al final con hardware real bajo gates HIL
  explícitos.
- **Etapa 4:** verificación HIL en el robot físico, exclusivamente bajo autorización de Nivel D
  separada (no acelerable, según política vigente en `AGENTS.md`).

Ninguna de estas etapas se ejecuta en R9.

## 10. Archivos a crear en checkpoint futuro

```text
codigo ottoguide/src/interaction/cxx_runtime/src/otto_pipeline_adapter.cpp   (o similar)
codigo ottoguide/src/interaction/cxx_runtime/include/otto_pipeline_adapter.hpp
codigo ottoguide/src/interaction/cxx_runtime/src/otto_jsonl_shim.cpp         (implementación real, reemplazando el stub)
docs/Arquitectura/IA_CXX_R10_*.md (según corresponda al checkpoint de implementación)
```

Ningún archivo de este apartado se crea en R9.

## 11. Archivos que no deben tocarse todavía

```text
docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/otto_pipeline.cpp
docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/CMakeLists.txt
docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/scripts/otto_say.sh
docs/legacy/**
codigo ottoguide/src/interaction/runtime_port.py
codigo ottoguide/src/interaction/jsonl_worker_supervisor.py
codigo ottoguide/src/interaction/worker_supervisor.py
codigo ottoguide/tests/support/u3a_loopback_worker.py
codigo ottoguide/src/interaction/cxx_runtime/src/otto_jsonl_loopback_worker.cpp
```

## 12. Secuencia recomendada R10/R11/R12

- **R10 (propuesto):** diseño detallado del adapter (Nivel A, documentación con lectura C++
  read-only, análoga a este checkpoint), incluyendo el mapeo evento-por-evento entre estados
  internos del pipeline y `WorkerEventType`, sin escribir código de adapter todavía.
- **R11 (propuesto):** implementación compile-only del dispatch loop real en
  `otto_jsonl_shim.cpp` contra mocks (sin Whisper/Ollama/Piper/Unitree reales), siguiendo el
  mismo patrón de gates de confirmación explícita por fase usado en R8 (código, build,
  ejecución, tests, commit).
- **R12 (propuesto):** integración incremental con componentes reales uno a la vez (primero
  Whisper offline con audio pregrabado, luego Ollama local, luego Piper, luego Unitree
  AudioClient), cada uno como su propio checkpoint con su propio gate, culminando en HIL
  Nivel D separado y explícitamente no acelerable.

## 13. Riesgos

- **Riesgo de reescritura accidental:** la tentación de "portar" la lógica de
  `otto_pipeline.cpp` a Python en vez de envolverla en C++ degradaría la arquitectura CXX-first.
  Mitigado por reafirmar en cada checkpoint futuro `CXX_PIPELINE_PRIMARY = true`.
- **Riesgo de acoplar el adapter al hardware demasiado pronto:** implementar el dispatch loop
  directamente contra AudioClient/Whisper reales sin antes validarlo contra mocks dificultaría
  el diagnóstico de fallos de protocolo vs. fallos de hardware.
- **Riesgo de romper el pipeline físico ya probado:** cualquier refactor de
  `otto_pipeline.cpp` (Etapa 1) es la operación de mayor riesgo de toda la secuencia — requiere
  su propio checkpoint, su propia autorización explícita, y verificación funcional exhaustiva
  antes de considerar el archivo modificado como equivalente al original.
- **Riesgo de mapeo incorrecto de emergency_stop:** el protocolo espera que `emergency_stop`
  produzca una parada de proceso limpia; `otto_pipeline.cpp` no tiene hoy ningún mecanismo de
  parada externa — el adapter deberá introducir un punto de interrupción seguro sin invocar
  movimiento ni control de actuadores.
- **Riesgo de mezclar HIL con offline:** compilar/ejecutar contra el robot físico antes de
  agotar la validación offline violaría la política de niveles A–D ya vigente en `AGENTS.md`.

## 14. Mitigaciones

- Cada etapa (9) tiene su propio checkpoint futuro con su propio conjunto de gates y
  confirmaciones literales explícitas, sin heredar autorizaciones de checkpoints anteriores
  (patrón ya validado en toda la secuencia R6→R8D).
- El refactor de `otto_pipeline.cpp` (si se decide) se trata como Nivel C/D separado, con
  verificación de equivalencia funcional (no solo de hash) documentada explícitamente antes de
  aceptarlo.
- Mocks de componentes de hardware/modelo se introducen antes que las integraciones reales,
  replicando el patrón ya exitoso de R7→R8 (loopback antes que dispatch loop real).
- `emergency_stop` se implementa primero contra mocks, con pruebas explícitas de que no invoca
  ningún control de movimiento ni actuador antes de considerar su integración con
  `otto_pipeline.cpp` real.

## 15. Gates antes de build

```text
- Diseño del adapter documentado y revisado (checkpoint tipo R10).
- Confirmación de que ningún target existente de CMakeLists.txt fue modificado sin
  autorización explícita separada.
- Confirmación de que no se introdujeron dependencias de Whisper/Ollama/Piper/Unitree SDK sin
  decisión explícita de checkpoint.
- Hash forense de otto_pipeline.cpp verificado antes y después (si el archivo no fue tocado,
  debe permanecer idéntico).
```

## 16. Gates antes de ejecución local

```text
- Build compile-only ya validado con exit code 0, sin warnings.
- Ejecución exclusivamente contra mocks (sin Whisper/Ollama/Piper/Unitree reales).
- Timeout estricto en toda ejecución (patrón ya usado en R6/R8: 3s).
- Confirmación explícita literal separada para la fase de ejecución, no heredada de la fase de
  build.
```

## 17. Gates antes de robot compile-only

```text
- Toda la validación offline (build + ejecución contra mocks + tests Python) debe estar 100%
  verde antes de siquiera considerar compilar en un entorno con el SDK de Unitree disponible.
- Ningún binario resultante se ejecuta contra el robot en esta fase — solo se verifica que
  compila en un entorno con el SDK real presente.
- Clasificación Nivel C explícita, con sus propias confirmaciones literales.
```

## 18. Gates antes de HIL/robot físico

```text
- Nivel D explícito, no acelerable (ninguna variante "-FAST" permitida, según AGENTS.md
  vigente).
- Autorización HIL separada e independiente de cualquier autorización de código/build/
  ejecución previa.
- Presencia y supervisión humana directa confirmada antes de cualquier movimiento o audio real
  en el robot.
- Plan de emergency_stop verificado exhaustivamente contra mocks antes de considerarlo
  habilitado contra hardware real.
```

## 19. Criterios de aceptación

Para que un futuro checkpoint de implementación (R10+) se considere exitoso, deberá demostrar:

1. El adapter/shim habla el protocolo JSONL exactamente igual que el loopback worker de R8
   (mismos wire strings, mismo framing, misma validación de envelope).
2. `otto_pipeline.cpp` permanece sin modificar, o si se modifica, el cambio está explícitamente
   autorizado y verificado funcionalmente equivalente, con su propio hash forense documentado.
3. Ningún comando/evento del protocolo se reimplementa en Python — Python solo orquesta,
   nunca reemplaza la lógica de conversación C++.
4. `emergency_stop` produce una parada de proceso limpia y verificable sin movimiento físico
   antes de habilitarse contra hardware real.
5. Todas las integraciones de hardware/modelo real pasan primero por una fase equivalente
   validada contra mocks.

## 20. Próximo checkpoint recomendado

`IA-CXX-R9B_PRE_PUSH_REVIEW_BRIDGE_PLAN_NO_RUNTIME_NO_PUSH` — revisión pre-push de este
documento antes de cualquier mirror stage, sin modificar archivos, sin compilar, sin ejecutar,
sin robot, sin push.

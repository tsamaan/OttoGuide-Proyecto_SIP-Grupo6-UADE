# IA-CXX-R2 — Diseño del shim/wrapper C++ JSONL

```
CXX_PIPELINE_PRIMARY = true
PYTHON_REIMPLEMENTATION_PRIMARY = false
R2_RUNTIME_EXECUTION = false
R2_CXX_BUILD = false
R2_CXX_EXECUTION = false
OTTO_PIPELINE_CPP_MODIFIED = false
AUDIO_PRIMARY_PATH = CXX_UDP_AUDIO_LOOP
NEXT_CHECKPOINT = IA-CXX-R2B_PRE_PUSH_REVIEW_CXX_JSONL_SHIM_NO_RUNTIME_NO_PUSH
```

## 1. Resumen ejecutivo

Este documento diseña el layout concreto del shim/wrapper C++ (`otto_jsonl_shim.cpp` +
`otto_jsonl_protocol.hpp`) que hablará el protocolo JSONL ya definido en
`runtime_port.py`/`jsonl_worker_supervisor.py`, sin modificar ni reemplazar
`otto_pipeline.cpp`. El shim es un proceso C++ nuevo y separado: el pipeline validado en
robot sigue siendo la única implementación de STT/LLM/TTS/audio físico. R2 entrega diseño +
skeleton no compilado/no ejecutado; la extracción real de funciones puras hacia una librería
compartida y la integración de build quedan para checkpoints posteriores (R3 en adelante).

## 2. Estado base heredado de IA-CXX-R1

- Canónico y mirror alineados en `review/orchestrator-unification @
  306eca9eeb442ae17959ab3c133de956d7f4f675` (verificado en IA-CXX-R1F, tree hash
  `93cd1bdd097cc1f45308e805c54ff9e25cc0b4ad` idéntico en ambos, re-verificado al inicio de
  este checkpoint).
- Ciclo documental IA-CXX-R1 cerrado: decisión `CXX_PIPELINE_PRIMARY = true`,
  `PYTHON_REIMPLEMENTATION_PRIMARY = false` publicada sin ambigüedad en ambos repos.
- `otto_pipeline.cpp` con hash forense `0d1cc4567387f4bc41e3705d95c16d80be2e61d76fe2ea99dbe8a9fa6a926bcf`,
  confirmado idéntico en este checkpoint antes de crear cualquier archivo nuevo.
- Opción B (shim/wrapper separado) ya era la decisión recomendada en IA-CXX-R1 §16; R2
  concreta esa decisión en un layout de archivos y un contrato de protocolo específico.

## 3. Decisiones no negociables

- El pipeline C++ (`otto_pipeline.cpp`) sigue siendo la única implementación de captura de
  audio, wake word, VAD, STT (Whisper), LLM (Ollama) y TTS/playback (Piper + `AudioClient`)
  con validación física en robot.
- Python/FastAPI no reimplementa ninguna de esas capacidades como ruta primaria. El
  `ConversationManager`/`AudioHardwareBridge`/`WhisperSTTClient` en
  `codigo ottoguide/src/interaction/` (auditados en este checkpoint, ver §4) permanecen como
  el fallback HIL local ya existente cuando `interaction_runtime is None` — R2 no los toca,
  no los extiende, y no los convierte en ruta primaria.
- El shim JSONL es un adaptador de protocolo alrededor del pipeline C++, no una
  reimplementación de su lógica de audio/modelo.
- `otto_pipeline.cpp`, `CMakeLists.txt` y `otto_say.sh` no se modifican en R2.
- No se compila ni se ejecuta nada en R2 (ni el pipeline original, ni el shim nuevo).

## 4. Qué queda fuera de alcance en R2

- Extracción real de funciones desde `otto_pipeline.cpp` a un header/librería compartida
  (solo se identifican candidatas, §16).
- Modificación de `CMakeLists.txt` para integrar el shim al build (queda para R4
  compile-only offline).
- Cualquier compilación, ejecución, acceso a robot, micrófono, Whisper, Ollama o Piper.
- Resolución definitiva de la Opción de audio 2 (Python inyecta PCM) — se documenta como
  alternativa futura, no se implementa.
- Nota adicional sobre código Python existente: la auditoría de este checkpoint encontró que
  `codigo ottoguide/src/interaction/` ya contiene un pipeline de conversación local en Python
  (`conversation_manager.py`, `audio_bridge.py`, `stt_whisper_client.py`,
  `tts_unitree_client.py`, `wake_word_detector.py`) que usa `pyttsx3`/`speech_recognition`/
  Whisper HTTP/Ollama/Piper como implementación HIL alternativa, invocada por
  `tour_orchestrator.py` cuando `interaction_runtime is None`. Este módulo **ya existía antes
  de IA-CXX-R1** y no fue creado por este ciclo. R2 no lo modifica, no lo elimina, y no lo usa
  como base para el shim — se documenta aquí únicamente para que quede explícito que no es
  la ruta primaria y que el shim JSONL (conectado a `otto_pipeline.cpp`) es el camino que a
  futuro debe volver ese fallback innecesario, no al revés.

## 5. Contrato JSONL existente

Definido íntegramente en `codigo ottoguide/src/interaction/runtime_port.py` (649 líneas,
stdlib-only, sin efectos secundarios). El shim debe hablar este contrato exactamente como
está — R2 no propone cambios al protocolo.

- `INTERACTION_PROTOCOL_VERSION = 1` (constante obligatoria en todo envelope).
- Envelope de comando: `WorkerCommandEnvelope` (protocol_version, message_id, interaction_id,
  command, sequence, emitted_at_monotonic_s, payload).
- Envelope de evento: `WorkerEventEnvelope` (protocol_version, message_id, interaction_id,
  event, sequence, emitted_at_monotonic_s, payload).
- Límites de payload: profundidad máx. 8, strings máx. 4096 chars, contenedores máx. 256
  ítems, tamaño serializado máx. 32768 bytes (`MAX_PAYLOAD_*` en `runtime_port.py`).
- Identificadores: ASCII, regex `^[A-Za-z0-9._:-]+$`, máx. 80 caracteres
  (`MAX_IDENTIFIER_LENGTH`).

## 6. Comandos requeridos

De `WorkerCommandType` (`runtime_port.py:102-110`):

| Comando | interaction_id | Clase |
|---|---|---|
| `start` | debe ser `None` | proceso |
| `health` | debe ser `None` | proceso |
| `activate` | requerido | interacción |
| `pause` | requerido | interacción |
| `resume` | requerido | interacción |
| `stop` | requerido | interacción |
| `emergency_stop` | debe ser `None` | proceso |
| `close` | debe ser `None` | proceso |

El shim debe rechazar (evento `failed`) cualquier comando con `interaction_id` que no respete
esta partición — la validación ya existe en `_validate_command_interaction_id`
(`runtime_port.py:317-321`) del lado Python; el shim debe implementar la contraparte
equivalente en C++ para no depender únicamente de la validación del supervisor.

## 7. Eventos requeridos

De `WorkerEventType` (`runtime_port.py:113-127`):

| Evento | interaction_id | Clase |
|---|---|---|
| `ready` | `None` | proceso |
| `heartbeat` | `None` | proceso |
| `wake_word_confirmed` | `None` | proceso |
| `stopped` | `None` | proceso |
| `closed` | `None` | proceso |
| `capture_started` | requerido | interacción |
| `transcript_ready` | requerido | interacción |
| `response_ready` | requerido | interacción |
| `playback_started` | requerido | interacción |
| `playback_completed` | requerido | interacción |
| `interaction_timeout` | requerido | interacción |
| `cancelled` | requerido | interacción |
| `command_accepted` | flexible | ambos (requiere payload `command` + `message_id`) |
| `failed` | flexible | ambos (requiere payload `code` + `message`, ambos acotados) |

## 8. Envelopes y correlación

- `message_id`: identificador único por mensaje, generado por el emisor (Python para
  comandos, shim para eventos).
- `interaction_id`: correlaciona una interacción concreta; `None` para comandos/eventos de
  proceso, obligatorio para comandos/eventos de interacción.
- `sequence`: entero no negativo, estrictamente creciente por el lado que lo emite (el shim
  debe mantener su propio contador monótono de secuencia de eventos, independiente del
  contador de comandos entrante).
- `emitted_at_monotonic_s`: float finito no negativo, timestamp monotónico del emisor (no
  reloj de pared) — el shim debe usar `std::chrono::steady_clock`, análogo al reloj
  monotónico que ya usa `otto_pipeline.cpp` internamente para medir latencia de Whisper
  (`otto_pipeline.cpp:629-634`).

## 9. Política stdout/stderr

- `stdout` es exclusivamente protocolo JSONL: una línea, un evento, sin mezclar logs humanos
  (regla ya declarada en IA-CXX-R1 §6/§20, reafirmada aquí como vinculante para R2).
- `stderr` es exclusivamente para logs humanos, drenados por
  `JsonlInteractionWorkerSupervisor` como `stderr_tail_lines`/`stderr_tail_max_chars` sin
  interpretarlos como protocolo.
- Contraste explícito con `otto_pipeline.cpp`: su `main()` actual mezcla el indicador visual
  ANSI (`print_indicador`, `\r` in-place) y logs (`[MIC]`, `[STT]`, `[LLM]`) directamente en
  `std::cout` (`otto_pipeline.cpp:68-80`, `755-757`, etc.). El shim **no reutiliza ese patrón
  de I/O** — es un proceso nuevo con su propia disciplina stdout/stderr, no una copia del
  main original.

## 10. Manejo de errores

- Todo error de protocolo (comando desconocido, `interaction_id` inválido, payload fuera de
  límites) se reporta como evento `failed` con `code` y `message` acotados (regla
  `_validate_event_payload` para `WorkerEventType.FAILED`, `runtime_port.py:341-347`).
- El shim no debe terminar el proceso ante un comando inválido individual — reporta `failed`
  y continúa sirviendo el protocolo, salvo error fatal de inicialización (dependencias
  faltantes, ver §14).

## 11. Heartbeat y health

- El pipeline original no emite heartbeat — es una carencia explícita ya señalada en
  IA-CXX-R1 §22 (riesgo: "no heartbeat"). El shim debe añadir un emisor de `heartbeat`
  periódico independiente del bucle principal del pipeline (p. ej. hilo dedicado de baja
  prioridad), de forma que `JsonlInteractionWorkerSupervisor.heartbeat_monitor` tenga una
  señal de vida incluso durante fases largas de `PROCESANDO` (espera de Ollama) o
  `ESCUCHANDO` (VAD).
- `health` (comando de proceso) debe responder con un estado compatible con
  `InteractionRuntimeHealth` (protocol_version, state, ready, capabilities,
  last_heartbeat_monotonic_s, last_error) — el shim serializa esto como payload del evento de
  respuesta correspondiente.

## 12. Emergency stop

- `emergency_stop` es un comando de proceso (`interaction_id = None`), consistente con
  `JsonlInteractionWorkerSupervisor.emergency_stop()` que descarta la cola de comandos
  pendientes antes de encolarlo.
- El shim debe priorizar `emergency_stop` sobre cualquier operación de audio en curso:
  detener reproducción (`PlayStop` equivalente), abortar captura/VAD, y transicionar a un
  estado seguro antes de emitir el evento de confirmación. Esto es una extensión de
  comportamiento respecto al pipeline original, que hoy no tiene ningún mecanismo de
  cancelación externa — es responsabilidad nueva del shim, no del pipeline.

## 13. Timeouts

- `InteractionContext.timeout_s` (default 30.0s, `runtime_port.py:356`) ya coincide con
  `TIMEOUT_SECS` del pipeline original (`otto_pipeline.cpp:88`, `TIMEOUT_SECS = 30`) — no se
  requiere reconciliación numérica en R2, solo mapear el timeout de la interacción activa al
  mecanismo de timeout ya existente en el estado `ESCUCHANDO` (`otto_pipeline.cpp:787`).
- El shim debe emitir `interaction_timeout` (evento de interacción) cuando ese timeout se
  cumpla, en vez de transicionar silenciosamente a `HIBERNACION` como hace hoy el pipeline
  original.

## 14. Modelo de proceso C++

- Proceso nuevo, independiente del binario `otto_pipeline` compilado por
  `CMakeLists.txt` actual (que no se modifica en R2).
- `stdin`: lectura de comandos JSONL, una línea por comando.
- `stdout`: escritura de eventos JSONL, una línea por evento.
- `stderr`: logs humanos exclusivamente.
- Fail-closed ante dependencias faltantes: si en un futuro checkpoint de build (R4+) el shim
  detecta que `whisper.cpp`, el modelo Whisper, Ollama, Piper o el SDK Unitree no están
  disponibles, debe fallar el arranque (`ready=false` o evento `failed` en `start`) en vez de
  degradar silenciosamente a una respuesta simulada — la prohibición IA-CXX-R1 de "no
  simular respuesta en modo real" se preserva como requisito de diseño para R4+, aunque no
  aplica todavía en R2 (nada se ejecuta).

## 15. Layout del shim

```
docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/
├── otto_pipeline.cpp          (sin modificar — pipeline original, hash forense estable)
├── CMakeLists.txt             (sin modificar en R2)
├── otto_jsonl_protocol.hpp    (nuevo — constantes/enums/schema del protocolo, sin I/O)
├── otto_jsonl_shim.cpp        (nuevo — main() del shim, skeleton con TODOs)
└── README_JSONL_SHIM.md       (nuevo — documentación del shim)
```

`otto_jsonl_protocol.hpp` es deliberadamente separado de `otto_jsonl_shim.cpp` para que, en
un checkpoint futuro, pueda reutilizarse desde tests de protocolo (R3, fake-worker) sin
arrastrar dependencias de I/O.

## 16. Funciones candidatas de `otto_pipeline.cpp`

Mapeo de lógica pura (potencialmente extraíble a una librería compartida en un checkpoint
futuro posterior a R2) vs. I/O/loop principal (permanece en el pipeline original):

| Función | Línea aprox. | Tipo | Candidata a extraer |
|---|---|---|---|
| `normalizar` | 148 | pura (transform de string) | Sí |
| `es_alucinacion` | 166 | pura (filtro de string) | Sí |
| `es_wake_word` | 210 | pura (filtro de string) | Sí |
| `es_despedida` | 216 | pura (filtro de string) | Sí |
| `es_frase_salida` | 226 | pura (filtro de string) | Sí |
| `es_texto_valido` | 258 | pura (filtro de string) | Sí |
| `es_consulta_coherente` | 288 | pura (filtro de string, reglas de estructura) | Sí |
| `seleccionar_rechazo_contextual` | 420 | pura (selección de frase) | Sí |
| `frase_aleatoria` | 140 | pura (selección aleatoria) | Sí |
| `calcular_rms` | 598 | pura (cómputo numérico) | Sí |
| `rms_bar` / `estado_str` / `print_indicador` | 44-80 | I/O de terminal (ANSI) | No (descartar, no aplica al shim) |
| `transcribir` | 606 | I/O (Whisper GPU) | No en R2 — requiere `whisper_context*` vivo |
| `ollama_query` | 441 | I/O (socket HTTP directo) | No en R2 — es I/O de red bloqueante |
| `otto_say` | 484 | I/O (`system()` + `AudioClient::PlayStream`) | No — usa `system()`, deliberadamente fuera de alcance de "pura" |
| `otto_beep` | 529 | I/O (`AudioClient`) | No |
| `capture_thread` | 561 | I/O (UDP multicast, hilo) | No en R2 |
| `tomar_audio` / `tomar_utterance` | 647/659 | I/O (buffer compartido + `usleep`) | No en R2 |
| `main` / state machine | 704 | I/O + orquestación | No — es exactamente lo que el shim debe envolver, no reemplazar |

Las 10 funciones "puras" son las candidatas naturales para una librería compartida
(`otto_text_filters.hpp`/`.cpp` o similar) en un checkpoint futuro (R3+), porque no dependen
de sockets, hilos, ni SDKs — son transformaciones de `std::string`/`std::vector<int16_t>` sin
efectos de I/O. **Ninguna extracción ocurre en R2.**

## 17. Qué NO se extrae todavía

- `transcribir`, `ollama_query`, `otto_say`, `otto_beep`, `capture_thread`,
  `tomar_audio`/`tomar_utterance`: permanecen exclusivamente en `otto_pipeline.cpp`. Extraerlas
  requeriría decidir cómo comparten estado (`whisper_context*`, `g_audio`, `buf_mutex`,
  `audio_buffer`) entre el pipeline original y el shim, lo cual es una decisión de
  arquitectura de proceso (§18-20) que R2 solo documenta como pregunta abierta, no resuelve
  con código.
- La lógica de estados `HIBERNACION`/`ESCUCHANDO`/`PROCESANDO` (`main`, línea 704 en
  adelante) no se extrae — es el núcleo del loop que el shim debe envolver vía JSONL, no
  reimplementar.

## 18. Opción audio 1: C++ conserva UDP/audio físico

El shim (o el pipeline original, sin modificar) sigue siendo quien abre el socket UDP
multicast (`capture_thread`, `otto_pipeline.cpp:561-595`) y quien llama a
`AudioClient::PlayStream` para reproducir. Python únicamente envía comandos de ciclo de vida
(`start`, `activate`, `pause`, `resume`, `stop`, `emergency_stop`, `close`) y consume eventos;
nunca transporta audio.

Ventajas:
- Fiel al comportamiento ya validado físicamente en robot (mismo camino de captura/playback).
- No requiere extender el protocolo JSONL con payloads de audio binario/base64.
- No duplica responsabilidad de I/O de audio entre Python y C++.

Desventajas:
- El endpoint `POST /tour/pause` (que hoy decodifica `audio_b64` a PCM float32 y lo pasa a
  `orchestrator.request_interaction`, ver `api/router.py:154`) queda sin uso directo por el
  shim — ese audio decodificado no tendría destino en esta opción salvo que se ignore o se
  use solo para el camino legacy (`ConversationManager`).

## 19. Opción audio 2: Python inyecta audio PCM/audio_b64

El protocolo se extendería para que Python envíe el PCM capturado (p. ej. desde
`POST /tour/pause`) como parte del payload de `activate` o de un comando nuevo, y el shim
lo inyecte directamente al pipeline en vez de leer del socket UDP.

Ventajas:
- Reutiliza el audio que ya llega hoy a `POST /tour/pause` vía `audio_b64`.
- Desacopla la fuente de audio del transporte UDP multicast específico del robot.

Desventajas:
- Se aleja del pipeline validado físicamente — el camino probado en robot es UDP multicast
  directo desde el hardware de audio del G1, no un payload HTTP re-empaquetado.
- Requiere extender el protocolo JSONL (`runtime_port.py`) con un nuevo campo de payload de
  audio, lo cual está fuera del contrato ya diseñado y validado en IA-CXX-R1/R2.
- Duplica responsabilidad: dos caminos de entrada de audio (UDP directo + inyección Python)
  a mantener y sincronizar.

## 20. Decisión R2 sobre audio

**Opción 1 (C++ conserva UDP/audio físico) es la ruta primaria para R2 en adelante.** No hay
evidencia estática que la contradiga: el pipeline validado en robot ya captura y reproduce
audio de forma autónoma, y el protocolo JSONL existente (`runtime_port.py`) no fue diseñado
con un campo de payload de audio — introducir uno sería un cambio de protocolo no solicitado
en este checkpoint. La Opción 2 queda documentada como alternativa futura, a reconsiderar
solo si un checkpoint posterior encuentra una razón operativa concreta (p. ej. necesidad de
fuentes de audio no-UDP) que la Opción 1 no pueda cubrir.

## 21. Skeleton propuesto

Tres archivos nuevos, ninguno compilado ni ejecutado en R2 (ver §22 del reporte de gates):

- `otto_jsonl_protocol.hpp`: constantes de protocolo, enums de comando/evento, structs
  declarativos — sin dependencias de Unitree/Whisper/Ollama/Piper, sin syscalls, sin `main`.
- `otto_jsonl_shim.cpp`: `main()` skeleton con lectura de stdin y escritura de stdout
  marcadas como `TODO`, dispatch de comandos como stubs documentales, sin llamadas reales a
  audio/modelo/red, sin `system()`.
- `README_JSONL_SHIM.md`: propósito, estado (no compilado/no ejecutado), y gates pendientes
  antes de cualquier build futuro.

## 22. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| El shim diverge silenciosamente del contrato de `runtime_port.py` | `otto_jsonl_protocol.hpp` refleja 1:1 los valores string de `WorkerCommandType`/`WorkerEventType`; validación cruzada en R2B. |
| Mezclar accidentalmente logs y protocolo en stdout (como hace hoy `otto_pipeline.cpp`) | Regla explícita en skeleton: todo `std::cout` del shim es JSONL; todo log usa `std::cerr`. |
| Extracción futura de funciones puras introduce comportamiento distinto al validado en robot | Extracción diferida a checkpoint futuro con comparación explícita de outputs antes/después. |
| Ambigüedad sobre quién posee el socket UDP (shim vs. pipeline original) | Resuelta en R2: Opción 1, el shim no abre su propio socket UDP en ningún checkpoint hasta que se decida lo contrario explícitamente. |
| Falta de heartbeat dificulta detección de cuelgues reales | Diseño de heartbeat periódico independiente documentado en §11, a implementar en R3+. |

## 23. Gates de seguridad

- `otto_pipeline.cpp`, `CMakeLists.txt`, `otto_say.sh`: sin modificar (verificado por hash
  forense antes y después de este checkpoint).
- Ningún archivo nuevo contiene `system(`, llamadas a sockets reales, hilos, ni includes de
  `whisper.h`/`unitree/...`/Ollama/Piper.
- Ningún comando `cmake`/`make`/`g++` se ejecuta en este checkpoint.
- Ningún acceso a robot, micrófono, o red.

## 24. Plan R2B–R2F

- **R2B**: pre-push review del commit documental/skeleton local (sin runtime, sin push).
- **R2C**: staging al mirror únicamente, con confirmación explícita del usuario.
- **R2D**: análisis read-only del mirror antes de promoción canónica.
- **R2E**: promoción al canónico, con confirmación explícita del usuario.
- **R2F**: verificación final de alineación bit-a-bit canónico/mirror, cierre de ciclo R2.

## 25. Plan R3–R6

- **R3**: tests de protocolo contra un fake-worker (proceso de prueba que habla el mismo
  JSONL sin tocar Whisper/Ollama/Piper/Unitree), validando el contrato del shim de forma
  aislada.
- **R4**: compile-only offline — integrar el shim al build (`CMakeLists.txt` o build
  paralelo) en un entorno con el SDK disponible pero sin robot conectado; sin ejecución.
- **R5**: smoke test con binario dummy — ejecución controlada sin robot, validando el ciclo
  de vida del proceso (spawn, heartbeat, terminate) sin dependencias reales.
- **R6**: validación HIL con robot real, exclusivamente bajo autorización explícita y
  separada del resto del ciclo.

## 26. Criterios de aceptación de R2B

- El commit local de este checkpoint contiene exactamente los archivos listados en §15 más
  las notas documentales breves permitidas (§14 del prompt de origen).
- `otto_pipeline.cpp` mantiene el hash forense `0d1cc4567387f4bc41e3705d95c16d80be2e61d76fe2ea99dbe8a9fa6a926bcf`.
  sin cambios.
- `CMakeLists.txt` y `otto_say.sh` sin cambios.
- Ningún archivo Python funcional (`codigo ottoguide/src/**`, `codigo ottoguide/api/**`,
  `codigo ottoguide/main.py`) modificado.
- El skeleton C++ nuevo no contiene `system(`, llamadas reales a Whisper/Ollama/Piper/Unitree,
  ni ejecución de ningún tipo.
- Secret scan sobre el diff: 0 coincidencias.

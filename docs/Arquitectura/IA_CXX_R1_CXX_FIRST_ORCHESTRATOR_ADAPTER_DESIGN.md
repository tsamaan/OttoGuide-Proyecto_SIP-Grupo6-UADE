# IA-CXX-R1 — C++-first orchestrator adapter design

## 1. Resumen ejecutivo

`CXX_PIPELINE_PRIMARY = true`
`PYTHON_REIMPLEMENTATION_PRIMARY = false`
`R1_RUNTIME_EXECUTION = false`
`R1_CODE_FUNCTIONAL_CHANGES = false`
`NEXT_CHECKPOINT = IA-CXX-R2_CXX_JSONL_SHIM_DESIGN_OR_SKELETON_NO_ROBOT`

El pipeline C++ histórico (`otto_pipeline.cpp`) es el runtime candidato prioritario para
conversación física en el robot. Python no reimplementa STT/LLM/TTS/captura de audio/playback;
Python actúa como plano de control: supervisa el ciclo de vida del proceso C++, media entre
HTTP/FastAPI y el worker, y aplica las garantías de seguridad (emergency stop, timeouts,
auditoría) que ya existen en `TourOrchestrator`.

El hallazgo más importante de esta auditoría es que **el contrato del protocolo y el
supervisor del lado Python ya existen, completos y sin usar**: `runtime_port.py` define el
protocolo JSONL versionado (comandos, eventos, envelopes, validación estricta) y
`jsonl_worker_supervisor.py` implementa un supervisor de subproceso que ya habla ese
protocolo por `stdin`/`stdout`, con heartbeat, emergency stop prioritario, y escalación
`terminate`→`kill`. Lo que falta no es diseñar el protocolo — ya está diseñado y
type-checked — sino conectar el otro extremo: un proceso C++ que hable ese mismo protocolo.

## 2. Estado actual

### 2.1 `InteractionRuntimePort` — dónde existe

Definido en `codigo ottoguide/src/interaction/runtime_port.py`. Es un `Protocol`
(`runtime_checkable`) stdlib-only, sin efectos de lado, que declara:

```
async def start(self) -> None
async def health(self) -> InteractionRuntimeHealth
async def activate(self, context: InteractionContext) -> None
async def pause(self) -> None
async def resume(self) -> None
async def stop(self) -> None
async def emergency_stop(self) -> None
async def next_event(self, *, timeout_s: float | None = None) -> WorkerEventEnvelope
async def close(self) -> None
```

También define el wire protocol completo: `WorkerCommandType`, `WorkerEventType`,
`WorkerCommandEnvelope`, `WorkerEventEnvelope`, `InteractionRuntimeCapabilities`,
`InteractionRuntimeHealth`, `InteractionContext`, y validación estricta de payloads
(profundidad máxima, tamaño máximo, identificadores ASCII, enteros firmados de 64 bits,
JSON-safety). `INTERACTION_PROTOCOL_VERSION = 1`.

### 2.2 `TourOrchestrator` — dónde acepta `interaction_runtime` y dónde lo usa

`codigo ottoguide/src/core/tour_orchestrator.py:226` — el constructor acepta
`interaction_runtime: Optional[InteractionRuntimePort] = None`, guardado en
`self._interaction_runtime`.

Se usa en al menos estos puntos:

- `on_enter_interacting` (línea ~811): si `self._interaction_runtime is not None`, dispara
  `_run_supervised_runtime_interaction(waypoint_id)` como task; si es `None`, cae a
  `_run_legacy_conversation_interaction(...)` (el `ConversationManager` actual).
- `_run_supervised_runtime_interaction` (línea ~890): construye un `InteractionContext`
  (`interaction_id`, `tour_id`, `waypoint_id`, `locale="es-AR"`, `timeout_s`, `metadata`) y
  lo activa contra el runtime.
- `_ensure_runtime_emergency_task`, `_runtime_stop_best_effort`,
  `_runtime_emergency_stop_best_effort`: manejan parada/emergencia del runtime cuando está
  presente, sin bloquear el resto del apagado HIL-safe si el runtime no responde.

Es decir: **el orquestador ya sabe cómo hablarle a un `InteractionRuntimePort` real**. El
bifurcado legacy/runtime es una decisión de un solo `if` basada en si el parámetro fue
inyectado.

### 2.3 Por qué actualmente no se instancia en `main.py`

`codigo ottoguide/main.py` construye `TourOrchestrator` (línea ~191) pasando
`hardware_api`, `nav_bridge`, `conversation_manager=_get_conversation_manager_stub(settings)`,
`vision_processor`, `telemetry_manager`, `mission_audit_logger`, `robot_mode`, `event_bus`.
**No pasa `interaction_runtime=`.** El parámetro queda en su default `None`, por lo que
`app.state.orchestrator` siempre opera en el camino legacy (`ConversationManager`), nunca en
el camino runtime-supervisado, independientemente del modo (`mock`/`sim`/`real`).

Esto no es un bug — es una decisión pendiente documentada explícitamente en
`worker_supervisor.py`: *"La elección de transporte (JSONL, stdin/stdout, socket Unix, TCP,
pipe nombrado, memoria compartida) y de tecnología del worker (Python, C++) queda
deliberadamente sin decidir en esta etapa."* Este documento toma esa decisión.

### 2.4 Endpoints actuales que disparan interacción

- `POST /question` (`api/router.py:678`): texto plano → `orchestrator.handle_user_question(text)`
  → `ConversationManager`. Docstring explícito: *"Sin ejecucion de STT; texto plano."* No pasa
  por `InteractionRuntimePort` en el código actual (llama directo al método del orquestador,
  no a `on_enter_interacting`).
- `POST /tour/pause` (`api/router.py:154`): acepta `audio_b64` opcional (PCM float32,
  decodificado en memoria, nunca a disco). Requiere estado `NAVIGATING`. Llama
  `orchestrator.request_interaction(audio_pcm, language=...)`, que termina disparando la
  transición NAVIGATING→INTERACTING y, dentro de ella, `on_enter_interacting` — el mismo punto
  de bifurcación legacy/runtime descrito en 2.2.

### 2.5 Qué cubre `/question`

Solo texto. No hay ruta de audio en este endpoint. Sirve como fallback de accesibilidad/debug
(preguntar sin hablarle al robot), no como sustituto del loop conversacional físico.

### 2.6 Qué cubre `/tour/pause`

Acepta audio, pero hoy ese audio no llega a Whisper/Ollama/Piper reales — llega al
`ConversationManager` Python (que internamente puede usar `LocalNLPPipeline`/
`CloudNLPPipeline` vía Ollama, con fallback a un stub mínimo si Ollama no está disponible).
No hay STT real en el camino Python actual: el audio PCM se pasa a
`process_interaction(audio_buffer, language=...)`, y no hay evidencia en este árbol de que
`ConversationManager` invoque Whisper. El STT/TTS/playback físico real solo existe en
`otto_pipeline.cpp`.

### 2.7 Qué sigue siendo legacy `ConversationManager`

Todo el camino que no pasa por `interaction_runtime`: `_run_legacy_conversation_interaction`,
`_get_conversation_manager_stub` en `main.py`, `LocalNLPPipeline`/`CloudNLPPipeline` en
`src/interaction/conversation_manager.py`. Este camino seguirá existiendo como fallback
degradado (p. ej. si el worker C++ falla en real mode y se decide fallar cerrado en vez de
silenciarlo — ver §22 Gates de seguridad) pero no es el candidato primario para conversación
física.

## 3. Decisión de arquitectura CXX-first

- `otto_pipeline.cpp` y el árbol `Ottoguide_IA/` son la base prioritaria para el runtime de
  conversación física.
- Python no reimplementa captura de audio UDP, wake word, VAD, STT (Whisper), LLM local
  (Ollama), TTS (Piper) ni playback físico (`AudioClient.PlayStream`).
- Python supervisa: lifecycle del proceso, health/readiness, enrutamiento HTTP, telemetría,
  auditoría, y tiene la última palabra en emergency stop.
- El C++ sigue siendo dueño del loop conversacional físico completo, incluyendo su propia
  máquina de estados interna (`HIBERNACION`/`ESCUCHANDO`/`PROCESANDO`), sus filtros
  anti-alucinación, su normalización de texto en español, y sus heurísticas de wake
  word/despedida — toda lógica ya afinada y validada empíricamente en robot real.

## 4. Por qué no reimplementar en Python

1. **Ya funciona y fue validado físicamente.** `IMPORT_PROVENANCE.md` registra que el equipo
   reportó el pipeline como probado en un Unitree G1 EDU real (aunque esta importación no
   repitió esa validación HIL). Reimplementar significa renunciar a ese historial de pruebas
   y reintroducir todos los bugs que el ajuste iterativo en C++ ya resolvió (los filtros
   `es_alucinacion`, `es_consulta_coherente`, `normalizar` son el resultado de iteración
   empírica contra Whisper real, no de diseño teórico).
2. **Latencia y stack de audio en tiempo real.** El C++ ya integra directamente con
   `unitree_sdk2` (`g1_audio_client.hpp`, `channel_factory.hpp`) y `whisper.cpp` con
   aceleración CUDA (`use_gpu = true`, enlazado contra `libggml-cuda.so`). Reconstruir un
   pipeline de audio de baja latencia equivalente en Python (bindings de Whisper, cliente
   UDP multicast, cliente Unitree audio) es trabajo sustancial sin garantía de paridad de
   latencia — el propio protocolo (`runtime_port.py`) ya fue diseñado asumiendo un worker
   nativo con estos requisitos de tiempo real.
3. **Duplicación de superficie de fallos.** Cada reimplementación introduce una segunda
   fuente de bugs de audio/modelo que hay que mantener en paralelo al C++ ya probado, sin
   beneficio arquitectónico: el `InteractionRuntimePort` ya abstrae completamente la
   tecnología del worker.
4. **La decisión ya estaba prevista.** `worker_supervisor.py` documenta explícitamente que
   "Python, C++" son ambas opciones de tecnología de worker contempladas por diseño — el
   protocolo no asume Python del otro lado.

`PYTHON_REIMPLEMENTATION_PRIMARY = false` es, por lo tanto, la continuación natural de una
decisión de arquitectura ya tomada en el código existente, no una preferencia nueva de este
documento.

## 5. Componentes existentes reutilizables

| Componente | Archivo | Rol en el diseño CXX-first |
|---|---|---|
| `InteractionRuntimePort` | `src/interaction/runtime_port.py` | Contrato ya definido; se implementa contra el worker C++ vía `JsonlInteractionWorkerSupervisor`, no requiere una clase nueva. |
| Protocolo JSONL (comandos/eventos/envelopes) | `src/interaction/runtime_port.py` | Ya versionado (`INTERACTION_PROTOCOL_VERSION=1`), ya valida framing/tamaño/tipos. Es el protocolo que el shim C++ debe hablar. |
| `JsonlInteractionWorkerSupervisor` | `src/interaction/jsonl_worker_supervisor.py` | Ya implementa spawn de subproceso, JSONL sobre stdin/stdout, drenado de stderr como logs, heartbeat monitor, emergency stop con descarte de cola, escalación terminate→kill. Solo necesita un `argv` que apunte al binario C++/shim. |
| `InteractionWorkerSupervisor` (Protocol) | `src/interaction/worker_supervisor.py` | Extiende el runtime port con `termination: WorkerTermination \| None`. Ya implementado por `JsonlInteractionWorkerSupervisor`. |
| Punto de inyección | `main.py` (constructor de `TourOrchestrator`) | Falta un solo argumento nuevo: `interaction_runtime=<instancia de JsonlInteractionWorkerSupervisor>`. |
| Bifurcación legacy/runtime | `tour_orchestrator.py::on_enter_interacting` | Ya implementada; no requiere cambios para activar el camino runtime, solo que `interaction_runtime` deje de ser `None`. |

**No hace falta escribir un nuevo protocolo ni un nuevo supervisor.** El trabajo de R2+ es:
(a) decidir cómo el C++ habla ese protocolo (opción A vs B, §14-16), y (b) conectar el punto
de inyección en `main.py` bajo un gate de configuración explícito.

## 6. Frontera Python/C++

```
FastAPI (api/router.py)
   │  POST /tour/pause {audio_b64?}      POST /question {text}
   ▼
TourOrchestrator (src/core/tour_orchestrator.py)
   │  on_enter_interacting()
   │  interaction_runtime is not None?
   ├── NO  → _run_legacy_conversation_interaction() → ConversationManager (Python NLP)
   └── SI  → _run_supervised_runtime_interaction()
                │
                ▼
        InteractionRuntimePort (contrato, src/interaction/runtime_port.py)
                │
                ▼
        JsonlInteractionWorkerSupervisor (src/interaction/jsonl_worker_supervisor.py)
                │  subprocess.exec(argv)
                │  stdin  ─── JSONL commands  ──▶
                │  stdout ◀── JSONL events    ───
                │  stderr ◀── logs (drenados, nunca protocolo)
                ▼
        Proceso C++ (otto_pipeline modificado, o shim/wrapper — ver §13-16)
                │
                ▼
        UDP mic (robot) → Whisper (GPU) → Ollama local (:11434) → Piper → AudioClient.PlayStream
```

Reglas de frontera (todas ya reflejadas en el supervisor Python existente):

- `stdout` del proceso C++ es protocolo exclusivamente — una línea, un JSON, un evento. Nada
  de logs de progreso, barras de RMS, ni indicadores ANSI ahí.
- `stderr` es para logs humanos; el supervisor lo drena a una cola acotada
  (`stderr_tail_lines`, `stderr_tail_max_chars`) sin interpretarlo como protocolo.
- Nunca construir comandos de shell con texto proveniente del usuario (ya es una invariante
  documentada en `worker_supervisor.py`; el actual `otto_say()` en C++ usa `system()` con
  `PIPER_BIN`/`PIPER_VOICE` fijos, no con texto de usuario interpolado directamente en el
  comando — pero cualquier adapter debe preservar esta propiedad si cambia esa función).
- El proceso C++ no debe degradarse silenciosamente en modo real: si no puede alcanzar
  Whisper/Ollama/Piper/`AudioClient`, debe emitir `FAILED` (evento de proceso,
  `interaction_id=None`) y terminar, nunca simular una respuesta.

## 7. Contrato `InteractionRuntimePort`

Ya completamente definido (ver §2.1). No requiere cambios de forma para soportar C++: el
contrato es agnóstico a la tecnología del worker por diseño. `JsonlInteractionWorkerSupervisor`
ya lo implementa contra *cualquier* proceso hijo que hable el protocolo JSONL correcto — sea
Python o C++.

## 8. Supervisor recomendado

`JsonlInteractionWorkerSupervisor` (existente, sin modificar). Se instancia con un
`JsonlWorkerSupervisorConfig(argv=(...))` donde `argv` apunta al binario C++ (o al shim, ver
§13-16). No se requiere un nuevo supervisor para C++: el supervisor ya es agnóstico al
lenguaje del worker, solo exige que hable JSONL por stdin/stdout con el framing y los tipos de
mensaje definidos en `runtime_port.py`.

## 9. Protocolo de comandos

Ya definido en `WorkerCommandType` (`runtime_port.py`):

| Comando | Clase | interaction_id | Uso esperado contra C++ |
|---|---|---|---|
| `start` | proceso | `None` | Enviado una vez al arrancar; el worker debe responder `ready` con `capabilities`. |
| `health` | proceso | `None` | Reservado para chequeo de salud explícito (ver §17). |
| `activate` | interacción | requerido | Arranca una interacción: payload incluye `locale`, `timeout_s` (ver `_run_supervised_runtime_interaction`). |
| `pause` | interacción | requerido | Pausa la interacción activa (ej. si el orquestador necesita reanudar navegación). |
| `resume` | interacción | requerido | Reanuda una interacción pausada. |
| `stop` | interacción | requerido | Termina la interacción activa de forma cooperativa. |
| `emergency_stop` | proceso | `None` | Máxima prioridad; descarta cola de comandos pendientes antes de enviarse (ya implementado en el supervisor). |
| `close` | proceso | `None` | Apagado cooperativo del worker completo. |

## 10. Protocolo de eventos

Ya definido en `WorkerEventType` (`runtime_port.py`):

| Evento | Clase | interaction_id | Mapeo al loop C++ actual |
|---|---|---|---|
| `ready` | proceso | `None` | Tras cargar Whisper y conectar `AudioClient` (hoy: líneas `[OK] Whisper cargado en GPU`, `[OK] AudioClient conectado`). Payload debe incluir `InteractionRuntimeCapabilities`. |
| `heartbeat` | proceso | `None` | Nuevo — el C++ actual no emite heartbeat; debe agregarse (ver §19 timeouts). |
| `command_accepted` | flexible | según comando | Ack de correlación (`message_id`, `command`) — nuevo en el C++, ya validado por el supervisor. |
| `wake_word_confirmed` | proceso | `None` | Mapea a la transición `HIBERNACION → ESCUCHANDO` (hoy: `"Wake word detectada -> ESCUCHANDO"`). |
| `capture_started` | interacción | requerido | Inicio de `tomar_utterance()` (captura VAD). |
| `transcript_ready` | interacción | requerido | Tras `transcribir()` exitoso, texto ya filtrado de alucinaciones. |
| `response_ready` | interacción | requerido | Tras `ollama_query()` exitoso. |
| `playback_started` | interacción | requerido | Inicio de `otto_say()` / primer `PlayStream`. |
| `playback_completed` | interacción | requerido | Tras el `PlayStop` al final de `otto_say()`. |
| `interaction_timeout` | interacción | requerido | Mapea al timeout de `TIMEOUT_SECS` en estado `ESCUCHANDO` (hoy vuelve a `HIBERNACION` sin señalizar al exterior). |
| `cancelled` | interacción | requerido | Interacción cancelada por comando `stop`/`pause` antes de completar. |
| `failed` | flexible | según contexto | Errores de proceso (Whisper no carga, `AudioClient` no conecta) o de interacción (Ollama no responde). |
| `stopped` | proceso | `None` | Confirmación de `stop` a nivel proceso (poco usado; la mayoría de `stop` son de interacción). |
| `closed` | proceso | `None` | Confirmación final de `close`, ya usada por `_close_impl()` para esperar `closed_event`. |

## 11. Mapeo `TourOrchestrator` → runtime C++

`on_enter_interacting()` ya construye el `InteractionContext` correcto
(`interaction_id`, `tour_id`, `waypoint_id`, `locale="es-AR"`, `timeout_s`) y lo pasa a
`activate()`. No requiere cambios: una vez que `interaction_runtime` no sea `None`, este
camino se activa automáticamente sin tocar `tour_orchestrator.py`.

## 12. Mapeo de endpoints actuales

- `POST /tour/pause` con `audio_b64`: hoy el audio decodificado se pasa a
  `orchestrator.request_interaction(audio_pcm, ...)`, que dispara la transición hacia
  `on_enter_interacting`. Una vez conectado el runtime C++, este es el disparador natural del
  loop conversacional físico completo — pero el C++ actual **captura su propio audio por UDP
  multicast** (`capture_thread()`, `MCAST_GRP`/`MCAST_PORT`), no recibe PCM desde Python. Este
  es un desacople de diseño a resolver explícitamente en R2: o (a) el worker C++ ignora
  `audio_b64` y sigue escuchando el multicast directamente (más fiel al comportamiento
  probado), o (b) se extiende el protocolo para inyectar audio desde Python al worker (mayor
  cambio, mayor riesgo). Este documento recomienda (a) para R2/R3 y deja (b) fuera de alcance
  hasta que exista evidencia de que el multicast directo no es viable en la topología final.
- `POST /question` (texto): permanece en el camino legacy de texto plano por ahora. No se
  recomienda enrutarlo al worker C++ en R2 — el C++ está diseñado alrededor de un loop de
  audio continuo (`HIBERNACION`/`ESCUCHANDO`), no de peticiones de texto discretas; forzarlo
  requeriría un modo de operación nuevo no probado en robot.

## 13. Estrategia para `otto_pipeline.cpp`

El archivo es monolítico e interactivo por diseño: un único `main()` con una máquina de
estados infinita, salida a terminal con colores ANSI e indicador de estado que sobreescribe
la línea actual (`print_indicador`), y sin ninguna noción de protocolo estructurado. Su
`stdout` mezcla logs humanos (`[MIC]`, `[STT]`, `[LLM]`) con el indicador visual — exactamente
lo opuesto de "stdout exclusivo para protocolo" que exige la frontera Python/C++ (§6).

## 14. Opción A: modificar `otto_pipeline.cpp` para hablar JSONL directamente

Reescribir el loop principal para que, en cada transición de estado relevante, escriba un
evento JSONL a stdout y lea comandos JSONL de stdin en vez de manejar su propio ciclo
autónomo con indicador visual. Ventaja: un solo binario, sin capa adicional. Riesgo: toca
directamente la lógica de estado ya probada en robot (`HIBERNACION`/`ESCUCHANDO`/`PROCESANDO`,
los filtros anti-alucinación, el manejo de `otto_say`/`otto_beep`), mezclando refactor de
I/O con lógica de negocio validada — cualquier error de esta reescritura arriesga
comportamiento ya afinado empíricamente contra Whisper/Ollama reales.

## 15. Opción B: shim/wrapper C++ alrededor del pipeline actual

Crear un proceso C++ nuevo y separado que: (a) hable JSONL por stdin/stdout con Python según
el protocolo de `runtime_port.py`, y (b) invoque la lógica del pipeline actual — idealmente
extrayendo las funciones puras ya existentes (`transcribir`, `ollama_query`, `otto_say`,
`es_alucinacion`, `es_consulta_coherente`, `normalizar`, etc.) a una librería/header
reutilizable, sin tocar su implementación, y reemplazando únicamente el `main()` y el I/O de
terminal (`print_indicador`, `std::cout` de estado) por el protocolo JSONL. El loop de estado
del shim reemplaza al loop de `otto_pipeline.cpp::main()`, pero llama a las mismas funciones
ya probadas.

## 16. Decisión recomendada entre A/B

**Recomendado: Opción B (shim/wrapper).**

Razones:

1. Preserva byte-a-byte la lógica de negocio ya validada (filtros, normalización, wake
   word/despedida, integración Whisper/Ollama/Piper/`AudioClient`) — el riesgo de regresión
   se limita a la capa de I/O nueva, no a la lógica conversacional.
2. Permite mantener `otto_pipeline.cpp` intacto como referencia forense (hash SHA-256
   verificable) mientras el shim evoluciona independientemente.
3. El `main()` actual ya es la única parte fuertemente acoplada a stdout como interfaz
   humana (colores ANSI, indicador que sobreescribe línea) — es precisamente la parte que
   Opción B reemplaza sin tocar el resto.
4. Es más fácil de testear de forma aislada en R3 (protocolo con fake worker) sin depender de
   que la extracción de funciones puras esté ya completa: el shim puede empezar como un
   wrapper delgado y ganar funciones reales incrementalmente.

Riesgo aceptado de Opción B: duplica superficialmente el punto de entrada (`main()` del shim
vs `main()` de `otto_pipeline.cpp` original), y requiere disciplina para no divergir la lógica
extraída de la del archivo original archivado. Mitigación: el archivo original permanece
como referencia con hash forense fijo; cualquier extracción de función a header compartido se
audita línea por línea contra el original en el checkpoint de implementación (R2+), no en
este checkpoint de diseño.

## 17. Health/readiness/capabilities

`health` (comando) → el worker debe responder con un evento que permita reconstruir
`InteractionRuntimeHealth` (`state`, `ready`, `capabilities`, `last_heartbeat_monotonic_s`,
`last_error`). `InteractionRuntimeCapabilities` ya declara exactamente los flags relevantes
para este pipeline: `audio_capture`, `wake_word`, `vad`, `stt`, `local_llm`, `spanish_tts`,
`physical_playback`, `physical_playback_stop`, `physical_playback_completion` — todos `bool`,
todos ya mapeables 1:1 a las capacidades reales de `otto_pipeline.cpp` (todas `true` si el
worker arrancó correctamente con Whisper cargado, `AudioClient` conectado, y Piper/Ollama
alcanzables).

`ready` debe emitirse solo cuando: Whisper cargado en GPU, `AudioClient` conectado con volumen
leído exitosamente (ya son los dos chequeos duros que hoy abortan con `return 1` en
`main()`), y el thread de captura UDP arrancado.

## 18. Stop/emergency

`emergency_stop` ya tiene prioridad garantizada en el supervisor Python
(`JsonlInteractionWorkerSupervisor.emergency_stop()`): descarta la cola de comandos
pendientes antes de encolar el propio `emergency_stop`, y una vez `_emergency_latched` queda
en `true`, ningún otro comando se acepta salvo el propio `emergency_stop`. Del lado C++, el
shim debe:

- Interrumpir inmediatamente cualquier reproducción en curso (`g_audio->PlayStop("otto")`)
  sin esperar a que termine el audio.
- Cancelar cualquier captura/transcripción en curso.
- Nunca reintentar conectar a Ollama/Whisper/`AudioClient` tras recibir `emergency_stop`.
- Responder rápido (dentro de `write_timeout_s`/`shutdown_timeout_s` del supervisor) para no
  forzar la escalación `terminate`→`kill` salvo que el proceso esté genuinamente colgado.

Esto reproduce, en el shim C++, la misma prioridad que `TourOrchestrator._runtime_emergency_stop_best_effort`
ya asume del lado Python.

## 19. Timeouts

El C++ actual ya tiene timeouts propios (`TIMEOUT_SECS=30` para volver a `HIBERNACION`,
`ms_max=8000` para `tomar_utterance`), pero no los comunica al exterior — hoy solo imprime a
consola. El shim debe:

- Mapear el timeout de `ESCUCHANDO` sin actividad a un evento `interaction_timeout`
  correlacionado con el `interaction_id` activo, en vez de solo volver a `HIBERNACION`
  silenciosamente.
- Emitir `heartbeat` a un intervalo menor que `heartbeat_timeout_s` configurado en Python
  (`JsonlWorkerSupervisorConfig.heartbeat_timeout_s`, default 5s) — necesario porque hoy el
  C++ no tiene ningún mecanismo de heartbeat, y el supervisor Python matará el worker si no
  lo recibe a tiempo (`_heartbeat_monitor`).
- Respetar `write_timeout_s`/`startup_timeout_s` del lado Python: el arranque de Whisper
  (carga de modelo en GPU) debe completar y emitir `ready` dentro del `startup_timeout_s`
  configurado, o el supervisor declarará fallo de arranque.

## 20. Logs: stdout protocolo, stderr logs

Cambio de comportamiento requerido respecto del C++ actual: hoy `std::cout` mezcla el
indicador de estado ANSI (`print_indicador`) con logs informativos (`[MIC]`, `[STT]`, `[LLM]`,
colores). En el shim:

- `stdout`: exclusivamente líneas JSONL de protocolo (un evento por línea, terminado en
  `\n`, UTF-8). Nada de colores ANSI, nada de indicador que sobreescribe línea.
- `stderr`: todo el logging humano — puede conservar el formato actual con colores si se
  desea para depuración manual, ya que el supervisor Python solo lo dren a como texto plano
  (`stderr_tail`) sin interpretarlo.

## 21. Variables/configuración necesarias

Actualmente hardcodeadas en `#define` dentro de `otto_pipeline.cpp` (líneas 82-97):
`MCAST_GRP`, `MCAST_PORT`, `LOCAL_IP`, `WHISPER_MODEL` (ruta absoluta
`/home/unitree/Desktop/whisper.cpp/models/...`), `PIPER_BIN`/`PIPER_VOICE` (rutas absolutas
`/home/unitree/piper/...`), `NET_IFACE`. El `CMakeLists.txt` también hardcodea
`WHISPER_DIR=/home/unitree/Desktop/whisper.cpp` y rutas de librerías CUDA
(`libggml-cuda.so`). Para R2+, estos valores deberían quedar como argumentos de línea de
comando o variables de entorno del shim (no de `otto_pipeline.cpp` original, que permanece
intacto) — pero **esa externalización de configuración es trabajo de R2/R4, no de este
checkpoint de diseño**.

## 22. Riesgos y mitigaciones

| Riesgo | Detalle | Mitigación |
|---|---|---|
| Pipeline monolítico/interactivo | `main()` mezcla estado, I/O de terminal, y lógica de negocio en un único loop sin separación. | Opción B (shim) aísla el cambio de I/O sin tocar la lógica de negocio (§16). |
| stdout mixto (logs + protocolo) | Hoy `std::cout` lleva tanto indicador visual como logs informativos. | Shim redirige todo log humano a stderr; stdout queda exclusivo para JSONL (§20). |
| Rutas hardcodeadas (modelo, Piper, red) | Ver §21; asume filesystem y topología del robot exactos. | No resolver en R1; documentar como bloqueante de R4 (compile-only offline) y R6 (HIL). |
| IP/interfaz/multicast dependen del robot | `MCAST_GRP`, `LOCAL_IP`, `NET_IFACE` fijos al robot real. | El shim no debe intentar simular estos valores fuera de HIL; R3/R5 usan fake worker/binario dummy, no el pipeline real. |
| Unitree SDK2 requerido | `channel_factory.hpp`, `g1_audio_client.hpp` — no compilable sin el SDK instalado. | R4 (compile-only) requiere entorno con SDK disponible pero sin robot conectado; fuera de alcance de este checkpoint. |
| Playback físico solo validable con robot | `AudioClient::PlayStream` no tiene equivalente mock conocido en este árbol. | R5 usa binario dummy/worker fake que simula eventos sin tocar `AudioClient` real; R6 es el único checkpoint que valida contra hardware. |
| Real mode no debe degradar a stub silenciosamente | Si el worker C++ falla en `ROBOT_MODE=real`, el orquestador no debe caer a `ConversationManager` sin que quede auditado/visible — degradar silenciosamente rompe la expectativa de que en real mode el runtime supervisado es la única fuente de verdad conversacional. | El diseño de fallback (R2+) debe decidir explícitamente: o (a) fallar cerrado (sin interacción) con `INTERACTION_TIMEOUT`/`FAILED` visible en `/status`, o (b) permitir fallback a legacy solo con flag explícito y auditado — nunca implícito. |
| `emergency_stop` debe tener prioridad sobre reproducción/loop C++ | Un `PlayStream` en curso no debe bloquear la respuesta a emergencia. | Ya garantizado del lado Python (descarte de cola); el shim C++ debe interrumpir `PlayStream` activamente, no esperar a que termine (§18). |
| Health debe detectar worker colgado o sin heartbeat | Sin heartbeat, un C++ colgado (p. ej. esperando indefinidamente una respuesta de Ollama) nunca sería detectado. | Requiere agregar heartbeat activo al shim (§19); el supervisor Python ya tiene `_heartbeat_monitor` implementado y listo para consumirlo. |

## 23. Gates de seguridad

- Ningún checkpoint hasta R5 inclusive toca el robot, compila C++, ni ejecuta binarios reales.
- R4 (compile-only) requiere entorno explícito con Unitree SDK2 y whisper.cpp disponibles,
  pero sigue sin robot conectado ni ejecución.
- R6 es el único checkpoint que puede tocar hardware, y solo con autorización explícita
  adicional al estilo de los gates ya usados en el ciclo WEB-R6 (confirmación explícita del
  usuario antes de cualquier acción irreversible o que toque el robot).
- `otto_pipeline.cpp` permanece sin modificar en todos los checkpoints hasta que R2+ decida
  explícitamente, con evidencia, extraer funciones a un header compartido — y aun entonces,
  el archivo original conserva su hash forense de referencia.

## 24. Plan R2-R6

- **R2**: diseño del shim/protocolo o skeleton documental/código mínimo sin ejecución —
  definir el layout del shim C++ (qué funciones se extraen de `otto_pipeline.cpp` a header
  compartido, cómo se estructura el loop JSONL), sin compilar ni ejecutar.
- **R3**: tests de protocolo con fake worker (Python o script simple que hable JSONL), sin
  C++ real — valida que `JsonlInteractionWorkerSupervisor` maneja correctamente el ciclo de
  vida completo (start/health/activate/pause/resume/stop/emergency_stop/close) contra un
  doble de prueba.
- **R4**: compile-only offline, sin robot — compila el shim C++ (y opcionalmente
  `otto_pipeline.cpp` intacto) en un entorno con Unitree SDK2/whisper.cpp disponibles, sin
  ejecutar ningún binario ni tocar hardware.
- **R5**: smoke con binario dummy o worker fake, sin robot — ejecuta el supervisor Python
  contra un binario C++ mínimo (o el shim real en modo simulado) que responda al protocolo
  sin invocar Whisper/Ollama/Piper/`AudioClient` reales.
- **R6**: HIL-safe con robot, solo con autorización explícita — primera validación contra
  hardware real, siguiendo el mismo patrón de confirmación explícita usado en el ciclo
  WEB-R6 antes de cualquier push/acción irreversible.

## 25. Fuera de alcance

- Modificar `otto_pipeline.cpp`, `CMakeLists.txt`, o `otto_say.sh`.
- Compilar o ejecutar cualquier binario C++.
- Iniciar Ollama, Whisper, o Piper.
- Abrir micrófono o reproducir audio.
- Modificar `main.py`, `api/router.py`, `api/schemas.py`, o cualquier archivo bajo
  `src/interaction/**` o `src/core/**`.
- Acceder al robot físico.
- Decidir la resolución final del desacople de audio descrito en §12 (multicast directo vs
  inyección de PCM desde Python) — queda como pregunta abierta para R2.

## 26. Criterios de aceptación del próximo checkpoint (IA-CXX-R2)

- Documento o skeleton que enumere exactamente qué funciones de `otto_pipeline.cpp` se
  extraerían a un header compartido (sin modificar el archivo original).
- Definición del layout de archivos del shim (p. ej. `otto_pipeline_jsonl_shim.cpp` +
  header compartido) sin crear el binario.
- Sin compilación, sin ejecución, sin acceso a robot.
- Debe dejar explícita la decisión pendiente de §12 (multicast directo vs inyección de audio)
  o, como mínimo, marcarla como pregunta abierta a resolver antes de R3.

## IA-CXX-R2 update

IA-CXX-R2 creó el diseño detallado del shim JSONL y un skeleton de código C++ no compilado ni
ejecutado (`otto_jsonl_shim.cpp`, `otto_jsonl_protocol.hpp`), sin modificar
`otto_pipeline.cpp`. La decisión de audio de §12/§25 fue resuelta a favor de la Opción 1
(C++ conserva UDP/audio físico) como ruta primaria. Ver
`docs/Arquitectura/IA_CXX_R2_CXX_JSONL_SHIM_DESIGN.md`.

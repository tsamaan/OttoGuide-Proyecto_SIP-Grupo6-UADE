# IA-CXX-R10 — Detailed adapter design offline

## 1. Dictamen

Este documento es un diseño técnico detallado, puramente offline. No implementa código, no
compila, no ejecuta, no usa robot. Detalla el adapter/shim C++ que, en un checkpoint futuro
(propuesto como R11, Nivel C, no fast-track), conectará `JsonlInteractionWorkerSupervisor`
(Python, sin cambios) con la lógica de conversación física ya probada en `otto_pipeline.cpp`
(C++, sin cambios en este checkpoint), reutilizando el contrato de protocolo ya validado por el
worker loopback de R8.

## 2. Estado actual confirmado

- Canónico y mirror alineados en `d036c2ee9015d2e0e8b763cd6fdd19cdc5d7e136` (POLICY-DOCS-FAST-R1),
  verificado independientemente en este checkpoint vía `git ls-remote` propio.
- Ciclo IA-CXX-R8 cerrado: worker C++ loopback protocol-compliant (test double) validado contra
  `JsonlInteractionWorkerSupervisor` real.
- Ciclo IA-CXX-R9 cerrado: plan de bridge documentado, identificando la brecha completa entre
  el loopback worker y `otto_pipeline.cpp`.
- `DOCS_ONLY_FAST_TRACK = true` habilitado en `AGENTS.md` (POLICY-DOCS-FAST-R1), usado en este
  checkpoint si el diff final se mantiene acotado a este único documento.
- `otto_jsonl_shim.cpp` sigue siendo el stub vacío original de R5; ningún dispatch loop real
  implementado todavía en ningún archivo.
- `otto_pipeline.cpp` con hash forense estable
  (`0d1cc4567387f4bc41e3705d95c16d80be2e61d76fe2ea99dbe8a9fa6a926bcf`) desde su importación.

## 3. Alcance y no-alcance

**Alcance de R10 (este checkpoint):** diseño detallado, documental, del adapter/shim C++:
mapeo comando-por-comando y evento-por-evento, modelo de proceso, lifecycle, manejo de errores,
configuración futura, mocks necesarios, y gates diferenciados para las etapas futuras de build,
ejecución offline, integración con componentes reales, y robot/HIL.

**No-alcance de R10:** no crea ni modifica ningún archivo `.cpp`/`.hpp`/`.py`. No compila. No
ejecuta. No toca `otto_pipeline.cpp` ni `docs/legacy/**`. No toca código bajo
`codigo ottoguide/src/interaction/cxx_runtime/`. No autoriza robot, SSH, audio real, ni Unitree
SDK bajo ninguna circunstancia.

## 4. Principio CXX-first

```text
CXX_PIPELINE_PRIMARY = true
PYTHON_REIMPLEMENTATION_PRIMARY = false
PYTHON_ROLE = supervisor_control_plane
CXX_ROLE = physical_conversation_runtime
```

`otto_pipeline.cpp` es un activo histórico funcional, ya validado físicamente en el robot. El
adapter diseñado aquí debe envolverlo, nunca reemplazar su lógica de audio/STT/LLM/TTS por una
reimplementación Python. R10 no implementa código; R11 (propuesto), si se aprueba, será
compile-only/offline, sin robot.

## 5. Contrato JSONL existente

`runtime_port.py` (stdlib-only, sin efectos de lado) define el contrato fuente de verdad:
`INTERACTION_PROTOCOL_VERSION = 1`; 8 comandos (`start`, `health`, `activate`, `pause`,
`resume`, `stop`, `emergency_stop`, `close`); 14 eventos (ver §9); envelope con
`protocol_version`, `message_id`, `interaction_id`, `sequence`, `emitted_at_monotonic_s`,
`payload`, más `command`/`event`. `JsonlInteractionWorkerSupervisor` spawnea un único proceso
hijo, trata `stdout` como protocolo JSONL exclusivo y `stderr` como logs, y aplica timeouts de
arranque/heartbeat/escritura/cierre configurables. El worker loopback de R8 ya demuestra que un
proceso C++ puede satisfacer este contrato completo sin modificar el supervisor.

## 6. Modelo de proceso objetivo

El adapter es el único proceso hijo que el supervisor Python spawnea vía `argv` — mismo modelo
que el loopback worker de R8, no un modelo nuevo. Internamente, el adapter:

1. Lee líneas JSONL de stdin en un loop de dispatch (implementación real, reemplazando el stub
   de `otto_jsonl_shim.cpp`).
2. Traduce cada comando entrante a una llamada de control sobre la lógica extraída de
   `otto_pipeline.cpp` (mecanismo exacto de extracción: fuera de alcance de R10, ver §18).
3. Traduce las transiciones internas de esa lógica (wake word, utterance capturada, respuesta
   lista, reproducción) a eventos JSONL salientes por stdout.
4. No abre threads adicionales de I/O de red/audio en la primera iteración (R11 compile-only);
   la concurrencia real (captura UDP en su propio hilo, como en `otto_pipeline.cpp` original) se
   diseña en un checkpoint posterior a R11, una vez que el dispatch loop básico esté probado
   contra mocks.

## 7. stdout JSONL-only / stderr logs-only

Invariante heredado sin excepción del worker loopback de R8 y del contrato de
`jsonl_worker_supervisor.py`: `stdout` transporta exclusivamente líneas JSONL de protocolo, una
por evento, con `\n` final y flush explícito. Cualquier log de diagnóstico, traza de debug, o
mensaje humano legible va exclusivamente a `stderr`, nunca mezclado con stdout. Esto es
particularmente relevante para el adapter porque `otto_pipeline.cpp` original escribe
profusamente a `stdout` con colores ANSI para depuración humana (`print_indicador`,
`std::cout << ...`) — ninguna de esas líneas debe sobrevivir en el adapter; deben redirigirse a
`stderr` o eliminarse si no aportan valor de diagnóstico.

## 8. Comandos entrantes y comportamiento esperado

| Comando | Tipo | Comportamiento esperado del adapter |
|---|---|---|
| `start` | proceso | Inicializa el adapter (sin abrir hardware todavía en R11 compile-only/mocks), emite `ready` con capabilities reflejando el modo (mock vs. real). |
| `health` | proceso | Responde `command_accepted`; no cambia estado. |
| `activate` | interacción | Inicia una interacción: dispara la secuencia wake-word→captura→STT→LLM→TTS→playback (real u orquestada sobre mocks según la fase), emitiendo los eventos de interacción correspondientes (§9). |
| `pause` | interacción | Pausa la interacción activa sin perder su `interaction_id`; en la lógica extraída de `otto_pipeline.cpp` esto no existe hoy (bucle continuo sin pausa) — el adapter debe introducir un punto de pausa seguro, diseño detallado diferido a R11. |
| `resume` | interacción | Reanuda desde el punto de pausa. |
| `stop` | interacción | Cancela la interacción activa de forma limpia, emite `cancelled` seguido de vuelta a `ready` (vía el propio supervisor, no el adapter). |
| `emergency_stop` | proceso | Ver §14 — cierre/latch seguro de proceso, nunca movimiento. |
| `close` | proceso | Cierre ordenado del proceso adapter, liberando cualquier recurso mock/real abierto. |

## 9. Eventos salientes y payload esperado

Los 14 eventos de `WorkerEventType`, todos ya definidos en `otto_jsonl_protocol.hpp`:

| Evento | Payload esperado |
|---|---|
| `ready` | `{capabilities...}` — 9 flags booleanos (`audio_capture`, `wake_word`, `vad`, `stt`, `local_llm`, `spanish_tts`, `physical_playback`, `physical_playback_stop`, `physical_playback_completion`), `true` solo cuando el componente real (no mock) está disponible. |
| `heartbeat` | `{}` — emitido periódicamente (ver §12), a diferencia del worker loopback de R8 que no lo hace. |
| `command_accepted` | `{"command": ..., "message_id": ...}` |
| `wake_word_confirmed` | `{}` — nuevo evento no usado por el loopback de R8; mapea a la detección de "hola otto" en `otto_pipeline.cpp::es_wake_word`. |
| `capture_started` | `{}` — mapea al inicio de `tomar_utterance` en el pipeline original. |
| `transcript_ready` | `{"text": ...}` — mapea al resultado de `transcribir()` (Whisper), tras pasar los filtros `es_alucinacion`/`es_texto_valido`/`es_consulta_coherente`. |
| `response_ready` | `{"text": ...}` — mapea al resultado de `ollama_query()`. |
| `playback_started` | `{}` — mapea al inicio de `otto_say()`. |
| `playback_completed` | `{"duration_s": ...}` — mapea al fin de `otto_say()` tras `PlayStop`. |
| `interaction_timeout` | `{}` — mapea al timeout de 30s en estado `ESCUCHANDO` (`TIMEOUT_SECS`). |
| `cancelled` | `{}` — mapea a `stop` recibido durante una interacción activa. |
| `failed` | `{"code": ..., "message": ...}` — ver §15. |
| `stopped` | `{}` |
| `closed` | `{}` |

## 10. Mapeo evento-por-evento desde `otto_pipeline.cpp`

| Estado/transición interna de `otto_pipeline.cpp` | Evento JSONL correspondiente |
|---|---|
| `HIBERNACION`, esperando wake word | Ninguno (proceso en `ready`, sin interacción activa) |
| `es_wake_word(t)` true | `wake_word_confirmed` seguido de la secuencia de `activate` |
| Transición a `ESCUCHANDO`, inicio de `tomar_utterance` | `capture_started` |
| `transcribir()` retorna texto válido (pasa filtros) | `transcript_ready` |
| `es_frase_salida`/`es_despedida` detectada | `cancelled` (interacción termina como salida de usuario, no como error) |
| `!es_texto_valido` o `!es_consulta_coherente` | `failed` con `interaction_id` (rechazo semántico, no error de proceso) seguido de reintento implícito (el pipeline original vuelve a escuchar; el adapter debe decidir si esto es un nuevo `transcript_ready` fallido o un evento de rechazo dedicado — diseño detallado diferido a R11, ver §19 gap) |
| `ollama_query()` retorna respuesta no vacía | `response_ready` |
| `ollama_query()` retorna vacío | `failed` con código dedicado (p. ej. `ERR_LLM_UNAVAILABLE`) |
| Inicio de `otto_say()` (llamada a Piper + `PlayStream`) | `playback_started` |
| Fin de `otto_say()` (tras `PlayStop`) | `playback_completed` |
| Timeout de 30s en `ESCUCHANDO` sin nueva voz | `interaction_timeout` |
| Vuelta a `HIBERNACION` tras despedida/timeout | Sin evento adicional — el supervisor ya vuelve a `READY` al recibir `cancelled`/`interaction_timeout`/`playback_completed`, según el caso |

Este mapeo es la contribución central de R10 y debe revisarse en el pre-push review (R10B,
propuesto) antes de servir de base para el código de R11.

## 11. Lifecycle del adapter

1. Proceso arranca, recibe `start` por stdin.
2. Inicializa recursos (reales o mock, según fase) sin bloquear indefinidamente.
3. Emite `ready` con capabilities reflejando exactamente qué está disponible.
4. Entra al loop de dispatch: por cada línea de stdin, procesa el comando, emite los eventos
   correspondientes.
5. En `close`, libera recursos ordenadamente, emite `closed`, termina con exit code 0.
6. En `emergency_stop`, ver §14.
7. En salida inesperada de cualquier hilo/recurso (p. ej. socket UDP cerrado externamente), el
   adapter debe fallar explícitamente (`failed`, proceso), nunca continuar en un estado
   ambiguo — mismo principio de fail-closed heredado del R7 §14 (Safety gates).

## 12. Heartbeat y health

A diferencia del worker loopback de R8 (que no emite heartbeat periódico automático — gap
documentado explícitamente en `IA_CXX_R8_PROTOCOL_COMPLIANT_LOOPBACK_WORKER.md` §10), el
adapter debe emitir `heartbeat` en un intervalo menor a `heartbeat_timeout_s` del supervisor
(default 5s), incluso durante una interacción activa de larga duración (p. ej. mientras espera
la respuesta de Ollama). Esto requiere un mecanismo de temporización dedicado (hilo o timer),
diseño detallado de implementación diferido a R11. `health` simplemente responde
`command_accepted` sin alterar el estado — el estado real se refleja en la cadencia de
`heartbeat` y en `ready`/`failed`.

## 13. Pause/resume/cancel/stop

`otto_pipeline.cpp` original no tiene ningún concepto de pausa — su bucle es continuo desde
`HIBERNACION` hasta `ESCUCHANDO`/`PROCESANDO` sin puntos de interrupción externos. El adapter
debe introducir un punto de pausa seguro (p. ej. entre la finalización de una fase — captura,
STT, LLM, TTS — y el inicio de la siguiente) sin interrumpir abruptamente una operación en
curso de forma insegura (p. ej. cortar `PlayStream` a mitad de un chunk de audio). El diseño
exacto de dónde se insertan esos puntos de pausa queda para R11, pero el principio guía es: la
pausa nunca debe dejar hardware (parlante, socket) en un estado indefinido.

`stop`/`cancel` sí tiene un análogo directo: `es_frase_salida`/`es_despedida` ya interrumpen
limpiamente el flujo en el pipeline original, y ese mismo mecanismo puede mapearse a `stop`
recibido externamente vía JSONL.

## 14. Emergency stop sin movimiento

`emergency_stop` debe producir un cierre/latch seguro de proceso, exactamente como lo hace ya
el worker loopback de R8 (transición a `stopped`, terminación limpia). `otto_pipeline.cpp`
original no tiene ningún mecanismo de parada externa — el adapter debe introducir un punto de
interrupción seguro que:

- detenga inmediatamente cualquier reproducción de audio en curso (`PlayStop` si hay una
  reproducción activa);
- no invoque ningún control de movimiento ni actuador — `otto_pipeline.cpp` no controla
  locomoción, únicamente audio, así que esto es una propiedad ya garantizada por el alcance del
  archivo original, pero debe verificarse explícitamente en R11 antes de cualquier prueba;
- termine el proceso de forma determinística, sin dejar el hardware de audio en un estado
  activo.

`emergency_stop` está explícitamente prohibido de publicar `/cmd_vel`, `/odom` o `/tf` — estos
tópicos no tienen relación alguna con el dominio de audio/conversación de `otto_pipeline.cpp` y
no deben introducirse en el adapter bajo ninguna circunstancia.

## 15. Manejo de errores y `failed` events

El adapter debe usar `failed` (payload `{"code": ..., "message": ...}`) para todo caso donde
`otto_pipeline.cpp` original simplemente reintentaba silenciosamente o pedía repetir (p. ej.
`ollama_query()` vacío → `frase_aleatoria(REPITE)`). El principio fail-closed heredado del R7
§14 aplica: si un componente real (o mock) falla o no está disponible, el adapter debe emitir
`failed` explícito, nunca simular una respuesta como si fuera genuina. Los códigos de error
concretos (p. ej. `ERR_STT_UNAVAILABLE`, `ERR_LLM_UNAVAILABLE`, `ERR_TTS_UNAVAILABLE`) se
definen en R11 junto con la implementación real.

## 16. Configuración futura

`otto_pipeline.cpp` original hardcodea toda su configuración vía macros de compilación (rutas
de modelo Whisper, voz Piper, IP/puerto multicast, umbrales RMS). El adapter, al envolver esa
lógica, debería eventualmente exponer esa configuración de forma parametrizable (variables de
entorno o archivo de configuración leído al arranque), sin cambiar el comportamiento por
defecto del pipeline ya validado. El mecanismo exacto (env vars vs. archivo) es una decisión
diferida a R11 — no se fija aquí para no restringir prematuramente el diseño de implementación.

## 17. Mocks necesarios para R11

Para validar el dispatch loop del adapter sin ningún componente real, R11 (si se aprueba) debe
introducir mocks para:

- **Captura de audio**: sustituir la captura UDP multicast real por una fuente de audio
  pregrabado o sintético, inyectada de forma determinística.
- **Whisper STT**: sustituir `whisper_full()` por una función que retorna texto fijo o
  configurable por escenario, análogo a como el loopback worker de R8 retorna `"hola"` fijo.
- **Ollama LLM**: sustituir la llamada HTTP real a `127.0.0.1:11434` por una función que
  retorna una respuesta fija o configurable, sin abrir ningún socket real.
- **Piper TTS + AudioClient**: sustituir `system()` (Piper) y
  `unitree::robot::g1::AudioClient::PlayStream`/`PlayStop` por una función que simplemente
  marca la reproducción como completada tras una espera simulada, sin generar audio real ni
  tocar el SDK Unitree.

Todos estos mocks deben vivir bajo `codigo ottoguide/src/interaction/cxx_runtime/`, nunca bajo
`docs/legacy/**`, y no deben requerir ninguna dependencia real (Whisper/Ollama/Piper/Unitree
SDK) para compilar ni ejecutar.

## 18. Archivos que podrían crearse en R11

```text
codigo ottoguide/src/interaction/cxx_runtime/src/otto_pipeline_adapter.cpp   (o nombre similar)
codigo ottoguide/src/interaction/cxx_runtime/include/otto_pipeline_adapter.hpp
codigo ottoguide/src/interaction/cxx_runtime/src/otto_jsonl_shim.cpp         (implementación real del dispatch loop, reemplazando el stub actual)
codigo ottoguide/src/interaction/cxx_runtime/src/mocks/*.cpp                 (mocks de §17)
codigo ottoguide/src/interaction/cxx_runtime/tests/*.cpp                     (tests de framing/dispatch del adapter)
docs/Arquitectura/IA_CXX_R11_*.md
```

Ningún archivo de esta sección se crea en R10.

## 19. Archivos que no deben tocarse todavía

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

**Gap explícito no resuelto en R10**: la sección §10 identifica un punto de diseño abierto — si
un rechazo semántico (`!es_texto_valido`/`!es_consulta_coherente`) debe mapearse a `failed` con
reintento implícito, o si el protocolo necesita un evento dedicado no presente hoy en
`WorkerEventType`. Esta decisión requiere alinearse primero con `runtime_port.py` (posiblemente
sin cambios, reutilizando `failed` con un código específico) antes de que R11 la implemente —
no se resuelve en este documento para evitar prescribir un cambio de protocolo sin su propio
checkpoint dedicado si resultara necesario.

## 20. Gates antes de build

```text
- Este diseño (R10) revisado y aprobado (checkpoint tipo R10B, pre-push review).
- Ningún target existente de CMakeLists.txt modificado sin autorización explícita separada.
- Ninguna dependencia de Whisper/Ollama/Piper/Unitree SDK introducida en el adapter real —
  únicamente en mocks, y solo si R11 así lo decide explícitamente.
- Hash forense de otto_pipeline.cpp verificado antes y después de cualquier build (no debe
  cambiar, ya que R11 no lo modifica, solo lo envuelve).
```

## 21. Gates antes de ejecución offline

```text
- Build compile-only ya validado con exit code 0, sin warnings.
- Ejecución exclusivamente contra los mocks de §17 (sin Whisper/Ollama/Piper/Unitree reales).
- Timeout estricto en toda ejecución (patrón ya usado en R6/R8: 3s o similar acotado).
- Confirmación explícita literal separada para la fase de ejecución, no heredada de la fase de
  build ni de este checkpoint de diseño.
```

## 22. Gates antes de integración con componentes reales

```text
- Toda la validación contra mocks (dispatch loop, heartbeat, pause/resume, emergency_stop,
  manejo de errores) debe estar 100% verde antes de introducir cualquier componente real.
- Cada componente real (Whisper, luego Ollama, luego Piper, luego Unitree AudioClient) se
  integra en su propio checkpoint separado, uno a la vez, nunca todos simultáneamente.
- Cada integración real requiere su propia confirmación explícita literal.
```

## 23. Gates antes de robot/HIL

```text
- Nivel D explícito, no acelerable (ninguna variante "-FAST" permitida, según AGENTS.md
  vigente — el fast-track de POLICY-DOCS-FAST-R1 aplica solo a documentación pura y nunca a
  Nivel D).
- Autorización HIL separada e independiente de cualquier autorización de código/build/
  ejecución/integración previa.
- Presencia y supervisión humana directa confirmada antes de cualquier movimiento o audio real
  en el robot.
- emergency_stop (§14) verificado exhaustivamente contra mocks y contra componentes reales
  offline antes de habilitarse contra hardware real.
```

## 24. Riesgos

- **Riesgo de mapeo incompleto en §10**: el gap documentado en §19 (rechazo semántico sin
  evento dedicado claro) podría descubrirse insuficiente durante la implementación de R11,
  requiriendo una decisión de protocolo no anticipada aquí.
- **Riesgo de introducir concurrencia prematura**: el pipeline original usa un hilo dedicado
  para captura UDP; replicar esa concurrencia en el adapter antes de validar el dispatch loop
  básico contra mocks síncronos aumentaría la superficie de bugs difíciles de diagnosticar.
- **Riesgo de acoplar mocks al hardware real por accidente**: si los mocks de §17 comparten
  código con las rutas reales de forma descuidada, un bug en el mock podría enmascarar un bug
  en la ruta real o viceversa.
- **Riesgo de que R11 intente saltar directamente a integración real**: sin los gates
  diferenciados de §20-§23, existe la tentación de compilar contra el SDK real antes de agotar
  la validación offline.

## 25. Mitigaciones

- El gap de §19 se resuelve explícitamente al inicio de R11 (o en un R10B/R10C de revisión) con
  su propia decisión documentada, antes de escribir el código de mapeo.
- La concurrencia real se difiere a un checkpoint posterior a R11, después de que el dispatch
  loop síncrono contra mocks esté completamente probado.
- Los mocks de §17 se implementan como módulos completamente separados (no ramas condicionales
  dentro del mismo código de producción), para que un bug de mock no pueda enmascarar
  comportamiento real y viceversa.
- Los gates de §20-§23 son secuenciales y cada uno requiere su propia confirmación explícita
  literal — ningún checkpoint puede saltar etapas sin una variante "-FAST" explícita, y Nivel D
  nunca admite fast-track.

## 26. Criterios de aceptación para R11

Para que R11 (si se ejecuta) se considere exitoso, deberá demostrar:

1. El dispatch loop real en `otto_jsonl_shim.cpp` (o archivo equivalente) habla el protocolo
   JSONL exactamente igual que el loopback worker de R8 (mismos wire strings, mismo framing,
   misma validación de envelope).
2. Los mocks de §17 permiten ejercitar los 8 comandos y al menos los 14 eventos de §9 sin
   ningún componente real.
3. `heartbeat` se emite periódicamente incluso durante una interacción activa simulada de larga
   duración.
4. `emergency_stop` produce cierre limpio verificable sin movimiento, contra mocks.
5. `otto_pipeline.cpp` permanece sin modificar, con su hash forense intacto, salvo que un
   checkpoint futuro explícitamente autorizado decida lo contrario con su propia justificación.
6. Ningún comando/evento del protocolo se reimplementa en Python.

## 27. Próximo checkpoint recomendado

`IA-CXX-R11_IMPLEMENT_JSONL_SHIM_COMPILE_ONLY_NO_ROBOT` — Nivel C, NO fast-track (ya toca
código C++), con confirmaciones explícitas separadas por fase (código, build, ejecución
offline contra mocks), sin robot, sin tocar `otto_pipeline.cpp` salvo autorización específica.

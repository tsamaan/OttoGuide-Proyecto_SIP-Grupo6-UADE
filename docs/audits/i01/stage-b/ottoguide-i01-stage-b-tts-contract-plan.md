# OttoGuide I-01 Stage B — Plan de Contrato TTS

## 1. Resultado

```
RESULT = I01_STAGE_B_TTS_CONTRACT_PLAN_V3_DOCUMENTATION_CORRECTED_READY_FOR_HUMAN_APPROVAL
TASK   = PLAN_I01_STAGE_B_TTS_CONTRACT
CONTRACT_VERSION = 3
```

---

## 2. Baselines verificados

```
DESIGN_REPORT_HASH_MATCH               = YES
  expected: 7AC7CFEAC8D22AD9A94D85D08853EC65835F4E6A36B46BD6E849D5FA19374980
  actual:   7AC7CFEAC8D22AD9A94D85D08853EC65835F4E6A36B46BD6E849D5FA19374980

STAGE_A_PLAN_HASH_MATCH                = YES
  expected: 50C5DC151A5E5B2C550B4416ABED13158667AAB50B0ADC49F9EB945EDA549CBD
  actual:   50C5DC151A5E5B2C550B4416ABED13158667AAB50B0ADC49F9EB945EDA549CBD

STAGE_A_IMPLEMENTATION_REPORT_HASH_MATCH = YES
  expected: 5C1855D715A4C253F1F0C26965B48222B967EB7663A91A29122000A9176F2627
  actual:   5C1855D715A4C253F1F0C26965B48222B967EB7663A91A29122000A9176F2627

STAGE_A_SELF_REVIEW_REPORT_HASH_MATCH  = YES
  expected: 2E7894A6437D706A62A9062110C50D835B367772B606A1C273B514409BB582D8
  actual:   2E7894A6437D706A62A9062110C50D835B367772B606A1C273B514409BB582D8

STAGE_A_COMMIT_REPORT_HASH_MATCH       = YES
  expected: 2DFFB1404484A58C84A7AA052177719476C08A732F9DA8270929C8CA2B4933BB
  actual:   2DFFB1404484A58C84A7AA052177719476C08A732F9DA8270929C8CA2B4933BB

STAGE_B_PLAN_PRE_EXISTED = NO
```

---

## 3. Estado Git

```
REPOSITORY_TOPLEVEL = C:/Users/lucas/Documents/OttoGuide-Lucas/
                      OttoGuide-Unification/worktrees/integration-phase6
BRANCH              = review/orchestrator-unification
HEAD                = 68967c85e0063e0b4d08b9411ff8431941ad2a35
HEAD_PARENT         = 2ef63ebaa987cff34f722c521da4aeeeb5ba2646
WORKTREE_CLEAN      = YES
TRACKED_MODIFIED_COUNT = 0
STAGED_COUNT           = 0
UNTRACKED_COUNT        = 0
MERGE_IN_PROGRESS      = NO
REBASE_IN_PROGRESS     = NO
CHERRY_PICK_IN_PROGRESS = NO
REVERT_IN_PROGRESS     = NO
```

---

## 4. Archivos inspeccionados

```
CURRENT_TTS_INTERFACE_PATH        = codigo ottoguide/src/interaction/tts_unitree_client.py
CURRENT_PIPER_IMPLEMENTATION_PATH = codigo ottoguide/src/interaction/tts_unitree_client.py (PiperTTSAdapter)
CURRENT_UNITREE_IMPLEMENTATION_PATH = codigo ottoguide/src/interaction/tts_unitree_client.py (UnitreeTTSAdapter)
CURRENT_FACTORY_PATH              = codigo ottoguide/src/interaction/tts_unitree_client.py (tts_adapter_factory)
CURRENT_CONVERSATION_CALLER_PATHS = codigo ottoguide/src/interaction/conversation_manager.py
                                    (LocalNLPPipeline, CloudNLPPipeline, ConversationManager)
CURRENT_ENTRYPOINT_PATHS          = codigo ottoguide/main.py
CURRENT_SETTINGS_PATHS            = codigo ottoguide/config/settings.py
CURRENT_AUDIO_TEST_PATHS          =
  codigo ottoguide/tests/unit/test_audio_characterization.py
  codigo ottoguide/tests/unit/test_audio_char_unitree.py
  codigo ottoguide/tests/unit/test_conversation_playback_lifecycle.py
```

---

## 4A. Reconstrucción del ciclo de vida en runtime

Esta sección establece la arquitectura real tal como existe en producción. Es la base sobre la que se construye el contrato objetivo.

### 4A.1 Fases del ciclo de vida de una solicitud TTS

```
REQUEST_TASK         = asyncio.Task que ejecuta synthesize_and_play()
SYNTHESIS_FUTURE     = Future que envuelve _run_piper_synthesis() en cpu_executor
PROCESS_POOL_WORK    = función top-level _run_piper_synthesis() corriendo en ProcessPoolExecutor
PLAYBACK_TASK        = asyncio.Task que ejecuta _run_alsa_playback() (método async de LocalNLPPipeline)
THREAD_POOL_WORK     = función top-level _play_audio_alsa() corriendo en ThreadPoolExecutor
```

### 4A.2 Relación de funciones y métodos

```
_run_piper_synthesis(text, model_path, sample_rate) -> NDArray[float32]
  TIPO       = función top-level (módulo conversation_manager)
  EJECUTOR   = ProcessPoolExecutor (cpu_executor)
  REQUSITO   = pickle-compatible (satisfecho — top-level)
  CANCELABLE = NO — Task cancel detiene el Future pero no el proceso OS

_play_audio_alsa(pcm_float32, sample_rate, block_size) -> None
  TIPO       = función top-level (módulo conversation_manager)
  EJECUTOR   = ThreadPoolExecutor (audio_executor)
  INTERNO    = sounddevice.OutputStream + threading.Event (finished_event)
  CANCELABLE = NO — Task cancel detiene el coroutine wrapper pero no el hilo OS

_run_alsa_playback(self, pcm_float32, sample_rate, block_size) -> None
  TIPO       = método ASYNC de LocalNLPPipeline (y CloudNLPPipeline)
  CÓDIGO     = await loop.run_in_executor(self._audio_executor, _play_audio_alsa, ...)
  CANCELABLE = SÍ a nivel asyncio.Task (cancela el await, no el hilo)
```

### 4A.3 Semántica de cancel en asyncio.Task vs. executor workers

```
asyncio.Task.cancel():
  → Inyecta CancelledError en el próximo punto await del coroutine
  → NO detiene el worker en ThreadPoolExecutor ni ProcessPoolExecutor
  → El worker continúa hasta completar; su resultado se descarta

Implicación para stop():
  → stop() PUEDE cancelar la asyncio.Task de playback (efecto asyncio observable)
  → stop() NO puede detener el hilo ALSA (sounddevice puede continuar hasta consumir el buffer PCM completo o hasta fallo del dispositivo)
  → stop() NO puede detener el proceso piper en cpu_executor
  → El nombre BEST_EFFORT es preciso y obligatorio
```

### 4A.4 Semántica fire-and-forget de synthesize_and_play

```
synthesize_and_play(text):
  1. await asyncio.wait_for(loop.run_in_executor(cpu_executor, _run_piper_synthesis, ...))
     → BLOQUEANTE para el caller hasta que PCM esté listo o timeout
  2. task = asyncio.create_task(_run_alsa_playback(...))
  3. _track_playback_task(task)
  4. return  ← AQUÍ RETORNA — no espera que el audio suene

Consecuencia crítica:
  → Errores de playback NUNCA llegan al caller de synthesize_and_play
  → _on_playback_done() los captura vía done_callback → LOGGER.warning
  → TTSPlaybackError NO es observable por el caller
```

### 4A.5 Mock boundaries para tests de contrato

```
Para tests que verifican is_active durante playback:
  CORRECTO   = mockear adapter._run_alsa_playback (el método async)
               → asyncio.Event controla el bloqueo sin cruzar fronteras de executor
  INCORRECTO = mockear _play_audio_alsa (función sync en ThreadPoolExecutor)
               → asyncio.Event no puede bloquear un hilo OS
               → asyncio.sleep() no puede awaited en contexto sync

Para tests que verifican comportamiento durante síntesis lenta:
  CORRECTO   = mockear _run_piper_synthesis → time.sleep() para simular lentitud
               O: rediseñar test para controlar en fase de playback (más determinista)
  INCORRECTO = asyncio.sleep() en el mock de _run_piper_synthesis
               → asyncio.sleep es coroutine; no puede ejecutarse en ProcessPool worker
```

### 4A.6 Mecanismo de supresión de resultados obsoletos (generation counter)

```
Problema:
  synthesize_and_play("primera") está en await de síntesis
  stop() es llamado → cancela playback tasks → _synthesis_active = False
  El proceso en cpu_executor continúa → síntesis termina → _run_piper_synthesis retorna
  La coro de "primera" reanuda → intenta registrar playback task
  Resultado: "primera" inicia playback a pesar de stop() previo

Solución — _request_generation counter:
  _request_generation: int = 0  [atributo del adapter]

  synthesize_and_play(text):
    self._request_generation += 1
    my_generation = self._request_generation
    ...
    pcm = await asyncio.wait_for(...)  # síntesis
    if my_generation != self._request_generation:
        return  # ← supresión de resultado obsoleto; no registra playback
    task = asyncio.create_task(_run_alsa_playback(...))
    _track_playback_task(task)

  stop():
    self._request_generation += 1  # invalida cualquier síntesis en vuelo
    # cancela tasks existentes
    ...
```

---

## 5. Contrato vigente

### 5.1 TTSAdapter (abstracta)

**Archivo**: `tts_unitree_client.py:50`

| Campo | Valor |
|---|---|
| PUBLIC_OPERATION | `async speak(text: str) -> None` |
| PUBLIC_OPERATION | `@property backend_name -> str` |
| SYNC_OR_ASYNC | async (speak); sync (backend_name) |
| RETURN_TYPE | None |
| BLOCKING_BOUNDARY | `loop.run_in_executor(None, ...)` — executor por defecto en ambas implementaciones |
| TASK_OWNERSHIP | Ninguna — no crea Tasks |
| CANCELLATION_BEHAVIOR | asyncio.CancelledError propagado; el hilo en executor continúa |
| CONCURRENCY_BEHAVIOR | NO DEFINIDA — sin lock ni política explícita |
| STATE_OBSERVABILITY | NINGUNA — sin `is_speaking`/`speaking` ni estado público; `is_active` pertenece al contrato objetivo de Stage B |
| ERROR_BEHAVIOR | Excepciones capturadas genericamente en subclases; sin jerarquía tipada |
| CLEANUP_BEHAVIOR | SIN close() — recursos no liberados explícitamente |

### 5.2 PiperTTSAdapter

**Archivo**: `tts_unitree_client.py:80`

- Backend: Docker + paplay (ruta de desarrollo/notebook)
- `speak()` → `loop.run_in_executor(None, _speak_sync, text)`
- `_speak_sync()`:
  - `tempfile.mkstemp` → `docker cp` → `docker exec sh -c piper_cmd` → `docker cp` back → `subprocess.Popen(paplay)` → `_wait_for_playback_end()` polling `pactl` → `time.sleep(0.5)`
- TIMEOUT en docker: `check=False` en todos los `subprocess.run` — sin timeout explícito
- STOP: Sin implementación; hilo continúa hasta que `paplay` + `time.sleep` terminan
- IS_SPEAKING: No
- CLOSE: No
- EXCEPCIONES: capturadas en bloque `except Exception as exc` → `LOGGER.warning`; limpieza de tempfile en finally

### 5.3 UnitreeTTSAdapter

**Archivo**: `tts_unitree_client.py:218`

- Backend: `AudioClient.TtsMaker()` — SDK Unitree nativo (modo robot HIL)
- `speak()` → `loop.run_in_executor(None, _speak_sync, text)`
- `_speak_sync()`:
  - Inicialización lazy de `AudioClient` si `_client is None` (import lazy de `unitree_sdk2py`)
  - Si `_client is None` tras init: log warning, return silencioso
  - Captura `tts_index` → `self._client.TtsMaker(text, self._language)` → wrapper defensivo verifica incremento +1
  - Si incremento != 1: log CRITICAL + corrige `tts_index` directamente (parche al bug SDK)
- STOP: Sin implementación; `TtsMaker()` es fire-and-forget
- IS_SPEAKING: No
- CLOSE: No
- EXCEPCIONES: `except Exception as exc` → `LOGGER.warning`; `_client` queda en estado indeterminado tras error

**Nota sobre PlayStop()**: Ambas copias del SDK (`libs/unitree_sdk2_python-master/` y `libs/unitree_sdk2_python/`) contienen `PlayStop(app_name: str)` que usa `ROBOT_API_ID_AUDIO_STOP_PLAY`. La compatibilidad de `PlayStop()` con audio iniciado por `TtsMaker()` es DESCONOCIDA sin acceso HIL. No se invoca en Stage B.

### 5.4 tts_adapter_factory

**Archivo**: `tts_unitree_client.py:360`

```python
def tts_adapter_factory(*, robot_mode: str = "mock") -> TTSAdapter:
    if robot_mode == "real":
        return UnitreeTTSAdapter()
    else:
        return PiperTTSAdapter()
```

- Existe y funciona (caracterizado por AUDIO-CHAR-004)
- **NO ESTÁ CONECTADA** a `LocalNLPPipeline` ni a `ConversationManager`
- Solo se usa en tests de caracterización

### 5.5 LocalNLPPipeline (caller principal, ruta de síntesis activa)

**Archivo**: `conversation_manager.py:285`

```
synthesize_and_play(text: str) -> None  [async]
  → loop.run_in_executor(cpu_executor, _run_piper_synthesis, text, model_path, AUDIO_SAMPLE_RATE)
      [asyncio.wait_for(timeout=TTS_TIMEOUT_S)]
  → _track_playback_task(_run_alsa_playback(pcm, rate, block_size), name="tts-alsa-playback")

_run_piper_synthesis(text, model_path, sample_rate) -> NDArray[float32]
  [módulo top-level, ProcessPoolExecutor, piper Python library ONNX]

_play_audio_alsa(pcm_float32, sample_rate, block_size) -> None
  [módulo top-level, ThreadPoolExecutor, sounddevice OutputStream + queue]

_run_alsa_playback(self, pcm_float32, sample_rate, block_size) -> None  [MÉTODO ASYNC]
  [método de instancia en LocalNLPPipeline; wraps _play_audio_alsa en audio_executor]

_playback_tasks: set[asyncio.Task[None]]  [privado]

close() -> None  [sync]
  → cancela tasks en _playback_tasks
  → shutdown(wait=False, cancel_futures=True) de cpu_executor y audio_executor si propios
```

| Campo | Valor |
|---|---|
| TASK_OWNERSHIP | Tasks creadas con `asyncio.create_task`; registradas en `_playback_tasks`; limpiadas con `done_callback` |
| CANCELLATION_BEHAVIOR | `task.cancel()` cancela el Task de asyncio; el hilo en ThreadPoolExecutor continúa hasta que ALSA termina |
| CONCURRENCY_BEHAVIOR | **ALLOW_CONCURRENT** — cada llamada a `synthesize_and_play` crea una nueva Task sin cancelar las anteriores |
| STATE_OBSERVABILITY | `_playback_tasks` (privado); NO existe `is_speaking` ni `speaking` público (AUDIO-CHAR-011) |
| ERROR_BEHAVIOR | Síntesis: TimeoutError propagado al caller (generate() lo captura); Playback: excepción en done_callback → LOGGER.warning |
| CLEANUP_BEHAVIOR | `close()` sincrónico; cancela Tasks pero no espera su terminación; executor shutdown sin espera |

### 5.5A Separación histórica Stage A / contrato objetivo Stage B

```
HISTORICAL_STAGE_A_STATE = No public is_speaking/speaking property, según AUDIO-CHAR-011.
TARGET_STAGE_B_STATE = is_active es la propiedad lógica recomendada para el nuevo contrato.
AUDIO_CHAR_011_HISTORICAL_TERMINOLOGY_CORRECT = YES
```

### 5.6 ConversationManager.close()

**Archivo**: `conversation_manager.py:1362`

- Sincrónico (def, no async)
- Llama `_local.close()` → `_cloud.close()` (si existe)
- NO espera tareas pendientes

---

## 6. Mapa de callers

### 6.1 Callers de `synthesize_and_play`

| CALLER_PATH | CALLER_SYMBOL | CALL_STYLE | AWAITED | ERROR_HANDLING |
|---|---|---|---|---|
| `conversation_manager.py:507` | `LocalNLPPipeline.generate` | `await self.synthesize_and_play(answer_text)` | SÍ | `except Exception` → log warning, degradación silenciosa |
| `conversation_manager.py:1079` | `ConversationManager.process_scripted_interaction` | `await self._local.synthesize_and_play(script_text)` | SÍ | Sin try/except local (propaga al caller) |
| `conversation_manager.py:1320` | `ConversationManager._process_llm_qa_interaction` | `await self._local.synthesize_and_play(message)` | SÍ | `except Exception` → pass |
| `conversation_manager.py:1333` | `ConversationManager._process_llm_qa_interaction` | `await self._local.synthesize_and_play(fallback)` | SÍ | `except Exception` → pass |
| `conversation_manager.py:1353` | `ConversationManager._process_llm_qa_interaction` | `await self._local.synthesize_and_play(fallback)` | SÍ | `except Exception` → pass |

### 6.2 Callers de `tts_adapter_factory`

| CALLER_PATH | CALLER_SYMBOL | NOTAS |
|---|---|---|
| `test_audio_characterization.py:75` | `test_audio_char_004_*` | Solo en tests; monkey-patched |
| `test_audio_characterization.py:155` | `test_audio_char_004_*` | Solo en tests; assertion sobre tipos |

`tts_adapter_factory` NO está invocada en producción (main.py ni ConversationManager).

### 6.3 Callers de TTSAdapter.speak()

| CALLER_PATH | NOTAS |
|---|---|
| Ninguno en producción | `speak()` no se invoca desde ConversationManager ni main.py |
| Solo en tests que crean PiperTTSAdapter/UnitreeTTSAdapter directamente | |

### 6.4 Respuestas a preguntas del spec §15

1. **¿Qué componente sintetiza actualmente?** `LocalNLPPipeline` mediante `_run_piper_synthesis` (piper ONNX library) en `cpu_executor` (ProcessPoolExecutor).
2. **¿Qué componente reproduce actualmente?** `LocalNLPPipeline` mediante `_play_audio_alsa` (sounddevice/ALSA) en `audio_executor` (ThreadPoolExecutor), envuelto por el método async `_run_alsa_playback`.
3. **¿Quién crea y destruye el adapter?** Nadie en producción — `tts_adapter_factory` no está wired. `LocalNLPPipeline` NO posee un adapter TTS.
4. **¿Quién debe poseer el lifecycle futuro?** Por diseño Stage B: el adapter mismo (`close()` propio) + el factory/ConversationManager para creación.
5. **¿Existe más de un camino TTS activo?** SÍ — dos caminos paralelos: (a) `LocalNLPPipeline.synthesize_and_play` (piper ONNX + ALSA, ruta real); (b) `PiperTTSAdapter.speak` (Docker + paplay, ruta desarrollo).
6. **¿La factory está conectada?** NO — existe y es correcta pero no se invoca en producción.
7. **¿Cambio mínimo para migrar sin big-bang?** Agregar `stop()`, `is_active`, `close()` a `TTSAdapter`; implementar en subclases; conectar factory a `LocalNLPPipeline` en paso separado controlado.

---

## 7. Problemas del contrato vigente

| PROBLEMA_ID | DESCRIPCIÓN | IMPACTO |
|---|---|---|
| P-01 | `TTSAdapter.speak()` es la única operación pública; no hay `synthesize_and_play`, `stop`, propiedad lógica pública del contrato objetivo, ni `close`. El contrato no es observable ni controlable desde el exterior. | Alto — callers no pueden saber si el robot está hablando |
| P-02 | `tts_adapter_factory` no está conectada. La ruta de síntesis real (piper ONNX + ALSA) vive en `LocalNLPPipeline`, paralela al adapter. El patrón Strategy no se cumple en producción. | Alto — la abstracción de adapter es efectivamente letra muerta |
| P-03 | Política de concurrencia `ALLOW_CONCURRENT` implícita. Llamadas concurrentes a `synthesize_and_play` producen audio solapado. Sin documentación ni control explícito. | Medio — degradación de UX en tours |
| P-04 | Sin `stop()`. Para detener audio es necesario cancelar el Task directamente o llamar `close()` (que también apaga los executors). No hay mecanismo intermedio. | Alto — impide interrumpir al robot durante una emergencia sin shutdown completo |
| P-05 | Sin excepciones tipadas. Todos los errores de síntesis y reproducción se absorben con `except Exception → LOGGER.warning`. El caller no puede distinguir error de síntesis vs. adapter cerrado. | Medio — dificulta diagnóstico y recuperación |
| P-06 | El runtime caracterizado por Stage A no exponía una propiedad pública `is_speaking` ni `speaking`; la actividad solo era observable mediante `_playback_tasks` privado. Los tests de Stage A acceden a `pipeline._playback_tasks` directamente (white-box). El contrato objetivo de Stage B recomienda `is_active` como propiedad lógica pública. | Medio — tests frágiles ante refactor |
| P-07 | `close()` sincrónico en `LocalNLPPipeline` cancela Tasks pero no espera su terminación. Si ALSA está reproduciendo, el hilo continúa brevemente después del close. | Bajo — potencial de resource leak en shutdown rápido |
| P-08 | `UnitreeTTSAdapter._client` permanece `None` sin señal de error si el SDK no está disponible. No hay distinción entre "no inicializado" y "SDK no disponible". | Bajo — dificulta diagnóstico en entorno HIL |
| P-09 | `PiperTTSAdapter._speak_sync` usa `time.sleep(0.5)` bloqueante dentro del executor. Este delay no es configurable ni cancelable. | Bajo — latencia innecesaria post-síntesis |
| P-10 | Sin `capabilities` explícitas. No hay forma de preguntar si un adapter soporta `stop()` efectivo o reporte confiable de actividad lógica antes de usarlo. | Bajo-Medio — necesario para integración limpia con Unitree |

---

## 8. Alternativas evaluadas

### 8.1 Alternativa A: Mantener TTSAdapter separado de LocalNLPPipeline (status quo extendido)

Agregar `stop`, `is_active`, `close` solo a la jerarquía `TTSAdapter` (PiperTTSAdapter, UnitreeTTSAdapter) sin tocar `LocalNLPPipeline`. La factory sigue sin conectarse.

**Pros**: Mínimo blast radius. Los tests de Stage A no se tocan.
**Contras**: Perpetúa P-02 (factory no wired). El nuevo contrato rico existe pero no se usa en producción. Etapa B se vuelve un ejercicio de papel sin efecto real en el comportamiento del robot.

**DECISIÓN**: DESCARTADA para Stage B completo. Aceptable como paso intermedio (B2-B4) antes de la migración de callers (B5).

### 8.2 Alternativa B: LocalNLPPipeline implementa TTSAdapter

`LocalNLPPipeline` se convierte en subclase concreta de `TTSAdapter`. La síntesis ONNX + ALSA se mueve al adapter.

**Pros**: Un único contrato, una única jerarquía.
**Contras**: Rompe el patrón Strategy — `LocalNLPPipeline` también tiene `generate()`, `transcribe()`, etc. Cambio de clase masivo. Violaría principio de responsabilidad única.

**DECISIÓN**: DESCARTADA. Responsabilidades demasiado distintas.

### 8.3 Alternativa C: Nuevo adapter local (LocalPiperTTSAdapter) absorbiendo la ruta ONNX

Crear `LocalPiperTTSAdapter(TTSAdapter)` que encapsula `_run_piper_synthesis` + `_play_audio_alsa`. `LocalNLPPipeline` instancia este adapter y delega `synthesize_and_play`.

**Pros**: La ruta real de producción queda en el adapter. La factory se puede conectar limpiamente. `LocalNLPPipeline` se simplifica.
**Contras**: Duplicación temporaria durante la migración. Requiere mover `_run_piper_synthesis` y `_play_audio_alsa` (funciones top-level en `conversation_manager.py`) a `tts_unitree_client.py` o a un nuevo módulo.

**DECISIÓN**: RECOMENDADA para el objetivo final (Stage B5). Es la decisión humana H-01.

### 8.4 Alternativa D: TTSController wrapper

Clase `TTSController` que envuelve cualquier `TTSAdapter` y agrega control de concurrencia, `is_active` y `stop`. `LocalNLPPipeline` recibe un `TTSController`.

**Pros**: No modifica TTSAdapter. Separación limpia de concerns.
**Contras**: Agrega una clase extra en la cadena. La observabilidad (`is_active`) duplica estado entre adapter y controller. Aumenta complejidad sin resolver P-02.

**DECISIÓN**: DESCARTADA. La complejidad no justifica el beneficio.

---

## 9. Contrato objetivo recomendado

### 9.1 Arquitectura Piper inequívoca

```
H-01_RECOMMENDED_OPTION = DEDICATED_LOCAL_PIPER_ADAPTER
PIPER_ADAPTER_ARCHITECTURE = SPLIT_LOCAL_ONNX_ALSA_FROM_DOCKER_WAV_PAPLAY
```

Componentes canónicos de Stage B:

| COMPONENTE | RESPONSABILIDAD | UBICACIÓN RECOMENDADA | ESTADO |
|---|---|---|---|
| `TTSAdapter` | Contrato público común, errores, capabilities y defaults transitorios | `src/interaction/tts_contract.py` | Nuevo contrato base |
| `LocalPiperTTSAdapter` | Piper ONNX en memoria + reproducción PCM vía ALSA/sounddevice; extracción futura de la ruta embebida en `LocalNLPPipeline` | `src/interaction/tts_piper_local.py` | Nuevo adapter recomendado |
| `PiperDockerTTSAdapter` | Docker `ottoguide-tts` + WAV + `paplay`; ruta de desarrollo existente | `src/interaction/tts_piper_docker.py` | Renombre explícito del adapter Docker actual |
| `UnitreeTTSAdapter` | `AudioClient.TtsMaker()` solamente | `src/interaction/tts_unitree_adapter.py` | Adapter Unitree offline/HIL |

**HECHO VERIFICADO**: el símbolo actual `PiperTTSAdapter` en `tts_unitree_client.py` no es el adapter Piper ONNX/ALSA; es Docker + WAV + `paplay`. La ruta Piper ONNX/ALSA vigente está embebida en `LocalNLPPipeline` (`_run_piper_synthesis`, `_run_alsa_playback`, `_play_audio_alsa`).

**RECOMENDACIÓN DE DISEÑO**: no transformar silenciosamente `PiperTTSAdapter` en Local Piper. En B4, el símbolo público existente debe preservarse como alias temporal o reexport de `PiperDockerTTSAdapter`, con deprecación documentada. La migración que elimine el alias queda diferida a una etapa posterior.

### 9.2 Signaturas transitorias de B2

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class TTSCapabilities:
    can_invalidate_stale_request: bool
    can_stop_physical_playback: bool
    can_report_logical_activity: bool
    can_report_physical_playback: bool
    can_stream: bool
    requires_hil: bool

class TTSError(Exception): ...
class TTSSynthesisError(TTSError): ...
class TTSUnavailableError(TTSError): ...
class TTSClosedError(TTSError): ...

class TTSAdapter(ABC):
    @abstractmethod
    async def speak(self, text: str) -> None:
        """API legacy temporal implementada por los adapters existentes."""
        ...

    async def synthesize_and_play(self, text: str) -> None:
        """API v2 temporal que delega en speak() durante la migración."""
        await self.speak(text)

    async def stop(self) -> None:
        """Stop lógico best-effort por defecto."""
        return None

    @property
    def is_active(self) -> bool:
        """Actividad lógica del adapter, no confirmación acústica."""
        return False

    @property
    def capabilities(self) -> TTSCapabilities:
        return TTSCapabilities(
            can_invalidate_stale_request=False,
            can_stop_physical_playback=False,
            can_report_logical_activity=False,
            can_report_physical_playback=False,
            can_stream=False,
            requires_hil=False,
        )

    async def close(self) -> None:
        return None
```

Resultado obligatorio:

```
B2_EXISTING_ADAPTERS_REMAIN_INSTANTIABLE = YES
```

Garantías de B2:

- Los adapters actuales siguen siendo instanciables.
- `tts_adapter_factory` sigue pudiendo construirlos.
- `AUDIO-CHAR-004` no falla por abstracción incompleta.
- `AUDIO-CHAR-012` no falla por abstracción incompleta.
- `speak()` no se elimina en B2.
- `synthesize_and_play()` no es abstracto en B2.
- La eliminación futura de `speak()` queda diferida.

### 9.3 Alias legacy

`is_speaking`, si se conserva temporalmente para compatibilidad, debe ser solo:

```
is_speaking = DEPRECATED_LOGICAL_ALIAS
NOT_PHYSICAL_AUDIO_CONFIRMATION = YES
```

El contrato público recomendado usa `is_active`.

---

## 10. Semántica de operaciones

### 10.1 synthesize_and_play(text: str) -> None

```
RECOMMENDED_RETURN_SEMANTICS = FIRE_AND_FORGET_LOGICAL_PLAYBACK
```

Semántica:

- Espera la síntesis.
- Valida `generation_id`.
- Crea una playback task propia si el resultado sigue vigente.
- Retorna después de programar la playback task.
- No espera el fin físico del audio.
- Texto vacío retorna sin iniciar síntesis ni playback.

Puede elevar al caller:

- `TTSSynthesisError`
- `TTSUnavailableError`
- `TTSClosedError`

No puede elevar por la misma llamada un error ocurrido después del retorno en playback background. Los errores de playback se registran, pueden almacenarse como `last_playback_error`, y pueden exponerse por telemetría. No se declara `TTSPlaybackError` como propagable por `synthesize_and_play()`.

`asyncio.CancelledError` no se envuelve como `TTSError`.

### 10.2 stop() -> None

```
STAGE_B_PHYSICAL_STOP_IMPLEMENTATION = DEFERRED
STAGE_B_STOP_SEMANTICS = LOGICAL_BEST_EFFORT
PHYSICAL_PLAYBACK_AFTER_ASYNC_TASK_CANCEL = MAY_CONTINUE_UNTIL_FULL_PCM_BUFFER_IS_CONSUMED_OR_DEVICE_FAILURE
```

Cancelar la `asyncio.Task` que espera `run_in_executor()` no detiene automáticamente el trabajo ya iniciado en `ThreadPoolExecutor`.

Para el worker actual:

```
_play_audio_alsa()
→ sounddevice.OutputStream
→ finished_event.wait()
```

el comportamiento honesto es que el audio físico puede continuar hasta consumir el buffer PCM completo o hasta fallo del dispositivo. Stage B no promete stop físico común. Una mejora futura puede introducir `threading.Event`, callback cooperativo, `CallbackStop` y timeout de cierre, pero eso queda fuera del alcance aprobado.

### 10.3 is_active -> bool

`is_active` representa actividad lógica conocida por el adapter:

- síntesis pendiente;
- operación async propia;
- playback task propia todavía activa.

No confirma que el parlante esté emitiendo audio.

Por backend debe documentarse:

| BACKEND | SOURCE_OF_TRUTH | TRUE_TRANSITIONS | FALSE_TRANSITIONS | PHYSICAL_AUDIO_REPRESENTED |
|---|---|---|---|---|
| LocalPiperTTSAdapter | `generation_id`, `_synthesis_active`, `_playback_tasks` | síntesis en curso o playback task propia activa | no hay síntesis vigente ni tasks propias | NO |
| PiperDockerTTSAdapter | task propia de `speak`/`synthesize_and_play` y generación | comando Docker/paplay en curso conocido por el adapter | operación finalizada, invalidada o cerrada | NO |
| UnitreeTTSAdapter | tarea propia que invoca `TtsMaker()` y generación | llamada SDK pendiente antes de cruzar frontera o todavía ejecutando en executor | llamada retornó, fue invalidada antes del side effect, o adapter cerró | NO |

### 10.4 close() -> None

`close()` es idempotente y lógico. Cancela tasks propias, invalida resultados obsoletos, limpia registros internos, libera executors propios y deja `is_active=False`. No promete detener un worker ALSA ya iniciado ni revertir side effects ya enviados al SDK Unitree.

---

## 11. Política de concurrencia

```
RECOMMENDED_CONCURRENCY_POLICY = LATEST_WINS_LOGICALLY
```

Semántica:

1. Cada solicitud obtiene un `generation_id` monotónico.
2. Una nueva solicitud incrementa la generación.
3. Una síntesis anterior puede continuar en el executor.
4. Cuando esa síntesis termina, comprueba su `generation_id`.
5. Si quedó obsoleta, su resultado PCM se descarta.
6. Una operación obsoleta no puede crear playback.
7. Una playback task async anterior puede cancelarse lógicamente.
8. Cancelar esa task no implica detener el audio físico.
9. Unitree puede haber enviado ya el side effect a `TtsMaker()`.
10. Ninguna capability promete reversión del side effect físico.

No se denomina `INTERRUPT_PREVIOUS` porque no garantiza interrupción física común a todos los backends.

---

## 12. stop() — semántica detallada

### 12.1 LocalPiperTTSAdapter

`stop()` incrementa `generation_id`, cancela playback tasks propias, limpia registros lógicos y deja `is_active=False`. No detiene por sí mismo el worker en `ThreadPoolExecutor`; el worker puede continuar hasta consumir el buffer PCM completo o fallar el dispositivo.

### 12.2 PiperDockerTTSAdapter

`stop()` invalida solicitudes obsoletas y cancela tareas async propias. Stage B no promete matar procesos externos ni detener un `paplay` ya iniciado salvo que una implementación posterior lo diseñe y pruebe explícitamente.

### 12.3 UnitreeTTSAdapter

`stop()` invalida solicitudes obsoletas y limpia estado lógico. En Unitree, invalidar una solicitud obsoleta no revierte una llamada `TtsMaker()` que ya cruzó la frontera del SDK.

`PlayStop()` queda diferido a `POST-I01-PLAYSTREAM-ADAPTER`/HIL. Stage B no invoca ni promete stop físico Unitree.

---

## 13. Actividad lógica

```python
@property
def is_active(self) -> bool:
    ...
```

La propiedad canónica es `is_active`, no `is_speaking`. Si se mantiene `is_speaking`, debe implementarse como alias temporal de actividad lógica y documentarse como `DEPRECATED_LOGICAL_ALIAS`.

Transiciones para LocalPiper:

1. Al iniciar síntesis vigente: `is_active=True`.
2. Al terminar síntesis: si la generación sigue vigente, se crea playback task propia.
3. Mientras la playback task propia sigue activa: `is_active=True`.
4. Si la generación quedó obsoleta: no se crea playback; `is_active` refleja solo operaciones vigentes.
5. En `stop()` y `close()`: se cancelan tasks propias, se invalida generación y `is_active=False`.

---

## 14. close() — semántica detallada

Cobertura esperada:

- `close()` durante playback activa cancela lógicamente la task propia.
- La task queda removida del registro interno.
- `is_active` termina en `False`.
- Executor propio recibe `shutdown` exactamente una vez.
- Executor inyectado no es cerrado por el adapter.
- Segunda y tercera llamada son no-op.
- `synthesize_and_play()` posterior eleva `TTSClosedError`.
- No quedan tasks propias registradas.

---

## 15. Capabilities

### 15.1 Modelo canónico

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class TTSCapabilities:
    can_invalidate_stale_request: bool
    can_stop_physical_playback: bool
    can_report_logical_activity: bool
    can_report_physical_playback: bool
    can_stream: bool
    requires_hil: bool
```

No se usan nombres legacy ambiguos de stop o cancelación pendiente porque no aclaran qué objeto o side effect se cancela.

### 15.2 Valores por adapter

| CAPABILITY | LocalPiperTTSAdapter | PiperDockerTTSAdapter | UnitreeTTSAdapter |
|---|---|---|---|
| can_invalidate_stale_request | True | True | True |
| can_stop_physical_playback | False | False | False |
| can_report_logical_activity | True | True | True |
| can_report_physical_playback | False | False | False |
| can_stream | False | False | False |
| requires_hil | False | False | True |

Aclaración obligatoria: en Unitree, invalidar una solicitud obsoleta no revierte una llamada `TtsMaker()` que ya cruzó la frontera del SDK.

### 15.3 PlayStream futuro

```
PLAYSTREAM_CAPABILITIES = DEFERRED
```

No se asignan capabilities definitivas a PlayStream hasta `POST-I01-PLAYSTREAM-ADAPTER` y validación HIL.

---

## 16. Excepciones tipadas

### 16.1 Jerarquía

```python
class TTSError(Exception):
    """Base para errores TTS observables."""

class TTSSynthesisError(TTSError):
    """La síntesis falló antes de crear playback vigente."""

class TTSUnavailableError(TTSError):
    """El backend requerido no está disponible."""

class TTSClosedError(TTSError):
    """El adapter fue llamado después de close()."""
```

### 16.2 Política por excepción

| EXCEPCIÓN | TRIGGER | PROPAGACIÓN |
|---|---|---|
| `TTSSynthesisError` | falla síntesis antes de playback vigente | caller |
| `TTSUnavailableError` | backend no disponible | caller |
| `TTSClosedError` | llamada post-close | caller |
| `asyncio.CancelledError` | cancelación asyncio | se propaga directo, no se envuelve |
| error de playback background | falla después del retorno | log/telemetría/`last_playback_error`, no caller |

---

## 17. Matriz de compatibilidad Piper / Unitree

| CONTRACT_FEATURE | LocalPiperTTSAdapter | PiperDockerTTSAdapter | UnitreeTTSAdapter | IMPLEMENTABLE_OFFLINE | REQUIRES_HIL | DEFERRED |
|---|---|---|---|---|---|---|
| `speak` legacy temporal | Sí en transición | Sí | Sí | Sí | No | Eliminación posterior |
| `synthesize_and_play` concreto en B2 | delega en `speak` hasta B3 | delega en `speak` hasta B4 | delega en `speak` hasta B5 | Sí | No | No |
| stale-result suppression | Sí | Sí | Sí antes del side effect SDK | Sí | No | No |
| stop físico | No | No | No | No | Sí para validar futuro | POST-B |
| `is_active` lógico | Sí | Sí | Sí | Sí | No | No |
| reporte físico de audio | No | No | No | No | Sí | POST-B |
| capabilities canónicas | Sí | Sí | Sí | Sí | No | No |
| PlayStream | No | No | No | No | Sí | POST-I01-PLAYSTREAM-ADAPTER |

---

## 18. Frontera con PlayStream / HIL

### 18.1 Explícitamente fuera de Stage B

```
AUDIO-CHAR-006       = EXCLUIDO (PlayStream adapter)
AUDIO-CHAR-007       = EXCLUIDO (PlayStream adapter)
AUDIO-CHAR-006-HIL   = EXCLUIDO
AUDIO-CHAR-007-HIL   = EXCLUIDO
PlayStreamAdapter    = NO diseñado en Stage B
Reproducción física por streaming = NO
Validación de speaker físico     = NO
```

### 18.2 Restricciones de Stage B que no deben bloquear PlayStream

- `synthesize_and_play` retorna cuando la síntesis terminó y la playback task lógica fue programada.
- `_play_audio_alsa` debe ser reemplazable sin cambiar el contrato público.
- `TTSCapabilities.can_stream` queda reservado en `False` durante Stage B.

### 18.3 Decisiones diferidas explícitamente

```
AUDIO_CHAR_006_STATUS  = DEFERRED_TO_POST_I01_PLAYSTREAM_ADAPTER
AUDIO_CHAR_007_STATUS  = DEFERRED_TO_POST_I01_PLAYSTREAM_ADAPTER
HIL_VALIDATION_STATUS  = DEFERRED_TO_HIL_STAGE
PHYSICAL_STOP_STATUS   = DEFERRED_TO_HIL_STAGE
STREAMING_PROTOCOL     = NOT_DESIGNED_IN_STAGE_B
```

---

## 19. Tests contractuales — AUDIO-CONTRACT-013 a 020

### Cobertura obligatoria verificada

| AREA | TEST_ID | CUBIERTO |
|---|---|---|
| Capabilities explícitas y texto vacío no-op | 013 | SÍ |
| Estado inicial lógico | 014 | SÍ |
| Actividad lógica durante playback | 015 | SÍ |
| stop idempotente sin actividad | 016 | SÍ |
| stop cancela playback task async controlada | 017 | SÍ |
| close y cleanup completo | 018 | SÍ |
| Excepciones tipadas | 019 | SÍ |
| LATEST_WINS_LOGICALLY y stale-result suppression | 020 | SÍ |

```
LOGICAL_AUDIO_CONTRACT_ID_COUNT = 8
CAPABILITIES_ASSERTIONS_EXPLICIT = YES
```

Los 8 IDs son identificadores lógicos. Con parametrización puede haber `N` casos pytest; no se exige `N collected`.

### AUDIO-CONTRACT-013

```
TEST_ID             = AUDIO-CONTRACT-013
TEST_NAME_PROPOSED  = test_contract_capabilities_and_empty_text_noop
TARGET              = LocalPiperTTSAdapter, PiperDockerTTSAdapter, UnitreeTTSAdapter offline
ASSERTIONS          =
  - type(adapter.capabilities) is TTSCapabilities
  - dataclass frozen y slots
  - igualdad determinista entre instancias iguales
  - inmutabilidad comprobada
  - can_invalidate_stale_request valor esperado por adapter
  - can_stop_physical_playback valor esperado por adapter
  - can_report_logical_activity valor esperado por adapter
  - can_report_physical_playback valor esperado por adapter
  - can_stream valor esperado por adapter
  - requires_hil valor esperado por adapter
  - estado inicial is_active = False
  - texto vacío no inicia síntesis ni playback
CURRENT_EXPECTED_STATUS = FAIL runtime assertion; sin collection error
```

### AUDIO-CONTRACT-014

```
TEST_ID             = AUDIO-CONTRACT-014
TEST_NAME_PROPOSED  = test_contract_is_active_false_initially
TARGET              = adapters canónicos
ASSERTIONS          = is_active = False en estado inicial; no importa hardware
CURRENT_EXPECTED_STATUS = FAIL runtime assertion; sin collection error
```

### AUDIO-CONTRACT-015

```
TEST_ID             = AUDIO-CONTRACT-015
TEST_NAME_PROPOSED  = test_contract_is_active_true_during_controlled_playback
TARGET              = LocalPiperTTSAdapter
MOCK_BOUNDARY       = adapter._run_alsa_playback como coroutine controlada
ASSERTIONS          = is_active=True durante playback task propia; is_active=False al finalizar
CURRENT_EXPECTED_STATUS = FAIL runtime assertion; sin collection error
```

### AUDIO-CONTRACT-016

```
TEST_ID             = AUDIO-CONTRACT-016
TEST_NAME_PROPOSED  = test_contract_stop_idempotent_when_inactive
TARGET              = adapters canónicos
ACTION              = await adapter.stop(); await adapter.stop(); await adapter.stop()
ASSERTIONS          = ninguna excepción; is_active=False
CURRENT_EXPECTED_STATUS = FAIL runtime assertion; sin collection error
```

### AUDIO-CONTRACT-017

```
TEST_ID             = AUDIO-CONTRACT-017
TEST_NAME_PROPOSED  = test_contract_stop_cancels_active_playback_task_strongly
TARGET              = LocalPiperTTSAdapter
AUDIO_CONTRACT_017_STRONG_CANCELLATION_ASSERTION = YES
```

Patrón requerido:

```python
started = asyncio.Event()
release = asyncio.Event()
cancelled = asyncio.Event()

async def controlled_playback(*args, **kwargs):
    started.set()
    try:
        await release.wait()
    except asyncio.CancelledError:
        cancelled.set()
        raise
```

Secuencia conceptual:

1. Iniciar `synthesize_and_play()`.
2. Esperar `started`.
3. Obtener referencia inequívoca a la playback task interna.
4. Confirmar `is_active=True`.
5. `await adapter.stop()`.
6. Esperar `cancelled`.
7. `assert playback_task.cancelled() is True`.
8. `assert playback_task` ya no está registrada.
9. `assert is_active is False`.
10. Segunda llamada `stop()` no falla.

No se acepta una alternativa débil entre estado cancelado y simple remoción del registro. El test valida cancelación lógica de la task async, no stop físico del worker real.

### AUDIO-CONTRACT-018

```
TEST_ID             = AUDIO-CONTRACT-018
TEST_NAME_PROPOSED  = test_contract_close_full_lifecycle_cleanup
TARGET              = LocalPiperTTSAdapter y adapters con recursos propios/injectados
AUDIO_CONTRACT_018_CLEANUP_COVERAGE = COMPLETE
```

Debe cubrir:

- 018-A: `close` durante playback task activa.
- 018-B: playback task queda cancelada y removida.
- 018-C: `is_active` termina en `False`.
- 018-D: executor propio recibe `shutdown` exactamente una vez.
- 018-E: executor inyectado no es cerrado por el adapter.
- 018-F: segunda y tercera llamada `close()` son no-op.
- 018-G: `synthesize_and_play()` después de `close()` eleva `TTSClosedError`.
- 018-H: no quedan tasks propias registradas.

Usar executors falsos o spies; no depender de hardware.

### AUDIO-CONTRACT-019

```
TEST_ID             = AUDIO-CONTRACT-019
TEST_NAME_PROPOSED  = test_contract_typed_exception_on_synthesis_failure
TARGET              = LocalPiperTTSAdapter
ASSERTIONS          = TTSSynthesisError/TTSUnavailableError según causa; is_active=False; sin playback tasks
CURRENT_EXPECTED_STATUS = FAIL runtime assertion; sin collection error
```

### AUDIO-CONTRACT-020

```
TEST_ID             = AUDIO-CONTRACT-020
TEST_NAME_PROPOSED  = test_contract_latest_wins_distinguishes_request_and_playback_tasks
TARGET              = LocalPiperTTSAdapter
REQUEST_TASK_AND_PLAYBACK_TASK_DISTINGUISHED = YES
STALE_RESULT_SUPPRESSION_TESTED = YES
```

Escenario 020-A — supresión de síntesis obsoleta:

1. Solicitud A inicia síntesis y queda controladamente bloqueada.
2. Solicitud B incrementa `generation_id`.
3. B completa su síntesis.
4. A termina después.
5. El resultado de A se descarta.
6. A no crea playback.
7. Solo B crea playback.

```
STALE_SYNTHESIS_PLAYBACK_COUNT = 0
LATEST_SYNTHESIS_PLAYBACK_COUNT = 1
```

Escenario 020-B — reemplazo lógico de playback:

1. Solicitud A ya retornó después de programar playback.
2. `request_task_A` puede estar completed.
3. `playback_task_A` sigue activa.
4. Solicitud B invalida A.
5. B cancela `playback_task_A` lógicamente.
6. El test observa la cancelación dentro del mock async de playback.
7. B crea `playback_task_B`.

No exigir estado cancelado en la request task A; la assertion se refiere a `playback_task_A`.

---

## 20. Estrategia de migración

### Resumen de etapas

| ETAPA | NOMBRE | PROPÓSITO |
|---|---|---|
| B1 | Tests contractuales inicialmente rojos | AUDIO-CONTRACT-013..020 sin collection errors |
| B2 | Contrato transitorio compatible | `TTSCapabilities`, errores, defaults concretos, adapters actuales instanciables |
| B3 | LocalPiperTTSAdapter | Extraer Piper ONNX/ALSA desde `LocalNLPPipeline` |
| B4 | PiperDockerTTSAdapter | Adaptar adapter Docker existente y preservar alias/reexports |
| B5 | UnitreeTTSAdapter offline | `TtsMaker()` solamente; capabilities honestas |
| B6a | Construcción e inyección | crear adapter según configuración; sin migrar todos los callers |
| B6b | Migración de callers y wiring | `LocalNLPPipeline`, `ConversationManager`, `main.py`, shutdown |
| B7 | Autorrevisión y regresión | contract tests, Stage A, focalizados, suite unitaria, lifecycle, cleanup |
| B8 | Aprobación humana y commit | commit local solo con autorización; push separado |

### B1 — Tests contractuales inicialmente rojos

```
ENTRY_GATE = Stage A commit aprobado; worktree limpio
FILES_ALLOWED = tests/unit/test_audio_contract.py
EXPECTED_RED_TESTS = AUDIO-CONTRACT-013..020 fallan por assertions runtime
EXPECTED_GREEN_TESTS = collection completa sin ImportError; Stage A sin cambios
ROLLBACK = eliminar archivo nuevo de tests
EXIT_GATE = LOGICAL_TEST_ID_COUNT=8; PYTEST_CASE_COUNT=N documentado; COLLECTION_ERRORS=0; FAILED_CASES=N; SKIPPED=0; XFAILED=0
COMMIT_POLICY = NO_COMMIT sin aprobación humana
```

Modelo B1: usar `importlib.import_module("src.interaction")` y `getattr` para símbolos todavía inexistentes. No usar imports directos de módulos nuevos. Cada caso debe recolectar y fallar en runtime por assertion; no `skip`, no `xfail`, no hardware.

### B2 — Contrato transitorio compatible

```
ENTRY_GATE = B1 creado y con collection errors = 0
FILES_ALLOWED = src/interaction/tts_contract.py, src/interaction/tts_unitree_client.py, src/interaction/__init__.py, tests contractuales correspondientes
EXPECTED_RED_TESTS = casos que requieren implementación real siguen rojos
EXPECTED_GREEN_TESTS = símbolos existen; adapters actuales siguen instanciables; AUDIO-CHAR-004 y AUDIO-CHAR-012 no rompen por abstracción
ROLLBACK = revertir archivos de contrato, bridge mínimo y exports
EXIT_GATE = B2_EXISTING_ADAPTERS_REMAIN_INSTANTIABLE=YES; speak() sigue; synthesize_and_play() concreto delega en speak()
COMMIT_POLICY = NO_COMMIT sin aprobación humana
```

B2 compatibility bridge planificado, sin implementar en esta tarea:

```
B2_COMPATIBILITY_BRIDGE =
1. Crear src/interaction/tts_contract.py.
2. Modificar mínimamente src/interaction/tts_unitree_client.py para importar TTSAdapter y TTSCapabilities desde tts_contract.py; mantener PiperTTSAdapter y UnitreeTTSAdapter instanciables; preservar speak() como API legacy temporal; heredar synthesize_and_play(), stop(), is_active, capabilities y close() concretos desde la nueva base; conservar reexports y compatibilidad de imports; no implementar todavía LocalPiperTTSAdapter; no alterar todavía el wiring de producción.
3. Modificar mínimamente src/interaction/__init__.py para reexportar los símbolos contractuales nuevos y preservar los símbolos públicos existentes.

B2_TTS_CONTRACT_FILE = src/interaction/tts_contract.py
B2_TTS_UNITREE_CLIENT_MINIMAL_BRIDGE = REQUIRED
B2_INTERACTION_INIT_REEXPORT_UPDATE = REQUIRED
B2_EXISTING_ADAPTERS_REMAIN_INSTANTIABLE = YES
B2_LOCAL_PIPER_IMPLEMENTATION = DEFERRED_TO_B3
B2_PRODUCTION_WIRING_CHANGE = NO
```

### B3 — LocalPiperTTSAdapter

```
ENTRY_GATE = B2 verde para compatibilidad
FILES_ALLOWED = src/interaction/tts_piper_local.py, tests contractuales relacionados
EXPECTED_RED_TESTS = Unitree/Docker específicos aún pueden seguir rojos
EXPECTED_GREEN_TESTS = LocalPiper AUDIO-CONTRACT-013..020
ROLLBACK = revertir adapter local
EXIT_GATE = generation_id, stale-result suppression, playback task ownership, stop lógico, close cleanup implementados
COMMIT_POLICY = NO_COMMIT sin aprobación humana
```

### B4 — PiperDockerTTSAdapter

```
ENTRY_GATE = B3 LocalPiper verde
FILES_ALLOWED = src/interaction/tts_piper_docker.py, src/interaction/tts_unitree_client.py compat, src/interaction/__init__.py
EXPECTED_RED_TESTS = Unitree específicos aún pueden seguir rojos
EXPECTED_GREEN_TESTS = Docker contract offline sin hardware; alias PiperTTSAdapter preservado
ROLLBACK = revertir adapter Docker/alias
EXIT_GATE = PiperDocker separado de LocalPiper; no se confundió Docker con ONNX/ALSA
COMMIT_POLICY = NO_COMMIT sin aprobación humana
```

### B5 — UnitreeTTSAdapter offline

```
ENTRY_GATE = B4 verde
FILES_ALLOWED = src/interaction/tts_unitree_adapter.py, compat exports
EXPECTED_RED_TESTS = wiring productivo aún no migrado
EXPECTED_GREEN_TESTS = Unitree offline contract + AUDIO-CHAR-012
ROLLBACK = revertir adapter Unitree nuevo/compat
EXIT_GATE = TtsMaker solamente; sin PlayStream; sin stop físico; sin speaking físico; capabilities honestas
COMMIT_POLICY = NO_COMMIT sin aprobación humana
```

### B6a — Construcción e inyección

```
ENTRY_GATE = B5 verde y H-04 revisada
FILES_ALLOWED = factory/config mínimos, tests de construcción
EXPECTED_RED_TESTS = callers antiguos todavía pueden no usar el adapter nuevo
EXPECTED_GREEN_TESTS = factory construye adapter según configuración
ROLLBACK = revertir factory/config
EXIT_GATE = creación e inyección disponibles sin activar wiring productivo completo
COMMIT_POLICY = NO_COMMIT sin aprobación humana
```

### B6b — Migración de callers y wiring

```
ENTRY_GATE = B6a verde y aprobación humana de H-01..H-04
FILES_ALLOWED = LocalNLPPipeline, ConversationManager, main.py, shutdown wiring, tests focalizados
EXPECTED_RED_TESTS = ninguno nuevo aceptado
EXPECTED_GREEN_TESTS = Stage A, contract, lifecycle, cloud interlock, suite unitaria focalizada
ROLLBACK = revertir wiring/callers
EXIT_GATE = callers usan contrato; shutdown llama close(); sin regresiones no documentadas
COMMIT_POLICY = NO_COMMIT sin aprobación humana
```

### B7 — Autorrevisión y regresión

```
ENTRY_GATE = B6b verde
FILES_ALLOWED = audit-reports nuevos; ningún código salvo correcciones autorizadas por hallazgo
EXPECTED_RED_TESTS = solo fallos preexistentes documentados, si los hubiera
EXPECTED_GREEN_TESTS = contract, Stage A, focalizados, lifecycle, cleanup
ROLLBACK = eliminar informes temporales
EXIT_GATE = informe de implementación y autorrevisión listos
COMMIT_POLICY = NO_COMMIT sin aprobación humana
```

### B8 — Aprobación humana y commit

```
ENTRY_GATE = B7 completado; aprobación humana explícita
FILES_ALLOWED = git index solo si autorizado
EXPECTED_RED_TESTS = ninguno no documentado
EXPECTED_GREEN_TESTS = suite definida por B7
ROLLBACK = no iniciar commit si falta autorización
EXIT_GATE = commit local creado solo si autorizado; push separado
COMMIT_POLICY = COMMIT_LOCAL_ONLY_WITH_EXPLICIT_HUMAN_AUTHORIZATION; PUSH_PROHIBIDO_EN_ESTA_ETAPA
```

---

## 21. Impacto por archivo

| ARCHIVO | CAMBIO_ESPERADO | CATEGORÍA |
|---|---|---|
| `src/interaction/tts_contract.py` | `TTSCapabilities`, errores, `TTSAdapter` transitorio compatible | CONTRACT_INTERFACE |
| `src/interaction/tts_piper_local.py` | `LocalPiperTTSAdapter` ONNX/ALSA | LOCAL_PIPER_ADAPTER |
| `src/interaction/tts_piper_docker.py` | `PiperDockerTTSAdapter` Docker/WAV/paplay | DOCKER_PIPER_ADAPTER |
| `src/interaction/tts_unitree_adapter.py` | `UnitreeTTSAdapter` con `TtsMaker()` | UNITREE_ADAPTER |
| `src/interaction/tts_unitree_client.py` | compatibilidad temporal, alias/reexports | COMPATIBILITY |
| `src/interaction/conversation_manager.py` | migración de callers en B6b | CALLER_MIGRATION |
| `main.py` | wiring/shutdown en B6b | WIRING_CHANGE |
| `config/settings.py` | solo si se necesita selección explícita de adapter | CONFIG_OPTIONAL |
| `tests/unit/test_audio_contract.py` | AUDIO-CONTRACT-013..020 | TEST_ONLY |

---

## 22. Riesgos

| RISK_ID | RIESGO | MITIGACIÓN | BLOQUEA_STAGE_B |
|---|---|---|---|
| R-01 | stop físico Unitree no verificable sin HIL | `can_stop_physical_playback=False`; PlayStop diferido | NO |
| R-02 | actividad Unitree es lógica, no física | `can_report_physical_playback=False`; `is_active` lógico | NO |
| R-03 | cancelación asyncio no detiene executors | documentar worker continúa hasta buffer completo/fallo; stale suppression | NO |
| R-04 | close puede dejar worker ALSA ya iniciado corriendo | Stage B acepta stop lógico; futuro stop cooperativo | NO |
| R-05 | alias `PiperTTSAdapter` puede confundirse con LocalPiper | renombrar Docker explícitamente y deprecar alias | SÍ para B4 si no se documenta |
| R-06 | B1 puede romper collection si importa símbolos inexistentes | usar importlib/getattr y assertions runtime | SÍ para B1 |
| R-07 | wiring de callers tiene blast radius | dividir B6a/B6b | NO |

---

## 23. Decisiones que requieren aprobación humana

### H-01 — Arquitectura Piper objetivo

```
DECISION_ID = H-01
QUESTION = Arquitectura Piper objetivo.
RECOMMENDED_OPTION = LocalPiperTTSAdapter dedicado, separado de PiperDockerTTSAdapter.
DEFAULT_IF_NOT_DECIDED = No comenzar B1.
```

### H-02 — Política de concurrencia

```
DECISION_ID = H-02
QUESTION = Política de concurrencia.
RECOMMENDED_OPTION = LATEST_WINS_LOGICALLY.
DEFAULT_IF_NOT_DECIDED = SERIALIZE como fallback conservador.
```

### H-03 — Alcance Unitree

```
DECISION_ID = H-03
QUESTION = Alcance Unitree.
RECOMMENDED_OPTION = TtsMaker solamente, validación offline, sin stop físico ni PlayStream.
DEFAULT_IF_NOT_DECIDED = No migrar Unitree.
```

### H-04 — Separación del wiring

```
DECISION_ID = H-04
QUESTION = Separación del wiring.
RECOMMENDED_OPTION = B6a construcción/inyección y B6b migración de callers.
DEFAULT_IF_NOT_DECIDED = No activar wiring productivo.
```

Estas recomendaciones no son aprobaciones humanas.

---

## 24. Gates de implementación

### Gate 1 — Preflight

```
HEAD = 68967c85e0063e0b4d08b9411ff8431941ad2a35
BRANCH = review/orchestrator-unification
WORKTREE_CLEAN = YES
Sin operaciones Git incompletas = YES
```

### Gate 2 — Evidencia

```
Los 5 informes de Stage A tienen hashes correctos = YES
Plan v2 y autorrevisión previa leídos = YES
Código vigente inspeccionado read-only = YES
Tests vigentes inspeccionados read-only = YES
```

### Gate 3 — Contrato objetivo

```
LocalPiper y PiperDocker separados = YES
B2 preserva instanciación = YES
speak legacy preservado = YES
synthesize_and_play concreto en B2 = YES
```

### Gate 4 — Semántica runtime

```
ALSA_ASYNC_TASK_CANCEL_STOPS_THREADPOOL_WORKER = NO
PHYSICAL_PLAYBACK_AFTER_ASYNC_TASK_CANCEL = MAY_CONTINUE_UNTIL_FULL_PCM_BUFFER_IS_CONSUMED_OR_DEVICE_FAILURE
RECOMMENDED_CONCURRENCY_POLICY = LATEST_WINS_LOGICALLY
```

### Gate 5 — Capabilities

```
CAPABILITIES_CANONICAL_MODEL_COUNT = 1
CAPABILITIES_ASSERTIONS_EXPLICIT = YES
UNITREE_PHYSICAL_STOP_PROMISED = NO
UNITREE_PHYSICAL_PLAYBACK_REPORT_PROMISED = NO
```

### Gate 6 — Tests

```
LOGICAL_AUDIO_CONTRACT_ID_COUNT = 8
AUDIO_CONTRACT_017_STRONG_CANCELLATION_ASSERTION = YES
AUDIO_CONTRACT_018_CLEANUP_COVERAGE = COMPLETE
REQUEST_TASK_AND_PLAYBACK_TASK_DISTINGUISHED = YES
STALE_RESULT_SUPPRESSION_TESTED = YES
B1_COLLECTION_ERRORS_EXPECTED = 0
```

### Gate 7 — Migración

```
IMPLEMENTATION_STAGE_COUNT = 9
IMPLEMENTATION_STAGES = B1,B2,B3,B4,B5,B6a,B6b,B7,B8
COMMIT_POLICY = HUMAN_AUTHORIZATION_REQUIRED
```

### Gate 8 — Alcance

```
CODIGO_MODIFICADO = 0
TESTS_MODIFICADOS = 0
COMMITS_CREADOS = 0
RED_ACCEDIDA = NO
ROBOT_ACCEDIDO = NO
```

---

## 25. Secuencia de próximos prompts

```
1. HUMAN_REVIEW_I01_STAGE_B_TTS_CONTRACT_PLAN_V3
   Revisión humana del plan v3 y de H-01..H-04.

2. IMPLEMENT_I01_STAGE_B_CONTRACT_TESTS
   Solo si el plan v3 es aprobado.

3. IMPLEMENT_I01_STAGE_B_TTS_BASE_CONTRACT
   Solo después de B1 y sin romper instanciación.

4. IMPLEMENT_I01_STAGE_B_LOCAL_PIPER_ADAPTER
   LocalPiper ONNX/ALSA dedicado.

5. IMPLEMENT_I01_STAGE_B_PIPER_DOCKER_ADAPTER
   Docker/paplay separado y alias legacy preservado.

6. IMPLEMENT_I01_STAGE_B_UNITREE_ADAPTER_OFFLINE
   TtsMaker solamente, sin PlayStream ni stop físico.

7. IMPLEMENT_I01_STAGE_B_WIRING_B6A_B6B
   Construcción/inyección y luego migración de callers.

8. SELF_REVIEW_AND_REGRESSION_I01_STAGE_B
   Tests contractuales, Stage A, lifecycle, cleanup.

9. HUMAN_APPROVAL_I01_STAGE_B_COMMIT
   Commit local solo con autorización explícita.
```

## 26. Acciones no realizadas

```
SOURCE_CODE_FILES_MODIFIED = 0
TEST_FILES_MODIFIED        = 0
DEPENDENCY_FILES_MODIFIED  = 0
COMMITS_CREATED            = 0
PUSH_PERFORMED             = NO
MERGE_PERFORMED            = NO
PR_CREATED                 = NO
GITHUB_ACCESSED            = NO
EXTERNAL_NETWORK_ACCESSED  = NO
ROBOT_ACCESSED             = NO
ROS_GRAPH_ACCESSED         = NO
AUDIO_PLAYBACK_EXECUTED    = NO
```

---

## 27. Corrección contractual de segunda pasada — versión 3

```
PRIOR_HUMAN_REVIEW = CHANGES_REQUESTED
CONTRACT_VERSION = 3
REMAINING_CONTRADICTIONS_REVIEWED = 8
REMAINING_CONTRADICTIONS_CORRECTED = 8
UNRESOLVED_CONTRADICTIONS = 0
```

### RC-01 — Identidad Piper

Corregido. El plan v3 separa `LocalPiperTTSAdapter` (ONNX/ALSA) de `PiperDockerTTSAdapter` (Docker/WAV/paplay) y preserva `PiperTTSAdapter` solo como alias/reexport temporal del adapter Docker existente.

### RC-02 — Instanciación en B2

Corregido. B2 mantiene `speak()` abstracto legacy y hace `synthesize_and_play()`, `stop()`, `is_active`, `capabilities` y `close()` concretos por defecto. Los adapters actuales no quedan ininstanciables.

### RC-03 — Cancelación ALSA

Corregido. El plan declara que cancelar la `asyncio.Task` no detiene el worker ya iniciado en `ThreadPoolExecutor`; el playback físico puede continuar hasta consumir el buffer PCM completo o hasta fallo del dispositivo.

### RC-04 — AUDIO-CONTRACT-017

Corregido. El test exige referencia inequívoca a `playback_task`, observación de `CancelledError` en un mock async controlado y `playback_task.cancelled() is True`; no acepta una assertion alternativa débil.

### RC-05 — AUDIO-CONTRACT-018

Corregido. El test cubre lifecycle completo de `close()`: cancelación/remoción de tasks, `is_active=False`, shutdown de executor propio una sola vez, executor inyectado intacto, idempotencia y `TTSClosedError` post-close.

### RC-06 — AUDIO-CONTRACT-020

Corregido. El requisito distingue `request_task` y `playback_task`, separa supresión de síntesis obsoleta de reemplazo lógico de playback, y verifica que el resultado stale no crea playback.

### RC-07 — Capabilities

Corregido. `TTSCapabilities` tiene un único modelo canónico y AUDIO-CONTRACT-013 verifica capabilities explícitamente. Unitree declara invalidación lógica, sin stop físico ni reporte físico.

### RC-08 — Modelo B1

Corregido. B1 evita imports directos de símbolos inexistentes; usa `importlib`/`getattr` para que collection complete y los fallos ocurran como assertions runtime.

### Validación contractual v3

```
LOCAL_PIPER_AND_DOCKER_SEPARATED = YES
B2_EXISTING_ADAPTERS_REMAIN_INSTANTIABLE = YES
RECOMMENDED_CONCURRENCY_POLICY = LATEST_WINS_LOGICALLY
CAPABILITIES_ASSERTIONS_EXPLICIT = YES
AUDIO_CONTRACT_017_STRONG_CANCELLATION_ASSERTION = YES
AUDIO_CONTRACT_018_CLEANUP_COVERAGE = COMPLETE
REQUEST_TASK_AND_PLAYBACK_TASK_DISTINGUISHED = YES
STALE_RESULT_SUPPRESSION_TESTED = YES
B1_COLLECTION_ERRORS_EXPECTED = 0
HUMAN_DECISION_COUNT = 4
```

### Trazabilidad histórica preservada

Los hallazgos válidos de la versión 2 se preservan como antecedentes. Quedan supersedidas las referencias de versiones anteriores que utilizaban `is_speaking` como propiedad común o que no distinguían actividad lógica de reproducción física. El contrato objetivo de Etapa B adopta `is_active` exclusivamente como estado lógico conocido por el adapter; `is_active` no confirma que el parlante esté emitiendo audio. También quedan superadas las referencias a cobertura de capabilities no explícita, conteos fijos de casos pytest o stop físico no demostrado.

---

## 28. Próxima acción

```
NEXT_ACTION = HUMAN_APPROVAL_I01_STAGE_B_TTS_CONTRACT_PLAN_V3
```

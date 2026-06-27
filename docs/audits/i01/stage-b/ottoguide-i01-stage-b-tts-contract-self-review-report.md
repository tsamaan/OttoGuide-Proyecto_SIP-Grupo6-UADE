# OttoGuide I-01 Stage B — Informe de Autorrevisión Correctiva del Plan TTS Contract

## 1. Resultado

```
RESULT = I01_STAGE_B_TTS_CONTRACT_PLAN_SELF_REVIEWED_AND_CORRECTED_READY_FOR_HUMAN_REVIEW
TASK   = SELF_REVIEW_AND_CORRECT_I01_STAGE_B_TTS_CONTRACT_PLAN
```

---

## 2. Contexto

Este informe documenta la autorrevisión del plan `ottoguide-i01-stage-b-tts-contract-plan.md` (v1) tras recibir el resultado de revisión humana:

```
HUMAN_REVIEW_I01_STAGE_B_TTS_CONTRACT_PLAN = CHANGES_REQUESTED
```

La autorrevisión tuvo dos objetivos:
1. Identificar y catalogar todas las contradicciones o errores en el plan v1
2. Producir un plan corregido v2 sin modificar ningún archivo de código, test ni configuración

---

## 3. Archivos producidos

| ARCHIVO | ACCIÓN | SHA256 |
|---|---|---|
| `audit-reports/ottoguide-i01-stage-b-tts-contract-plan.md` | REPLACED (v1 → v2) | BC25B5B9698719E8A6A38FDE7AE38F098C6554C984C2D536E9202B49300A53E6 |
| `audit-reports/ottoguide-i01-stage-b-tts-contract-self-review-report.md` | CREATED (este archivo) | — |

El plan v1 fue reemplazado atómicamente mediante `os.replace()`. No existe ningún archivo temporal residual.

---

## 4. Metodología de la autorrevisión

### 4.1 Fases ejecutadas

La autorrevisión siguió un protocolo de 31 fases:

- **Fase A**: Verificación de estado Git (worktree limpio, sin operaciones incompletas)
- **Fase B**: Verificación de integridad de artefactos (SHA256 de 5 informes Stage A)
- **Fase C**: Lectura completa de los 6 documentos de evidencia (diseño, planes, informes previos)
- **Fase D**: Lectura completa de 9 archivos fuente y de test
- **Fase E**: Reconstrucción del ciclo de vida en runtime (fases REQUEST_TASK, SYNTHESIS_FUTURE, etc.)
- **Fase F**: Análisis de semántica de cancelación (asyncio.Task vs. executor workers)
- **Fase G**: Análisis de observabilidad lógica vs. física (is_speaking)
- **Fase H**: Evaluación de política de concurrencia
- **Fase I**: Verificación de semántica de retorno (fire-and-forget confirmado)
- **Fase J**: Diseño canónico de capabilities
- **Fase K**: Jerarquía de excepciones (eliminación de TTSPlaybackError)
- **Fase L**: Rediseño de tests 013-020 (corrección de mock boundaries)
- **Fase M**: Estrategia de compatibilidad Stage A (concrete defaults)
- **Fase N**: Secuencia de implementación corregida
- **Fase O**: Revisión de decisiones H-01..H-04
- **Fases P-T**: Escritura, validación y reemplazo atómico del plan + este informe

### 4.2 Evidencia leída

Archivos leídos en su totalidad durante la autorrevisión:

| ARCHIVO | PROPÓSITO |
|---|---|
| `tts_unitree_client.py` (387 líneas) | TTSAdapter, PiperTTSAdapter, UnitreeTTSAdapter, tts_adapter_factory |
| `conversation_manager.py` (1393 líneas) | LocalNLPPipeline, synthesize_and_play, _run_alsa_playback, _play_audio_alsa |
| `test_audio_characterization.py` (388 líneas) | AUDIO-CHAR-001..011, patrones de mock |
| `test_audio_char_unitree.py` (44 líneas) | AUDIO-CHAR-012 |
| `test_conversation_playback_lifecycle.py` (350 líneas) | T01-T11, patrones threading.Event |
| `g1_audio_client.py` (patched) | PlayStop(), TtsMaker(), ROBOT_API_ID_AUDIO_STOP_PLAY |
| `g1_audio_client.py` (original) | Confirmación de que PlayStop() existe en ambas copias SDK |
| Plan v1 (1245 líneas) | Fuente de contradicciones a corregir |

---

## 5. Contradicciones identificadas y corregidas

### D-01 — AUDIO-CONTRACT-015: mock boundary incorrecto

**Sección afectada**: §19 AUDIO-CONTRACT-015

**Error en v1**:
```
MOCK_BOUNDARY = _play_audio_alsa → asyncio.Event que bloquea hasta set()
```

**Evidencia del error**:
- `_play_audio_alsa` es una función top-level SÍNCRONA en `conversation_manager.py` (líneas 215-280)
- Corre en ThreadPoolExecutor — contexto de hilo OS, no coroutine
- `asyncio.Event.wait()` es un coroutine; no puede awaited desde un contexto sync
- Resultado: el test fallaría con `RuntimeError: no running event loop` o bloquearía indefinidamente

**Corrección en v2**:
```
MOCK_BOUNDARY = adapter._run_alsa_playback → async mock con asyncio.Event
```
`_run_alsa_playback` es el MÉTODO ASYNC de PiperTTSAdapter/LocalNLPPipeline que envuelve `_play_audio_alsa`. Mockear el método async permite usar `asyncio.Event` en el mock correctamente. Este patrón es idéntico al de AUDIO-CHAR-009 en el código de tests existente.

---

### D-02 — AUDIO-CONTRACT-017: asyncio.sleep en contexto sync

**Sección afectada**: §19 AUDIO-CONTRACT-017

**Error en v1**:
```
MOCK_BOUNDARY = _play_audio_alsa → asyncio.sleep(10.0) — bloquea para simular reproducción larga
```

**Evidencia del error**:
- Mismo problema que D-01: `_play_audio_alsa` es función sync en ThreadPoolExecutor
- `asyncio.sleep(10.0)` es un coroutine; llamarlo desde sync context no bloquea; solo crea el coroutine object sin ejecutarlo
- El test no haría lo que intenta (simular reproducción larga)

**Corrección en v2**:
```
MOCK_BOUNDARY = adapter._run_alsa_playback → async mock con await asyncio.sleep(10.0)
```

---

### D-03 — AUDIO-CONTRACT-020: asyncio.sleep para síntesis lenta en ProcessPool

**Sección afectada**: §19 AUDIO-CONTRACT-020

**Error en v1**:
```
MOCK_BOUNDARY = síntesis_1: asyncio.sleep(1.0) — bloquea para simular síntesis lenta
```

**Evidencia del error**:
- `_run_piper_synthesis` es función top-level SÍNCRONA corriendo en ProcessPoolExecutor
- `asyncio.sleep(1.0)` no es ejecutable en worker de ProcessPool (no hay event loop)
- El test fallaría con error de serialización o comportamiento indefinido

**Corrección en v2**:
El test fue rediseñado para controlar el bloqueo en la fase de playback, que es el punto de control más determinista y correcto. La primera síntesis completa rápido pero el playback bloquea; la segunda llamada llega mientras el primero está en playback. Esto prueba la política LATEST_WINS sin depender de timing de ProcessPool.

---

### D-04 — TTSPlaybackError declarada como elevada al caller

**Sección afectada**: §10.1, §16.1, §16.2, §17

**Error en v1**:
```
class TTSPlaybackError(TTSError): ...
# La reproducción ALSA falló tras síntesis exitosa.
```
Listada como excepción que el caller puede capturar.

**Evidencia del error**:
- `synthesize_and_play` retorna en modo fire-and-forget cuando la síntesis terminó y la playback task fue creada
- Los errores de reproducción ALSA ocurren en el background Task, DESPUÉS de que `synthesize_and_play` ya retornó
- El done_callback `_on_playback_done()` captura estas excepciones y las loguea como WARNING: `LOGGER.warning("[LocalNLP] Excepcion en reproduccion ALSA: %s", exc)`
- No existe ningún punto en el flujo donde TTSPlaybackError pueda alcanzar al caller
- Definir TTSPlaybackError en la interfaz pública es una promesa incumplible

**Corrección en v2**:
TTSPlaybackError eliminada de la jerarquía pública. Solo TTSSynthesisError y TTSClosedError son elevadas al caller. Los errores de playback se documentan como "capturados en done_callback, solo LOGGER.warning".

---

### D-05 — INTERRUPT_PREVIOUS sin supresión de resultados de síntesis obsoletos

**Sección afectada**: §11, §12, §13.2

**Error en v1**:
La política INTERRUPT_PREVIOUS llamaba `stop()` y procedía con la nueva síntesis, pero no existía ningún mecanismo para prevenir que una síntesis en vuelo (en cpu_executor) que completara después del stop() registrara una playback task.

**Evidencia del error**:
Secuencia de carrera:
```
1. synthesize_and_play("primera") comienza → await de síntesis en ProcessPool
2. stop() llamado → cancela playback tasks → _synthesis_active = False
3. El worker de ProcessPool completa → retorna PCM
4. La coro de "primera" reanuda → intenta crear playback task
5. Resultado: "primera" inicia playback a pesar del stop()
```

**Corrección en v2**:
Generation counter `_request_generation: int = 0` añadido:
- `synthesize_and_play`: incrementa al inicio, guarda `my_generation`; antes de crear playback task verifica `my_generation == self._request_generation`; si no coincide, retorna sin registrar
- `stop()`: incrementa el contador al inicio para invalidar síntesis en vuelo
- `close()`: incrementa el contador como parte del cleanup

---

### D-06 — Nombre INTERRUPT_PREVIOUS impreciso

**Sección afectada**: §10.1, §11, §23 H-02

**Error en v1**:
El nombre "INTERRUPT_PREVIOUS" sugiere que la reproducción física anterior es interrumpida. Sin embargo:
- El hilo ALSA en ThreadPoolExecutor continúa hasta el frame actual
- El proceso piper en ProcessPoolExecutor no puede detenerse desde asyncio
- La "interrupción" es lógica (asyncio Task cancelada, flags reseteados), no física

**Corrección en v2**:
Renombrado a `LATEST_WINS_LOGICALLY`:
- "LATEST_WINS": la solicitud más reciente prevalece sobre las anteriores
- "LOGICALLY": el efecto de interrupción es en el espacio lógico de asyncio, no en hardware

---

### D-07 — TTSCapabilities con campos ambiguos

**Sección afectada**: §9.1, §15

**Error en v1**:
```python
can_stop: bool             # stop() tiene efecto observable en asyncio
can_report_speaking: bool  # is_speaking es confiable
stop_is_best_effort: bool  # True = cancela Task pero no hilo
```
- `can_stop`: no distingue si "stop" significa cancelar la asyncio.Task o detener el audio físico
- `can_report_speaking`: no distingue entre flag lógico interno y verificación física real
- `stop_is_best_effort`: redundante si `can_stop` ya distingue los niveles

**Corrección en v2**:
```python
can_cancel_pending_request: bool   # stop() cancela asyncio.Task (lógico)
can_stop_physical_playback: bool   # stop() detiene audio en hardware físico (HIL)
can_report_logical_activity: bool  # is_speaking refleja flags internos
can_report_physical_playback: bool # is_speaking verifica estado físico (HIL)
can_stream: bool                   # reservado para PlayStream adapter
requires_hil: bool                 # alguna capacidad requiere SDK/hardware real
```

---

### D-08 — UnitreeTTSAdapter stop declarado UNSUPPORTED sin documentar PlayStop()

**Sección afectada**: §5.3, §12.2, §15.2, §15.3, §17

**Error en v1**:
```
StopCapability = UNSUPPORTED
TtsMaker() es fire-and-forget al SDK. No existe API de cancelación
en AudioClient sin HIL.
```

**Evidencia del error**:
Ambas copias del SDK contienen:
```python
# libs/unitree_sdk2_python-master/unitree_sdk2py/g1/audio/g1_audio_client.py
def PlayStop(self, app_name: str) -> int:
    ...
    return self.sdk.ServiceClientCallResponse(
        ROBOT_API_ID_AUDIO_STOP_PLAY, ...)
```
También registrado en `Init()` con `ROBOT_API_ID_AUDIO_STOP_PLAY`.

**Corrección en v2**:
- `PlayStop()` existe y está documentado
- Su compatibilidad con audio iniciado por `TtsMaker()` es DESCONOCIDA sin acceso HIL
- Decisión Stage B: NO invocar `PlayStop()` sin validación HIL
- `can_stop_physical_playback = False` para ambos adapters en Stage B
- Documentado para post-B/HIL stage: si PlayStop() resulta compatible con TtsMaker, puede habilitarse

---

### D-09 — Gate B1 con conteo fijo de casos pytest

**Sección afectada**: §20 Etapa B1

**Error en v1**:
```
EXIT_GATE = pytest test_audio_contract.py muestra 8 FAILED (no ERROR)
```

**Evidencia del error**:
Con parametrización sobre PiperTTSAdapter y UnitreeTTSAdapter, cada test ID puede generar 2 casos pytest. Con 8 IDs y 2 adapters → 16 casos. El gate de "8 FAILED" sería incorrecto.

**Corrección en v2**:
```
EXIT_GATE = pytest --collect-only test_audio_contract.py muestra los 8 AUDIO-CONTRACT IDs;
            pytest test_audio_contract.py muestra N FAILED (no ERROR);
            N puede ser > 8 si los tests están parametrizados por adapter
```

---

### D-10 — Stage A compatibility no garantizada en B2 con métodos abstractos

**Sección afectada**: §9.1, §20 Etapa B2

**Error en v1**:
El plan declaraba en B2 que `stop/is_speaking/close` serían métodos `@abstractmethod` en `TTSAdapter`. Si PiperTTSAdapter y UnitreeTTSAdapter no los implementan todavía (se implementan en B3/B4), estos adapters no podrían ser instanciados.

**Evidencia del error**:
- AUDIO-CHAR-004 en `test_audio_characterization.py` instancia `PiperTTSAdapter` directamente
- AUDIO-CHAR-012 en `test_audio_char_unitree.py` instancia `UnitreeTTSAdapter` directamente
- Hacer `stop/is_speaking/close` abstractos en B2 sin implementarlos en B3/B4 simultáneamente produciría `TypeError: Can't instantiate abstract class` en los tests de Stage A

**Corrección en v2**:
Estrategia "concrete defaults":
- En B2, los nuevos métodos se agregan como implementaciones concretas NO abstractas en `TTSAdapter` base (stubs con comportamiento seguro: `stop()` no-op, `is_speaking` → False, `close()` no-op, `capabilities` → defaults)
- Las subclases concretas sobreescriben estos stubs en B3 (Piper) y B4 (Unitree)
- Stage A tests siguen pasando en todos los pasos de B2-B4 porque los adapters son instanciables

---

## 6. Verificación de ausencia de falsas correcciones

La autorrevisión verificó que los siguientes aspectos del plan v1 son correctos y fueron preservados sin modificación:

| ASPECTO | ESTADO_V1 | PRESERVADO_EN_V2 |
|---|---|---|
| fire-and-forget return semantics | CORRECTO | SÍ |
| `_run_alsa_playback` es método async | CORRECTO | SÍ |
| `_play_audio_alsa` es función top-level sync | CORRECTO | SÍ |
| ProcessPoolExecutor necesita top-level functions | CORRECTO | SÍ |
| asyncio.Task.cancel() no detiene hilo OS | CORRECTO | SÍ |
| Callers inventariados en §6 | CORRECTO | SÍ |
| Problemas del contrato en §7 | CORRECTO | SÍ |
| Alternativas evaluadas en §8 | CORRECTO | SÍ |
| Semántica de close() en §14 | CORRECTO (con adición de generation counter) | SÍ |
| Riesgos en §22 | CORRECTO | SÍ |
| H-01, H-03, H-04 | CORRECTO | SÍ |
| Secuencia de próximos prompts en §25 | CORRECTO (con ajuste de nombres) | SÍ |
| Acciones no realizadas en §26 | CORRECTO | SÍ |

---

## 7. Nueva sección añadida: §4A

Se añadió la sección §4A "Reconstrucción del ciclo de vida en runtime" como sección de referencia permanente en el plan. Esta sección:

1. **§4A.1**: Define las 5 fases del ciclo (REQUEST_TASK, SYNTHESIS_FUTURE, PROCESS_POOL_WORK, PLAYBACK_TASK, THREAD_POOL_WORK)
2. **§4A.2**: Distingue `_run_piper_synthesis` (sync top-level), `_play_audio_alsa` (sync top-level), y `_run_alsa_playback` (async método) con sus tipos correctos
3. **§4A.3**: Documenta formalmente la semántica de cancel asyncio.Task vs. executor workers
4. **§4A.4**: Documenta la semántica fire-and-forget y su implicación sobre TTSPlaybackError
5. **§4A.5**: Establece los mock boundaries correctos para cada tipo de función
6. **§4A.6**: Especifica el mecanismo de generation counter para supresión de stale results

Esta sección es la fuente de verdad que respalda las correcciones D-01 a D-05.

---

## 8. Cambios en §23 Decisiones Humanas

### H-01 (modificado)
Se añadió una nota sobre la posibilidad de crear un módulo separado `tts_contract.py` para alojar tipos de contrato generales, en lugar de continuar acumulando todo en `tts_unitree_client.py` (nombre engañoso si incluye LocalPiperTTSAdapter y clases de contrato). Esta es una recomendación de organización de módulos que puede resolverse en implementación sin necesidad de decisión humana previa.

### H-02 (nombre actualizado)
La opción recomendada fue renombrada de `INTERRUPT_PREVIOUS` a `LATEST_WINS_LOGICALLY` para reflejar el alcance real de la política (corrección D-06).

### H-03, H-04 (sin cambios)
Preservadas sin modificación — la autorrevisión no encontró errores en estas secciones.

---

## 9. Validación del plan corregido (v2)

```
RESULT_COUNT           = 1  (línea 6)
NEXT_ACTION_COUNT      = 1  (línea 1550)
AUDIO_CONTRACT_ID_COUNT = 8  (013, 014, 015, 016, 017, 018, 019, 020)
DUPLICATE_IDS          = 0
INVALID_CLAIM_COUNT    = 0
  asyncio.Event-in-sync-thread   = NO (solo aparece en negaciones)
  asyncio.sleep-as-sync-worker   = NO (solo aparece en negaciones)
  task-cancels-thread            = NO (explícitamente negado en §4A.3)
  TTSPlaybackError-to-caller     = NO (explícitamente eliminada)
  weak-cancellation-assertion    = NO (generation counter documentado)
  fixed-pytest-case-count        = NO (gate dice "N casos, puede ser > 8")
PLAN_V2_SIZE  = 74009 bytes
PLAN_V2_LINES = 1551
PLAN_V2_SHA256 = BC25B5B9698719E8A6A38FDE7AE38F098C6554C984C2D536E9202B49300A53E6
```

---

## 10. Acciones no realizadas

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
GIT_MUTATED                = NO
  (no add, commit, amend, push, fetch, pull, merge, rebase,
   cherry-pick, reset, restore, checkout, switch, stash, clean)
```

---

## 11. Próxima acción

```
NEXT_ACTION = HUMAN_REVIEW_CORRECTED_I01_STAGE_B_TTS_CONTRACT_PLAN
```

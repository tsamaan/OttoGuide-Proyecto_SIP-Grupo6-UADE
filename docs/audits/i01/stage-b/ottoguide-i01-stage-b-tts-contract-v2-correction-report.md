# OttoGuide I-01 Stage B — Second-Pass TTS Contract Correction Report

## 1. Resultado

```
RESULT = I01_STAGE_B_PLAN_V2_REMAINING_CONTRADICTIONS_CORRECTED_READY_FOR_HUMAN_REVIEW
```

## 2. Decisión humana de entrada

```
HUMAN_REVIEW_CORRECTED_I01_STAGE_B_TTS_CONTRACT_PLAN = CHANGES_REQUESTED
PLAN_V2 = NO_APROBADO
IMPLEMENTATION_STAGE_B = NO_AUTORIZADA
COMMIT = NO_AUTORIZADO
PUSH = NO_AUTORIZADO
```

## 3. Baselines

- Branch esperado: `review/orchestrator-unification`.
- HEAD esperado y verificado: `68967c85e0063e0b4d08b9411ff8431941ad2a35`.
- Parent esperado y verificado: `2ef63ebaa987cff34f722c521da4aeeeb5ba2646`.
- Plan v2 antes: SHA256=`BC25B5B9698719E8A6A38FDE7AE38F098C6554C984C2D536E9202B49300A53E6`; SIZE=74009; LINE_COUNT=1551.
- Plan v3 después: SHA256=`086B5957F1E09ACADFC2EC33E4B3ADFFADF130466A2663364AD4625E24773269`; SIZE=55755; LINE_COUNT=1356.
- Autorrevisión previa preservada: SHA256=`5C46BCAE5990037824356F04BE3B789E82DAC92101F0114A4E537EEEE0F4A398`; SIZE=17202; LINE_COUNT=402.

## 4. Archivos leídos

- `audit-reports/ottoguide-i01-stage-b-tts-contract-plan.md` — SIZE=55755; LINE_COUNT=1356; SHA256=086B5957F1E09ACADFC2EC33E4B3ADFFADF130466A2663364AD4625E24773269; FULLY_READ=YES
- `audit-reports/ottoguide-i01-stage-b-tts-contract-self-review-report.md` — SIZE=17202; LINE_COUNT=402; SHA256=5C46BCAE5990037824356F04BE3B789E82DAC92101F0114A4E537EEEE0F4A398; FULLY_READ=YES
- `audit-reports/ottoguide-i01-audio-design.html` — SIZE=75308; LINE_COUNT=1201; SHA256=7AC7CFEAC8D22AD9A94D85D08853EC65835F4E6A36B46BD6E849D5FA19374980; FULLY_READ=YES
- `audit-reports/ottoguide-i01-stage-a-characterization-test-plan.md` — SIZE=49147; LINE_COUNT=832; SHA256=50C5DC151A5E5B2C550B4416ABED13158667AAB50B0ADC49F9EB945EDA549CBD; FULLY_READ=YES
- `audit-reports/ottoguide-i01-stage-a-implementation-report.md` — SIZE=8341; LINE_COUNT=156; SHA256=5C1855D715A4C253F1F0C26965B48222B967EB7663A91A29122000A9176F2627; FULLY_READ=YES
- `audit-reports/ottoguide-i01-stage-a-self-review-report.md` — SIZE=14293; LINE_COUNT=253; SHA256=2E7894A6437D706A62A9062110C50D835B367772B606A1C273B514409BB582D8; FULLY_READ=YES
- `audit-reports/ottoguide-i01-stage-a-local-commit-report.md` — SIZE=8612; LINE_COUNT=206; SHA256=2DFFB1404484A58C84A7AA052177719476C08A732F9DA8270929C8CA2B4933BB; FULLY_READ=YES
- `codigo ottoguide/src/interaction\tts_unitree_client.py` — SIZE=17627; LINE_COUNT=386; SHA256=592D930AF4FCB4C0D0A2E83A8D95F600FE3FF29E6968F7BB6B73F6F2213CDE7E; FULLY_READ=YES
- `codigo ottoguide/src/interaction\conversation_manager.py` — SIZE=69875; LINE_COUNT=1392; SHA256=D99E8E199864DE9E42B83C9298505B0325FFA7FC86A47D957620BE91700006C4; FULLY_READ=YES
- `codigo ottoguide/src/interaction\__init__.py` — SIZE=1353; LINE_COUNT=52; SHA256=5344F214321D1FC3A67741C4CFA5B742DF107F6EDBFDBA57B48030C74BFC07C1; FULLY_READ=YES
- `codigo ottoguide/config/settings.py` — SIZE=10086; LINE_COUNT=233; SHA256=B4A089FEA6AF6D472B192F89141F099664B78B52EB1317E6EC17ACC91EC6A78A; FULLY_READ=YES
- `codigo ottoguide/main.py` — SIZE=33667; LINE_COUNT=754; SHA256=2C09251D24C93B7963904F696AD9D64B0E54DBB512E574AAEDA0AE60533E1C52; FULLY_READ=YES
- `codigo ottoguide/tests/unit\test_audio_characterization.py` — SIZE=13848; LINE_COUNT=387; SHA256=AAA32A4D118BA87DAC9C435A1DE343EE2BA49CA78E4814570E47237C04349A58; FULLY_READ=YES
- `codigo ottoguide/tests/unit\test_audio_char_unitree.py` — SIZE=1702; LINE_COUNT=44; SHA256=F1A1678266CC697C7C471482ADE2B20D37C5D38D0F1D4030C31B7CE75452AA98; FULLY_READ=YES
- `codigo ottoguide/tests/unit\test_conversation_playback_lifecycle.py` — SIZE=15691; LINE_COUNT=349; SHA256=5F3B8E2B1ECB8C7DBB82F4849B3B5B12F13CC0FA0428A67960C81B972A522802; FULLY_READ=YES
- `codigo ottoguide/tests/unit\test_conversation_cloud_interlock.py` — SIZE=17784; LINE_COUNT=436; SHA256=24D8A76A539E38E2888F4DEA62C51316EE2DB7A82C233DD1872D8DEF5CFC9476; FULLY_READ=YES
- `codigo ottoguide/libs/unitree_sdk2_python\unitree_sdk2py\g1\audio\g1_audio_client.py` — SIZE=2270; LINE_COUNT=71; SHA256=64A9942C1278B3B5BADF2AE7D1B871AC785F5FD3DEDA9404E97088B1E9AFF74B; FULLY_READ=YES
- `codigo ottoguide/libs/unitree_sdk2_python-master\unitree_sdk2py\g1\audio\g1_audio_client.py` — SIZE=3600; LINE_COUNT=93; SHA256=BC04A64478C9AADBD682EA91208ECFF6E77FE16D139A42C8E0C81BDCC29AF11B; FULLY_READ=YES

## 5. Contradicciones restantes

```
REMAINING_CONTRADICTIONS_REVIEWED = 8
REMAINING_CONTRADICTIONS_CORRECTED = 8
UNRESOLVED_CONTRADICTIONS = 0
```

## 6. Corrección RC-01

Se fijó una arquitectura Piper inequívoca: `LocalPiperTTSAdapter` para ONNX/ALSA y `PiperDockerTTSAdapter` para Docker/WAV/paplay. El símbolo legacy `PiperTTSAdapter` queda como alias o reexport temporal del Docker adapter.

## 7. Corrección RC-02

B2 conserva `speak()` y hace `synthesize_and_play()`, `stop()`, `is_active`, `capabilities` y `close()` concretos por defecto. Resultado: `B2_EXISTING_ADAPTERS_REMAIN_INSTANTIABLE = YES`.

## 8. Corrección RC-03

El plan declara que cancelar la task asyncio que espera `run_in_executor()` no detiene el worker ya iniciado en `ThreadPoolExecutor`; el playback físico puede continuar hasta consumir el buffer PCM completo o hasta fallo del dispositivo.

## 9. Corrección RC-04

`AUDIO-CONTRACT-017` ahora exige mock async controlado, referencia inequívoca a `playback_task`, observación de `CancelledError` y assertion fuerte sobre cancelación.

## 10. Corrección RC-05

`AUDIO-CONTRACT-018` ahora cubre cleanup real: task cancelada/removida, `is_active=False`, executor propio cerrado una vez, executor inyectado preservado, idempotencia y `TTSClosedError` post-close.

## 11. Corrección RC-06

`AUDIO-CONTRACT-020` separa supresión de síntesis obsoleta de reemplazo lógico de playback, y distingue request task de playback task.

## 12. Corrección RC-07

`TTSCapabilities` quedó canónico con seis campos explícitos. `AUDIO-CONTRACT-013` verifica capabilities de forma directa. Unitree no promete stop físico ni reporte físico.

## 13. Corrección RC-08

B1 usa `importlib`/`getattr` para evitar errores de collection por símbolos inexistentes; los fallos esperados ocurren como assertions runtime.

## 14. Arquitectura Piper final

```
H01_RECOMMENDED_OPTION = DEDICATED_LOCAL_PIPER_ADAPTER
PIPER_ADAPTER_ARCHITECTURE = LocalPiperTTSAdapter + PiperDockerTTSAdapter + UnitreeTTSAdapter
```

## 15. Contrato B2 compatible

```
B2_COMPATIBILITY_STRATEGY = speak legacy abstracto; synthesize_and_play concreto delega en speak; defaults concretos para stop/is_active/capabilities/close
B2_EXISTING_ADAPTERS_REMAIN_INSTANTIABLE = YES
```

## 16. Semántica ALSA

```
STAGE_B_STOP_SEMANTICS = LOGICAL_BEST_EFFORT
PHYSICAL_PLAYBACK_AFTER_ASYNC_TASK_CANCEL = MAY_CONTINUE_UNTIL_FULL_PCM_BUFFER_IS_CONSUMED_OR_DEVICE_FAILURE
```

## 17. Política de concurrencia

```
RECOMMENDED_CONCURRENCY_POLICY = LATEST_WINS_LOGICALLY
```

## 18. Capabilities

```
RECOMMENDED_CAPABILITIES_MODEL = TTSCapabilities(can_invalidate_stale_request, can_stop_physical_playback, can_report_logical_activity, can_report_physical_playback, can_stream, requires_hil)
CAPABILITIES_ASSERTIONS_EXPLICIT = YES
```

## 19. AUDIO-CONTRACT-013

Rediseñado para verificar tipo, dataclass frozen/slots, igualdad, inmutabilidad, los seis campos por adapter, `is_active=False` inicial y texto vacío sin síntesis ni playback.

## 20. AUDIO-CONTRACT-017

```
AUDIO_CONTRACT_017_STRONG_CANCELLATION_ASSERTION = YES
```

## 21. AUDIO-CONTRACT-018

```
AUDIO_CONTRACT_018_CLEANUP_COVERAGE = COMPLETE
```

## 22. AUDIO-CONTRACT-020

```
REQUEST_TASK_AND_PLAYBACK_TASK_DISTINGUISHED = YES
STALE_RESULT_SUPPRESSION_TESTED = YES
```

## 23. Modelo B1

```
B1_COLLECTION_ERRORS_EXPECTED = 0
B1_RUNTIME_FAILURE_MODEL = ASSERTION_FAILURES_AFTER_COLLECTION
```

## 24. Secuencia B1-B8

B1 tests rojos; B2 contrato compatible; B3 LocalPiper; B4 PiperDocker; B5 Unitree offline; B6a construcción/inyección; B6b callers/wiring; B7 autorrevisión/regresión; B8 aprobación humana y commit.

## 25. H-01..H-04

- H-01: LocalPiperTTSAdapter dedicado separado de PiperDockerTTSAdapter.
- H-02: LATEST_WINS_LOGICALLY.
- H-03: TtsMaker solamente, offline, sin stop físico ni PlayStream.
- H-04: B6a construcción/inyección y B6b migración de callers.

## 26. Diff documental

Clasificación de hunks validada antes del reemplazo atómico:

| CORRECTION_ID | SECTION | DEFECT | BEFORE | AFTER | AUTHORIZED |
|---|---|---|---|---|---|
| RC-03 | §4A | stop ALSA descrito como frame actual | duración física subestimada | buffer PCM completo o fallo | YES |
| RC-01/02/03/07 | §9-18 | contrato objetivo ambiguo | Piper identidad mixta, B2 abstracto, capabilities ambiguas | arquitectura separada, B2 compatible, capabilities canónicas | YES |
| RC-04/05/06/08 | §19-20 | tests débiles o collection riesgosa | assertions insuficientes y B1 con ImportError posible | tests fuertes y runtime failures | YES |
| RC-01/07 | §21-23 | impacto, riesgos y decisiones ambiguas | H-01/H-03/H-04 no eran inequívocas | cuatro decisiones exactas | YES |
| ALL | §24-25 | gates/secuencia v2 | B1-B6 | B1-B8 | YES |
| ALL | §27-28 | autorrevisión v2 y next action viejo | versión 2 | corrección segunda pasada v3 | YES |

```
UNEXPECTED_DIFF_HUNK_COUNT = 0
BASELINE_HISTORY_CHANGED = NO
STAGE_A_RESULTS_CHANGED = NO
COMMIT_SHA_CHANGED = NO
TEST_NODE_ID_HISTORY_CHANGED = NO
```

## 27. Validación final

```
RESULT_FIELD_COUNT = 1
NEXT_ACTION_FIELD_COUNT = 1
CONTRACT_VERSION = 3
LOGICAL_AUDIO_CONTRACT_ID_COUNT = 8
HUMAN_DECISION_COUNT = 4
INVALID_PIPER_IDENTITY_AMBIGUITY_COUNT = 0
INVALID_B2_ABSTRACT_INSTANTIATION_BREAK_COUNT = 0
INVALID_ALSA_CURRENT_FRAME_STOP_CLAIM_COUNT = 0
INVALID_REQUEST_TASK_EQUALS_PLAYBACK_TASK_COUNT = 0
INVALID_WEAK_CANCELLATION_OR_ASSERTION_COUNT = 0
INVALID_018_IDEMPOTENCE_ONLY_COUNT = 0
INVALID_IMPLICIT_CAPABILITIES_COVERAGE_COUNT = 0
INVALID_UNITREE_PHYSICAL_STOP_COUNT = 0
INVALID_UNITREE_PHYSICAL_SPEAKING_COUNT = 0
INVALID_B1_IMPORT_COLLECTION_ERROR_EXPECTATION_COUNT = 0
INVALID_FIXED_EIGHT_CASE_COUNT = 0
```

## 28. Estado Git

```
REPOSITORY_TOPLEVEL = <repo-root>
BRANCH = review/orchestrator-unification
HEAD_BEFORE = 68967c85e0063e0b4d08b9411ff8431941ad2a35
HEAD_AFTER = 68967c85e0063e0b4d08b9411ff8431941ad2a35
HEAD_PARENT = 2ef63ebaa987cff34f722c521da4aeeeb5ba2646
WORKTREE_BEFORE = CLEAN
WORKTREE_AFTER = CLEAN
```

## 29. Acciones no realizadas

```
SOURCE_CODE_FILES_MODIFIED = 0
TEST_FILES_MODIFIED = 0
DEPENDENCY_FILES_MODIFIED = 0
COMMITS_CREATED = 0
COMMITS_AMENDED = 0
PUSH_PERFORMED = NO
GITHUB_ACCESSED = NO
EXTERNAL_NETWORK_ACCESSED = NO
ROBOT_ACCESSED = NO
ROS_GRAPH_ACCESSED = NO
AUDIO_PLAYBACK_EXECUTED = NO
```

## 30. Riesgos

- La implementación Stage B sigue no autorizada.
- PlayStream y stop físico Unitree requieren HIL posterior.
- El alias legacy `PiperTTSAdapter` debe manejarse con cuidado en implementación para no reintroducir ambigüedad.

## 31. Próxima acción

```
NEXT_ACTION = HUMAN_REVIEW_I01_STAGE_B_TTS_CONTRACT_PLAN_V3
```

---

## Corrección documental posterior a revisión humana de v3

```
HUMAN_REVIEW_V3_RESULT = CHANGES_REQUESTED_MINIMAL
DOCUMENTARY_CORRECTION_SCOPE = DC-01, DC-02, DC-03, DC-04

CORE_ARCHITECTURE_CHANGED = NO
CONTRACT_SEMANTICS_CHANGED = NO
TEST_DESIGN_CHANGED = NO
IMPLEMENTATION_SEQUENCE_STRUCTURE_CHANGED = NO
IMPLEMENTATION_STAGE_COUNT_CORRECTED = 9

AUDIO_CHAR_011_HISTORICAL_TERM = is_speaking/speaking
TARGET_LOGICAL_ACTIVITY_PROPERTY = is_active

B2_COMPATIBILITY_BRIDGE_CLARIFIED = YES
DOCUMENTARY_POST_REVIEW_CORRECTION_APPLIED = YES

NEXT_ACTION = HUMAN_APPROVAL_I01_STAGE_B_TTS_CONTRACT_PLAN_V3
```

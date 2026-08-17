# OttoGuide I-01 Stage B — Documentación contractual TTS

## Estado

```
DOCUMENTATION_STATUS = APPROVED_FOR_REVIEW
CONTRACT_VERSION = 3
IMPLEMENTATION_STATUS = NOT_STARTED
COMMIT_STATUS = NOT_CREATED
PUBLICATION_STATUS = NOT_PUSHED
```

## Baseline Git

```
SOURCE_BRANCH = review/orchestrator-unification
SOURCE_HEAD   = 68967c85e0063e0b4d08b9411ff8431941ad2a35
```

El HEAD identifica el código inspeccionado durante la planificación.
La inclusión de esta documentación no implica que Stage B haya sido
implementado.

## Decisiones aprobadas

```
H-01 = DEDICATED_LOCAL_PIPER_ADAPTER
H-02 = LATEST_WINS_LOGICALLY
H-03 = UNITREE_TTSMAKER_ONLY_OFFLINE_STAGE_B
H-04 = SPLIT_B6A_AND_B6B
```

- LocalPiperTTSAdapter: Piper ONNX/ALSA.
- PiperDockerTTSAdapter: Docker/WAV/paplay.
- UnitreeTTSAdapter: TtsMaker solamente en Stage B offline.
- PlayStream, stop físico y HIL quedan diferidos.

## Archivos

| FILE | PURPOSE | SOURCE_SHA256 | COPY_SHA256 | BYTE_IDENTICAL |
|---|---|---|---|---|
| ottoguide-i01-stage-b-tts-contract-plan.md | Plan contractual TTS Stage B v3 | 60ecb09019bf96850984d80c6baa4af5ecb0c8be4f075488327cfb39ea5b5bd0 | 60ecb09019bf96850984d80c6baa4af5ecb0c8be4f075488327cfb39ea5b5bd0 | YES |
| ottoguide-i01-stage-b-tts-contract-self-review-report.md | Informe de autorrevisión correctiva del plan (v1→v2) | 5c46bcae5990037824356f04be3b789e82dac92101f0114a4e537eeee0f4a398 | 5c46bcae5990037824356f04be3b789e82dac92101f0114a4e537eeee0f4a398 | YES |
| ottoguide-i01-stage-b-tts-contract-v2-correction-report.md | Informe de corrección de segunda pasada (v2→v3) | b817a772086906f6ae1da1040d6903175fb8c0067cb3465e36a26594a36ebc4e | b817a772086906f6ae1da1040d6903175fb8c0067cb3465e36a26594a36ebc4e | YES |

## Alcance

- documentación únicamente;
- sin cambios de producción;
- sin cambios de tests;
- sin cambios de dependencias;
- sin implementación TTS;
- sin acceso a robot;
- sin publicación remota.

## Modos de copia

```
PLAN_COPY_MODE = BYTE_IDENTICAL
SELF_REVIEW_COPY_MODE = BYTE_IDENTICAL
CORRECTION_REPORT_COPY_MODE = SANITIZED_PUBLICATION_COPY
CONTENT_SEMANTICS_PRESERVED = YES
LOCAL_PATHS_SANITIZED = YES
```

El plan y el informe de autorrevisión son copias byte-for-byte de los artefactos externos aprobados. El informe de corrección fue sanitizado para reemplazar rutas absolutas locales por rutas relativas al repositorio; el contenido semántico y los resultados técnicos se preservaron íntegramente.

## Trazabilidad

README.md y SHA256SUMS.txt son artefactos de publicación creados para facilitar revisión y trazabilidad.

## Próxima acción

```
NEXT_ACTION = REVIEW_STAGE_B_DOCUMENTATION_COPY
```

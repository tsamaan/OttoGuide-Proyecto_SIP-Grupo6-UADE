# AGENTS.md — Política permanente de cierre y archivo de OttoGuide

Este archivo define las reglas operativas duraderas para cualquier agente o persona que trabaje con OttoGuide después de la consolidación final del proyecto académico.

## 1. Estado normativo del árbol

```text
PROGRAM_OBJECTIVE = OTTOGUIDE_FINAL_PROJECT_CLOSURE
TREE_CONTENT_STATUS = FINAL_RELEASE_TREE
PROJECT_PHASE = FINAL_PROJECT_CLOSED
BRANCH_RECONCILIATION = CLOSED
PRODUCTIVE_DEVELOPMENT = FROZEN
ACTIVE_PRODUCTIVE_NEXT_ACTION = NO_FURTHER_PRODUCTIVE_DEVELOPMENT
GIT_PUBLICATION_STATE = DYNAMIC_REMOTE_STATE_NOT_EMBEDDED
```

`FINAL_RELEASE_TREE` describe el contenido estable del árbol. No describe qué ref remoto apunta a él en un instante determinado. El estado de publicación de `feature`, `review`, `main`, mirror y canonical debe resolverse directamente desde GitHub antes de cualquier operación.

La precedencia documental vigente es:

1. `AGENTS.md`: reglas operativas, seguridad y Git.
2. `docs/Arquitectura/CIERRE_FINAL_MVP.md`: contrato durable de publicación y cierre.
3. `README.md`: verdad pública de producto y evidencia.
4. `TODO.md`: limitaciones y continuidad futura no bloqueante.
5. `docs/Arquitectura/UNIFICACION_RAMAS_Y_HANDOFF.md` y `docs/Arquitectura/unification-state.json`: provenance y estado machine-readable estable.
6. Ledgers y snapshots históricos: evidencia; no instrucciones activas sin revisión.

Los `NEXT_ACTION`, R8, U3, U3C, P2C y demás microcheckpoints preservados históricamente no reabren desarrollo.

## 2. Raíces canónicas

- `docs/`: única raíz documental propia.
- `codigo ottoguide/`: núcleo robótico, runtime, integración, herramientas, configuración y tests.
- `ottoguide_web_app/`: aplicación web integrada.

No recrear raíces históricas como `documentacion general del proyecto/`, `OttoGuide IA/` ni `planificacion/` fuera de `docs/planning/`. No crear nuevas raíces por pilar ni reorganizar el árbol final por razones cosméticas.

## 3. Principios de ingeniería y evidencia

- Evidencia antes que intuición.
- Un único dominio técnico por checkpoint.
- Cambios pequeños, coherentes, trazables y reversibles.
- No ampliar alcance después del cierre salvo una nueva fase explícitamente autorizada.
- Fuente de verdad: código productivo > tests > documentación vigente > provenance histórica.
- Una afirmación de agente no sustituye evidencia verificable.
- No elevar validación offline o histórica a validación física actual.

Etiquetas de evidencia:

- `IMPLEMENTADO`;
- `VALIDADO_OFFLINE`;
- `VALIDADO_FISICAMENTE_HISTORICO`;
- `NO_VALIDADO_EN_ARBOL_FINAL`;
- `FUERA_DEL_ALCANCE_FINAL_MVP`;
- `RIESGO_RESIDUAL_O_CONTINUIDAD_FUTURA`.

## 4. Invariantes de arquitectura y seguridad

Permanecen vigentes:

- `ONE_FASTAPI = YES`;
- `ONE_TOUR_ORCHESTRATOR = YES`;
- `ONE_MISSION_FSM = YES`;
- `ONE_MOTION_AUTHORITY = YES`;
- `ONE_CAMERA_AUTHORITY_PER_DEVICE = YES`;
- `ONE_REAL_AUDIO_AUTHORITY = YES`;
- `CLOUD_IN_REAL_MODE = PROHIBITED`;
- `SILENT_REAL_FALLBACK = PROHIBITED`;
- `WORKER_MOTION_AUTHORITY = PROHIBITED`;
- `PLAYBACK_COMPLETED_BEFORE_NAVIGATION_RESUME = REQUIRED`;
- merges mayoristas de ramas históricas = prohibidos.

Ninguna operación documental o Git autoriza robot, SSH al robot, HIL, DDS real, Nav2 real, SLAM, audio físico, `/cmd_vel`, locomoción ni escritura en hardware. Cualquier trabajo físico futuro requiere un checkpoint separado, operador, hardstop, límites, rollback y autorización explícita.

## 5. Evidencia y archivos protegidos

No modificar sin una fase/checkpoint futuro dedicado:

- `docs/legacy/**`;
- `docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/otto_pipeline.cpp`;
- `docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/CMakeLists.txt`;
- `docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/scripts/otto_say.sh`;
- `codigo ottoguide/src/interaction/runtime_port.py`;
- `codigo ottoguide/src/interaction/jsonl_worker_supervisor.py`;
- `codigo ottoguide/src/interaction/worker_supervisor.py`.

El árbol final no debe recibir cambios productivos para “completar” roadmaps históricos.

## 6. Modelo Git duradero

```text
review/orchestrator-unification
    historia completa de desarrollo e integración autoritativa

main
    snapshot final de entrega, exactamente un commit raíz sin padres

feature/odom-tf-r2-p2-frame-semantics-covariance-contract
    staging de cierre; deja de ser autoridad después de publicar

ramas laterales/personales y audit/*
    provenance histórica; no candidatos de merge mayorista
```

La reconciliación de ramas está cerrada. No mergear, rebasear ni cherry-pickear ramas históricas completas para “ponerse al día”.

El contrato de publicación es:

1. resolver refs remotos frescos;
2. auditar el árbol final exacto;
3. promover ese mismo commit/tree por fast-forward a mirror `review`;
4. verificar;
5. promover el mismo commit/tree por fast-forward a canonical `review`;
6. verificar igualdad exacta;
7. crear un commit raíz `R` con `parents(R) = []` y `tree(R) = SEALED_FINAL_TREE`;
8. reemplazar `main` primero en mirror mediante lease/CAS y verificar;
9. reemplazar canonical `main` por exactamente el mismo `R` y verificar.

Ese procedimiento es política durable, no un `NEXT_ACTION` de producto. El estado de ejecución se resuelve remotamente.

## 7. Reglas de escritura

- Mirror antes que canonical.
- Fast-forward por defecto.
- `BLIND_FORCE = PROHIBITED`.
- No tags salvo autorización explícita.
- No merge ni rebase con el placeholder histórico de `main`.
- Revalidar el ref esperado inmediatamente antes de cada escritura.
- Cualquier drift inesperado produce fail-closed.

La única excepción al fast-forward es el reemplazo único del placeholder histórico de `main` por el root final, protegido por lease o compare-and-swap equivalente y conforme a `CIERRE_FINAL_MVP.md`.

## 8. Política de `main`

El modelo es `SINGLE_ROOT_FINAL_RELEASE`:

- `main` contiene exactamente un commit raíz;
- ese commit no tiene padres;
- su tree es exactamente `SEALED_FINAL_TREE`;
- mirror/main y canonical/main terminan en el mismo SHA y tree;
- la genealogía completa permanece en `review/orchestrator-unification`.

No convertir `main` en rama de desarrollo.

## 9. Continuidad

Para una sesión futura:

1. leer `AGENTS.md`, `README.md`, `TODO.md` y `docs/Arquitectura/CIERRE_FINAL_MVP.md`;
2. resolver GitHub live si interesa conocer el estado de publicación;
3. usar el handoff y `unification-state.json` sólo para provenance/estado estable;
4. no continuar U3/U3C/R8/P2C ni otras tareas históricas;
5. no iniciar nuevas capacidades salvo una nueva fase explícitamente autorizada.

```text
ACTIVE_PRODUCTIVE_NEXT_ACTION = NO_FURTHER_PRODUCTIVE_DEVELOPMENT
```

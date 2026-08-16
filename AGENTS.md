# AGENTS.md — Política vigente de cierre de OttoGuide

Este archivo define las reglas operativas vigentes para trabajar sobre el repositorio durante el cierre final del proyecto académico OttoGuide.

## 1. Estado y precedencia

- `PROGRAM_OBJECTIVE = OTTOGUIDE_FINAL_PROJECT_CLOSURE`
- `PROJECT_PHASE = FINAL_PROJECT_CLOSURE`
- `BRANCH_RECONCILIATION = CLOSED`
- `PRODUCTIVE_DEVELOPMENT = FROZEN`
- Rama candidata de cierre: `feature/odom-tf-r2-p2-frame-semantics-covariance-contract`.
- Rama de integración e historia técnica autoritativa: `review/orchestrator-unification`.
- Rama de entrega final: `main`.
- `WHOLESALE_BRANCH_MERGES = PROHIBITED`.

Para el cierre vigente, la precedencia documental es:

1. `AGENTS.md`: reglas operativas y de seguridad para agentes.
2. `docs/Arquitectura/CIERRE_FINAL_MVP.md`: contrato vigente de cierre y publicación.
3. `README.md`: verdad pública de producto y evidencia.
4. `TODO.md`: bloqueantes reales del cierre y continuidad futura no bloqueante.
5. `docs/Arquitectura/UNIFICACION_RAMAS_Y_HANDOFF.md`, `docs/Arquitectura/unification-state.json` y los ledgers R/U/P2C: evidencia histórica y de provenance.

Los campos históricos `NEXT_ACTION`, R8, U3, U3C u otros microcheckpoints conservados en ledgers anteriores **no son instrucciones activas de desarrollo** durante `FINAL_PROJECT_CLOSURE`. Se preservan para trazabilidad.

## 2. Raíces canónicas del repositorio

- `docs/`: única raíz documental. Toda documentación nueva debe vivir dentro de `docs/`.
- `codigo ottoguide/`: núcleo robótico, runtime, integración, herramientas, configuración y tests asociados.
- `ottoguide_web_app/`: aplicación web integrada del proyecto.

No realizar movimientos estructurales tardíos salvo que una auditoría final demuestre un bloqueante material. En particular:

- no recrear `documentacion general del proyecto/`;
- no recrear `planificacion/` fuera de `docs/planning/`;
- no crear nuevas raíces documentales por pilar;
- no crear `docs/audit/`; la ruta canónica es `docs/audits/`;
- no mover `ottoguide_web_app/` sólo para forzar una raíz de software única.

## 3. Principios de ingeniería y evidencia

- Evidencia antes que intuición.
- Mantener un único dominio técnico por checkpoint.
- Cambios pequeños, coherentes, trazables y reversibles.
- No ampliar alcance durante el cierre salvo bloqueante material demostrado.
- Fuente de verdad técnica, en orden: código productivo > tests > documentación vigente > ramas fuente históricas > documentación histórica.
- Una afirmación de agente no sustituye evidencia verificable.
- Los reportes externos deben resumirse o incorporarse a documentación versionada antes de convertirse en autoridad duradera.

Toda afirmación de capacidad debe distinguir, cuando corresponda:

- `IMPLEMENTADO`;
- `VALIDADO_OFFLINE`;
- `VALIDADO_FISICAMENTE_HISTORICO`;
- `NO_VALIDADO_EN_CANDIDATO_ACTUAL`;
- `FUERA_DEL_ALCANCE_FINAL_MVP`;
- `RIESGO_RESIDUAL_O_CONTINUIDAD_FUTURA`.

Nunca transformar evidencia offline o histórica en una afirmación de validación física actual.

## 4. Invariantes de arquitectura y seguridad

Se mantienen vigentes:

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

Ninguna tarea documental o de Git autoriza acceso al robot, SSH al robot, HIL, movimiento, audio real, ejecución física, `/cmd_vel`, locomoción, Nav2 real ni escritura en hardware. Cualquier acción física requiere autorización explícita y separada, hardstop disponible, operador presente, límites definidos y rollback previo.

## 5. Archivos y evidencia protegidos

No modificar sin un checkpoint específico dedicado:

- `docs/legacy/**`;
- `docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/otto_pipeline.cpp`;
- `docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/CMakeLists.txt`;
- `docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/scripts/otto_say.sh`;
- `codigo ottoguide/src/interaction/runtime_port.py`;
- `codigo ottoguide/src/interaction/jsonl_worker_supervisor.py`;
- `codigo ottoguide/src/interaction/worker_supervisor.py`.

Durante el cierre, no modificar código productivo salvo que una auditoría final identifique un defecto material que impida la entrega y exista autorización explícita para abrir ese dominio técnico.

## 6. Flujo Git vigente de cierre

### Lectura y auditoría

- Las inspecciones read-only pueden hacerse directamente contra GitHub.
- No crear ramas sólo para auditar, comparar o reconstruir contexto.
- Resolver refs remotos de forma fresca; no depender de aliases Git locales ni de SHAs efímeros embebidos como "HEAD actual" en documentación duradera.
- Inspeccionar ramas históricas sólo como provenance o para una comprobación de completitud; no reabrir decisiones de integración ya cerradas.

### Mutación del candidato

- Usar la feature de cierre existente; no crear una feature adicional para remediaciones finales.
- Antes de una escritura: verificar ref esperado, alcance exacto, ausencia de secretos y que el cambio pertenezca al único dominio técnico declarado.
- Los cambios de código requieren validación ejecutable local proporcional al riesgo antes de publicar candidato.
- Una remediación puramente documental de cierre puede materializarse como **un único commit atómico** sobre la feature existente cuando haya auditoría remota previa, precondición exacta del ref y autorización explícita del usuario en ese checkpoint.
- Nunca mezclar una remediación documental con código, runtime, tests, configuración o hardware.

### Orden de publicación

1. mirror;
2. auditoría remota independiente del candidato publicado;
3. promoción fast-forward a mirror `review/orchestrator-unification` sólo con GO y autorización explícita;
4. verificación independiente de mirror review;
5. promoción fast-forward a canonical `review/orchestrator-unification` sólo con autorización explícita nueva;
6. verificación de igualdad exacta mirror/canonical;
7. sellado del árbol final;
8. publicación final de `main` según `docs/Arquitectura/CIERRE_FINAL_MVP.md` y con autorizaciones separadas.

No autorizar implícitamente pasos posteriores por haber autorizado uno anterior.

## 7. Reglas de push y refs

- Mirror antes que canonical.
- Fast-forward por defecto.
- `force` ciego está prohibido.
- No tags salvo autorización explícita.
- No merge ni rebase con el `main` histórico no relacionado.
- No reemplazar `main` durante checkpoints de feature/review.
- La única excepción potencial al fast-forward es el reemplazo final, único y lease-guarded del placeholder histórico de `main` por el release raíz sellado; requiere precondición exacta, autorización explícita separada para mirror y canonical y verificación posterior. Esta excepción **no queda autorizada por este archivo**.

## 8. Política final de `main`

El modelo objetivo es `SINGLE_ROOT_FINAL_RELEASE`:

- el release final `R` debe ser un commit raíz (`R.parents = []`);
- `tree(R)` debe ser exactamente el árbol final sellado en review;
- mirror/main y canonical/main deben terminar en el mismo SHA `R` y el mismo tree;
- `main` no es base de integración ni conserva la genealogía de review;
- la historia técnica y de integración permanece en `review/orchestrator-unification` y en la documentación de provenance.

El placeholder histórico de `main` y su precondición exacta para el reemplazo se documentan en `docs/Arquitectura/CIERRE_FINAL_MVP.md` y deben revalidarse inmediatamente antes de cualquier escritura.

## 9. Definición operativa de GO de cierre

Un candidato puede avanzar sólo si:

- la documentación vigente expresa una única verdad de producto;
- no existen claims de validación física actual no demostrados;
- la estructura real del repositorio coincide con la documentada;
- no hay secretos ni residuos bloqueantes identificados por la auditoría;
- no se introdujo código productivo dentro de una remediación documental;
- el ref remoto coincide exactamente con la precondición esperada;
- el árbol final puede sellarse de forma reproducible;
- los pasos de publicación restantes conservan mirror-before-canonical y autorizaciones separadas.

Preferencias de estilo, refactors no necesarios, limpieza cosmética o roadmaps históricos no son por sí mismos motivos para reabrir desarrollo.

## 10. Continuidad

Para una sesión nueva:

1. leer `AGENTS.md`;
2. leer `README.md`;
3. leer `TODO.md`;
4. leer `docs/Arquitectura/CIERRE_FINAL_MVP.md`;
5. usar `UNIFICACION_RAMAS_Y_HANDOFF.md` y `unification-state.json` sólo cuando haga falta provenance o reconstrucción histórica.

El objetivo activo es cerrar y publicar el proyecto, no continuar R8/U3/U3C ni iniciar nuevas capacidades.

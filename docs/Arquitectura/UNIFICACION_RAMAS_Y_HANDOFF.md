# OttoGuide — Handoff vigente de cierre final

## 1. Estado operativo

```text
PROGRAM_OBJECTIVE = OTTOGUIDE_FINAL_PROJECT_CLOSURE
PROJECT_PHASE = FINAL_PROJECT_CLOSURE
BRANCH_RECONCILIATION = CLOSED
PRODUCTIVE_DEVELOPMENT = FROZEN
ACTIVE_RELEASE_INSTRUCTION = REMOTE_AUDIT_FINAL_CLOSURE_CANDIDATE_BEFORE_SEALING
```

Este documento ya no es un roadmap de unificación U*. Es el gateway de provenance para retomar el cierre final desde un clon nuevo sin depender de chats, workstations históricas o adjuntos externos.

## 2. Autoridad vigente

Orden de lectura para una sesión nueva:

1. `AGENTS.md` — reglas operativas, seguridad y Git.
2. `README.md` — verdad pública de producto y evidencia.
3. `TODO.md` — alcance diferido y validaciones futuras.
4. `docs/Arquitectura/CIERRE_FINAL_MVP.md` — contrato de sellado/publicación.
5. `docs/Arquitectura/unification-state.json` — estado machine-readable del cierre.
6. Este handoff — provenance y reanudación.
7. Snapshots U-series y ledgers históricos sólo cuando sea necesario reconstruir decisiones.

## 3. Provenance U-series preservado

El handoff U-series anterior no se borró ni se reescribió para aparentar actualidad. Su blob exacto se conserva en:

`docs/Historico/Final_Closure_Predecessors/UNIFICACION_RAMAS_Y_HANDOFF_U_SERIES_SUPERSEDED.md`

El estado machine-readable U-series anterior se conserva en:

`docs/Historico/Final_Closure_Predecessors/unification-state-u-series-superseded.json`

Los `NEXT_ACTION` U3/U3C, deudas, baselines y roadmaps que aparecen allí son evidencia histórica. No son instrucciones activas durante `FINAL_PROJECT_CLOSURE`.

## 4. Modelo de repositorios y ramas

```text
CANONICAL_AUTHORITY = tsamaan/OttoGuide-Proyecto_SIP-Grupo6-UADE
MIRROR_STAGING = LucasCap12/OttoGuide-Proyecto_SIP-Grupo6-G1-EDU
CANDIDATE_BRANCH = feature/odom-tf-r2-p2-frame-semantics-covariance-contract
INTEGRATION_HISTORY = review/orchestrator-unification
FINAL_DELIVERY_BRANCH = main
FINAL_MAIN_MODEL = SINGLE_ROOT_FINAL_RELEASE
WHOLESALE_BRANCH_MERGES = PROHIBITED
```

Los SHAs vivos se resuelven desde GitHub inmediatamente antes de cada decisión. No se embebe un HEAD efímero como autoridad duradera.

## 5. Secuencia restante de cierre

```text
mirror feature candidate
-> independent remote audit
-> SEALED_FINAL_TREE
-> mirror review fast-forward [fresh explicit authorization]
-> verify
-> canonical review fast-forward [separate fresh explicit authorization]
-> verify identical tree
-> create root release R with tree(R) = SEALED_FINAL_TREE and parents(R) = []
-> mirror main [fresh explicit authorization + lease/CAS]
-> verify
-> canonical main = same R [separate fresh explicit authorization]
-> final verification
```

Autorizar un paso no autoriza los siguientes. Mirror siempre precede a canonical. `main` no se mergea ni rebasea con `review`.

## 6. Verdad de evidencia

El candidato puede contener implementación y validaciones offline sin que eso pruebe operación física actual. En particular, no se debe inferir del repositorio:

- publicación física actual de `/odom`, `/tf`, `/tf_static` o `/map`;
- autonomía Nav2 o SLAM/map físicamente validada;
- tour físico completo validado;
- audio, cámara o runtime DDS/ROS actuales validados sobre este árbol exacto;
- autorización para robot, SSH, HIL, movimiento o hardware.

La evidencia física histórica conserva provenance, no recertifica el candidato actual.

## 7. Alcance académico

El diseño académico original contempló un piloto UADE Monserrat por Lima 3/Lima 2 con cinco paradas de diálogo. También excluyó otros pisos/campus, IA abierta ilimitada durante el recorrido estructurado, integración con sistemas internos UADE y soporte multilingüe.

Ese alcance describe el producto académico previsto; no constituye por sí mismo evidencia de validación física del recorrido.

## 8. Reanudación fail-closed

Antes de cualquier escritura:

- resolver de nuevo candidate, mirror review, canonical review y ambos `main`;
- verificar el alcance autorizado;
- comprobar que el cambio pertenece a un único dominio técnico;
- no mezclar documentación con código/configuración/hardware;
- detenerse ante drift inesperado de ref o tree.

El siguiente paso vigente tras la publicación de esta reconciliación es una auditoría remota independiente del candidato del mirror. No ejecutar U3C ni reabrir desarrollo productivo desde este handoff.

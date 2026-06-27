# Evidencia Fase 2H.2.5 -- Recuperación local

Generado: 2026-06-23T17:45:00Z  
Corrección: evidencia actualizada en sesión de recuperación (sustituye claims incorrectos del commit `7dbc4d9`).  
Rama: `robot`  
HEAD: `d59376e6d1bebee0b211367b4ebca6c69477ef28`  
Commit parcial preservado: `ba8de8a77b20cf7526e899537651c575938068cc`  
Baseline previo: `cd3177b74948fa9d49ea87d8297430eccbad2712`

## Contenido

- `test_summary.json` -- resultados de pruebas Windows y WSL (sintaxis, targeted, unit, full, static verifier, parent CLI timeout x3, pytest suite completa, characterization runtime).
- `lease_monotonic_summary.json` -- validación monotónica de la cleanup lease (8/8 tests unitarios + 3/3 corridas reales del parent CLI timeout en WSL, dominios 20/24/28).
- `p0_hardening_summary.json` -- auditoría del P0 Decision Engine schema v2 (integridad, inputs humanos explícitos, command log, collection completeness, fixture E2E 13/13, WSL targeted 139/139 PASS).
- `runtime_characterization_summary.json` -- caracterización de inestabilidad runtime: diagnóstico 4/4 PASS, char_run_1 3/4 PASS, char_run_2 3/4 PASS; clasificación OBSERVED_ROOT_CAUSE_NOT_PROVEN.

## Correcciones respecto a commit 7dbc4d9

El commit `7dbc4d9` fue generado contra la distro WSL incorrecta (Ubuntu default sin pytest ni ROS2). La sesión de recuperación usó correctamente `Ubuntu-24.04` (`wsl.exe -d Ubuntu-24.04`), que tiene:
- pytest 7.4.4 (sistema python3)
- ROS2 Jazzy en `/opt/ros/jazzy`
- Nav2 instalado

Correcciones principales:
1. **parent_cli_timeout_x3 domain IDs**: 221/225/229 → 20/24/28 (los dominios reales de las corridas).
2. **pytest_suites**: de `BLOCKED_ENVIRONMENT_GAP` a `PASS_WITH_PREEXISTING_ENVIRONMENT_GAP` (662 passed, 38 skipped, 9 errors de pytest_asyncio -- misma firma que 2H.2.4).
3. **runtime_characterization**: de `NOT_EXECUTED_ENVIRONMENT_UNAVAILABLE` a resultados reales (diagnóstico 4/4, char1 3/4, char2 3/4).
4. **ros_install_present**: de `false` a `true` (Ubuntu-24.04 tiene `/opt/ros/jazzy`).

## Resultados consolidados

### Windows
- Sintaxis (`py_compile`): **PASS**
- Targeted 2H25 (4 archivos): **PASS** (101 passed, 60 skipped, 47 subtests)
- Monotonic lease (8/8): **PASS**
- P0 contract + E2E (60 passed, 1 skipped POSIX-only): **PASS**
- Unit suite completa: **PASS** (624 passed, 85 skipped)
- Full repo suite: **FAIL_PREEXISTING_PROVEN** (643 passed, 1 failed preexistente en test_tour_orchestrator.py, 109 skipped)
- Static verifier: **PASS**

### WSL (Ubuntu-24.04)
- Sintaxis (`py_compile`): **PASS**
- Static verifier: **PASS**
- Targeted 2H25 POSIX (defect fixes): **PASS** (139 passed, SHA d59376e)
- Unit suite completa: **PASS_WITH_PREEXISTING_ENVIRONMENT_GAP** (662 passed, 38 skipped, 9 errors pytest_asyncio)
- Parent CLI timeout x3 (dominios 20, 24, 28): **PASS_3_CONSECUTIVE**
- Runtime characterization (12 scenarios, 10 PASS, 2 FAIL): **CHARACTERIZED_ROOT_CAUSE_NOT_PROVEN**

## Characterization runtime

| Corrida | Dominio base | Escenario fallado | Error |
|---------|-------------|-------------------|-------|
| Diagnostic | 32-35 | ninguno | 4/4 PASS |
| Char run 1 | 36-39 | emergency_cancel (39) | controller_server NOT_ACTIVE:inactive, waypoint_follower LIFECYCLE_QUERY_FAILED (10 intentos, 2 errors) |
| Char run 2 | 40-43 | interaction_cancel (42) | 7/7 componentes NOT_DISCOVERED (12 intentos, carga acumulada) |

Clasificación: **OBSERVED_ROOT_CAUSE_NOT_PROVEN**. Consistente con defecto de deadline compartida/consulta secuencial en `wait_for_components_deterministic()`, pero no probado con test determinista reproducible. Sin residuos de proceso (group_alive_after=False, sin zombies/orphans) en los 12 escenarios.

## Lo que quedó completamente validado

- Lease monotónica v2: 8/8 tests + 3/3 corridas parent CLI WSL -- **MONOTONIC_VALIDATED**
- P0 Decision Engine v2: 47/47 subtests + 13/13 fixture E2E + static verifier PASS -- **HARDENED_OFFLINE_PENDING_FIELD_AUDIT**
- Fixes POSIX: defecto A (permisos de bundle) y defecto B (aserción monotónica) -- **139/139 PASS en WSL**
- Sin regresiones nuevas.

## Manifest

Ver `evidence_manifest.json` / `evidence_manifest.sha256` para los hashes de los cuatro archivos de resumen.

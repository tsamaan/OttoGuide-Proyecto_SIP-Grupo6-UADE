# Evidencia Fase 2H.2.5 -- Recuperación local

Generado: 2026-06-23T11:50:56Z
Rama: `robot`
Commit parcial preservado: `ba8de8a77b20cf7526e899537651c575938068cc`
Baseline previo: `cd3177b74948fa9d49ea87d8297430eccbad2712`

## Contenido

- `test_summary.json` -- resultados de pruebas Windows y WSL (sintaxis, targeted, unit, full, static verifier, parent CLI timeout x3).
- `lease_monotonic_summary.json` -- validación monotónica de la cleanup lease (8/8 tests unitarios + 3/3 corridas reales del parent CLI timeout en WSL).
- `p0_hardening_summary.json` -- auditoría del P0 Decision Engine schema v2 (integridad, inputs humanos explícitos, command log, collection completeness, fixture E2E 13/13).
- `runtime_characterization_summary.json` -- intento de caracterización de inestabilidad runtime; **bloqueado** por ausencia de entorno ROS2 en esta sesión (ver detalle).

## Hallazgo crítico de esta recuperación

El reporte previo de la Fase 2H.2.4
(`Operaciones_HIL/Evidencia/2H24/runtime_summary.json`) registra que sus
corridas reales usaron `source /opt/ros/jazzy/setup.bash` en WSL. En esta
sesión de recuperación, la única instancia WSL accesible (Ubuntu 24.04.4
LTS) **no tiene ningún instalador de ROS2** (`/opt/ros` no existe), ni
`pytest`/`pytest_asyncio` instalados fuera del venv de Windows. Instalar
estas dependencias está explícitamente prohibido por las restricciones de
seguridad de esta tarea (no `apt`, no `rosdep`, no `pip install`).

Como consecuencia:

- La caracterización de inestabilidad runtime (Sección 12) **no pudo
  ejecutarse** con ROS2/Nav2 real. Se realizó en su lugar una auditoría
  estática del algoritmo `wait_for_components_deterministic()` (ver
  `runtime_characterization_summary.json`), clasificada honestamente como
  `NOT_REPRODUCED_IN_2H25` -- nunca como una causa probada.
- La suite pytest completa de WSL (`tests/unit/`, `tests/`) **no pudo
  ejecutarse** por falta de `pytest`/`pytest_asyncio`. Se ejecutaron en su
  lugar: verificación de sintaxis (`py_compile`), el static verifier
  (`verify_sandbox_isolation.py`, sin dependencias de terceros), y el
  driver real `run_2h24_parent_cli_timeout.py` (solo stdlib, 3 corridas
  limpias, dominios 221/225/229).
- El `runtime_verifier` (`--runtime`, requiere `ROS_DOMAIN_ID` activo con
  grafo ROS2 real) tampoco pudo ejecutarse por la misma ausencia de ROS2.

Ninguno de estos bloqueos es atribuible a un cambio de código de esta
fase ni de `ba8de8a`: son una limitación del entorno de ejecución
disponible en esta sesión específica, distinta del entorno que tuvo la
sesión de 2H.2.4.

## Lo que sí quedó completamente validado

- Lease monotónica v2: 8/8 tests deterministas + 3/3 corridas reales del
  parent CLI timeout (WSL, stdlib únicamente) -- `MONOTONIC_VALIDATED`.
- P0 Decision Engine v2: 47/47 contract subtests + 13/13 fixture E2E +
  static verifier PASS -- `HARDENED_OFFLINE_PENDING_FIELD_AUDIT`.
- Suite completa Windows: 643 passed, 1 failed (preexistente, no tocado
  por esta fase), 109 skipped -- `FAIL_PREEXISTING_PROVEN`.
- Sin regresiones nuevas en ningún test ejecutable.

## Manifest

Ver `evidence_manifest.json` / `evidence_manifest.sha256` para los hashes
de los cuatro archivos de resumen.

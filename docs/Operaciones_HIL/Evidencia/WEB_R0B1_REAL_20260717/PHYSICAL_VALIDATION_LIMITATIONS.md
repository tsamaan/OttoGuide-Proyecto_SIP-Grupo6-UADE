# Limitaciones de la validación física — sesión r0b1-20260717T215047Z

Esta sesión demuestra que la herramienta HIL read-only puede mostrar
telemetría física real en un dashboard Web con enlace SSH durable. **No**
demuestra ninguna de las siguientes capacidades, y ningún documento derivado
debe afirmarlas:

## No validado en esta sesión

- **`/odom` como fuente de control**: se recibieron mensajes
  `rt/odommodestate` y `rt/lf/odommodestate` y se mostraron en el dashboard,
  pero no se validó su uso como entrada de un lazo de control, localización o
  fusión con otros sensores.
- **TF**: no se publicó, consumió ni validó ningún árbol de transformaciones.
- **Nav2**: no se ejecutó, configuró ni validó ninguna pila de navegación.
- **Navegación autónoma**: el robot permaneció inmóvil; no se ejecutó ningún
  movimiento, autónomo o teleoperado, durante esta sesión.
- **Recuperación física de cable**: la lógica del watchdog de túnel se probó
  **offline** (`tests/Test-WatchdogLogic.ps1`, shim sin SSH real) — ver
  `WATCHDOG_LOGIC_OFFLINE_TESTED = true`. La recuperación real ante una
  desconexión física del cable Ethernet **no** se ejecutó en este checkpoint:
  `PHYSICAL_CABLE_RECOVERY_VALIDATED = false`.
- **Recorrido manual**: no se marcaron fases de recorrido ni se capturó una
  ruta; esta sesión fue estacionaria.
- **Demo concurrente de IA legacy**: no se ejecutó ningún componente de
  `docs/legacy/interaccionia/**` junto con esta herramienta.

## Alcance de "BMS validado"

`BMS accepted = true` significa que el probe (`companion/ottoguide_bms_probe.py`)
recibió 20/20 mensajes coherentes con las cotas físicas esperadas (SOC,
voltaje de pack, corriente, voltaje de celda, temperatura) y que
`relative_cell_sum_error = 0.001` (suma de celdas vs. voltaje de pack) es
consistente con la escala elegida. Esto es una validación de **coherencia de
schema y escala**, no una certificación de la salud de la batería.

## Alcance de "runtime read-only observado"

`dds_writers_created = 0` y `movement_clients_imported = 0` se verificaron por
dos vías independientes: análisis estático (AST/imports/calls,
`companion/static_gate.py`) y observación en runtime (inventario de proceso).
Esto demuestra que el código desplegado en esa sesión no creó writers DDS ni
importó clientes de movimiento — no es una prueba formal exhaustiva de que
ninguna versión futura del mismo archivo pueda hacerlo; el static gate debe
volver a ejecutarse en cada deployment (ya está integrado como paso
obligatorio en `notebook/Deploy-OttoGuideObservability.ps1`).

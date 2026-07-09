# otto_jsonl_shim — skeleton, no compilado, no ejecutado

## Propósito

`otto_jsonl_shim.cpp` y `otto_jsonl_protocol.hpp` son el skeleton de un proceso C++ nuevo y
separado que hablará el protocolo JSONL ya definido en
`codigo ottoguide/src/interaction/runtime_port.py`, permitiendo que el orquestador
Python/FastAPI supervise el pipeline de conversación física existente
(`otto_pipeline.cpp`) sin reimplementarlo en Python.

Diseño completo: `docs/Arquitectura/IA_CXX_R2_CXX_JSONL_SHIM_DESIGN.md`.

## Por qué existe

La decisión de arquitectura cerrada en IA-CXX-R1 (`CXX_PIPELINE_PRIMARY = true`,
`PYTHON_REIMPLEMENTATION_PRIMARY = false`) estableció que el pipeline C++ ya validado
físicamente en un Unitree G1 EDU es el runtime primario de conversación, y que Python actúa
únicamente como supervisor/control-plane. El shim es el mecanismo concreto para conectar
ambos lados sin tocar la lógica ya probada.

## Qué NO es este shim

- **No reemplaza `otto_pipeline.cpp`.** El pipeline original permanece intacto, sin
  modificar, con su hash forense (`0d1cc4567387f4bc41e3705d95c16d80be2e61d76fe2ea99dbe8a9fa6a926bcf`)
  estable en todos los checkpoints desde su importación.
- **No fue compilado.** Ningún comando `cmake`/`make`/`g++` se ejecutó sobre estos archivos.
- **No fue ejecutado.** Ningún binario resultante de estos archivos corrió en ningún momento.
- **No está integrado al build.** `CMakeLists.txt` no fue modificado; la integración al
  sistema de build queda para un checkpoint futuro de tipo "compile-only offline" (R4), en un
  entorno con el SDK disponible pero sin robot conectado.
- **No implementa lógica real todavía.** Todo handler de comando, lectura de stdin, y
  emisión de eventos está marcado `TODO` y no tiene efecto alguno más allá de un log a
  `stderr`.

## Estado en IA-CXX-R2

Este checkpoint (IA-CXX-R2) entrega únicamente diseño documental y skeleton de código no
funcional. Es la fase de diseño de un plan de rollout HIL-safe de varios pasos:

- **R2** (este checkpoint): diseño + skeleton, sin build, sin ejecución.
- **R2B–R2F**: revisión, staging a mirror, análisis, promoción canónica, verificación final
  — mismo patrón de gates ya usado en el ciclo IA-CXX-R1.
- **R3**: tests de protocolo contra un fake-worker, sin tocar Whisper/Ollama/Piper/Unitree.
- **R4**: compile-only offline, sin ejecución, en entorno con SDK disponible.
- **R5**: smoke test con binario dummy, sin robot.
- **R6**: validación HIL con robot real, exclusivamente bajo autorización explícita.

## Gates antes de cualquier build futuro

Antes de que un checkpoint futuro compile este skeleton por primera vez (R4), debe:

1. Confirmar que los strings de `otto_jsonl_protocol.hpp` (`CommandTypeToWire`,
   `EventTypeToWire`) coinciden byte a byte con los valores de `WorkerCommandType` y
   `WorkerEventType` en `runtime_port.py`.
2. Confirmar que ninguna dependencia de Whisper/Ollama/Piper/Unitree SDK fue introducida sin
   una decisión explícita de checkpoint.
3. Confirmar que `stdout` sigue siendo protocolo exclusivo y `stderr` exclusivo para logs.
4. Ejecutarse únicamente en un entorno explícitamente autorizado para build (nunca contra el
   robot físico sin autorización HIL separada).

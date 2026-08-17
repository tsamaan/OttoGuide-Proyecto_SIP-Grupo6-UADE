# IA-CXX-R5 — CXX runtime skeleton, compile-only offline

```
CXX_RUNTIME_LOCATION = codigo ottoguide/src/interaction/cxx_runtime
DOCS_RUNTIME_CODE = prohibited
CODIGO_OTTOGUIDE_RUNTIME_CODE = required
CXX_PIPELINE_PRIMARY = true
PYTHON_REIMPLEMENTATION_PRIMARY = false
R5_CXX_BUILD = true
R5_CXX_EXECUTION = false
R5_ROBOT_ACCESS = false
R5_OTTO_PIPELINE_CPP_MODIFIED = false
R5_LEGACY_DOCS_MODIFIED = false
NEXT_CHECKPOINT = IA-CXX-R5B_PRE_PUSH_REVIEW_CXX_RUNTIME_SKELETON_COMPILE_ONLY_NO_RUNTIME_NO_PUSH
```

## 1. Dictamen R5

Este checkpoint creó la primera estructura C++ productiva (compilable, no documental) del
runtime de interacción IA, bajo `codigo ottoguide/src/interaction/cxx_runtime/`, recreando el
contrato de protocolo diseñado en IA-CXX-R2 en la ubicación decidida por IA-CXX-R4. El código
compiló offline exitosamente (g++ 15.2.0, C++17, sin CMake disponible en este entorno — se usó
el fallback directo con g++ documentado en el propio prompt). Los binarios resultantes no
fueron ejecutados. No se tocó `otto_pipeline.cpp`, ningún archivo bajo `docs/legacy/**`, ni
ningún archivo Python existente.

## 2. Estado heredado R1-R4

- **R1**: decisión de arquitectura — `CXX_PIPELINE_PRIMARY = true`,
  `PYTHON_REIMPLEMENTATION_PRIMARY = false`. `InteractionRuntimePort`/
  `JsonlInteractionWorkerSupervisor` ya existentes del lado Python, sin contraparte C++ hasta
  este checkpoint.
- **R2**: diseñó el layout y skeleton no compilado del shim JSONL C++ bajo
  `docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/` (`otto_jsonl_protocol.hpp`,
  `otto_jsonl_shim.cpp`, `README_JSONL_SHIM.md`). Ese skeleton documental permanece intacto y
  sin modificar.
- **R3 (R3→R3F)**: estabilizó `JsonlInteractionWorkerSupervisor` (capa Python), sin tocar C++.
- **R4 (R4→R4E-FAST)**: planificó la ubicación productiva
  (`codigo ottoguide/src/interaction/cxx_runtime/`) y los gates de build/test/safety que este
  checkpoint (R5) debía satisfacer.
- `otto_pipeline.cpp` permanece sin modificar en todo el ciclo, hash forense estable
  (`0d1cc4567387f4bc41e3705d95c16d80be2e61d76fe2ea99dbe8a9fa6a926bcf`), confirmado antes y
  después de este checkpoint.

## 3. Archivos creados bajo `codigo ottoguide/`

```
codigo ottoguide/src/interaction/cxx_runtime/
├── README.md
├── CMakeLists.txt
├── include/
│   └── otto_jsonl_protocol.hpp
├── src/
│   └── otto_jsonl_shim.cpp
└── tests/
    └── protocol_contract_smoke.cpp
```

- `README.md`: explica qué es y qué NO es este skeleton (no runtime, no ejecutado en R5, no
  reemplazo de `otto_pipeline.cpp`, no integrado al build legacy), su relación con R2/R4, y
  cómo compilarlo offline.
- `CMakeLists.txt`: aislado, C++17, sin dependencias de Unitree/Whisper/Ollama/Piper, dos
  targets (`otto_jsonl_shim`, `otto_jsonl_protocol_smoke`), sin `install()`, sin comandos
  post-build.
- `include/otto_jsonl_protocol.hpp`: recreación real (no simple copia textual) del header
  diseñado en R2 — mismos enums `CommandType`/`EventType`, mismas funciones
  `CommandTypeToWire`/`EventTypeToWire`, mismos límites de payload, ahora bajo
  `codigo ottoguide/` y verificado por compilación real en vez de solo lectura.
- `src/otto_jsonl_shim.cpp`: `main()` dummy que solo imprime una línea de estado a `stderr` y
  retorna 0; incluye `static_assert`s que verifican en tiempo de compilación dos wire strings
  clave contra el header. Sin lectura de stdin, sin escritura de stdout JSONL, sin sockets,
  sin `system()`/`popen`/`fork`/`exec`, sin llamadas a Whisper/Ollama/Piper/Unitree.
- `tests/protocol_contract_smoke.cpp`: `static_assert` para las 8 wire strings de comando, las
  14 wire strings de evento, el protocol version, y la partición proceso/interacción completa;
  `main()` con asserts redundantes en runtime, compilado pero no ejecutado en este checkpoint.

## 4. Paridad de protocolo con `runtime_port.py`

Verificación byte a byte documentada en evidencia (`IA_CXX_R5_PROTOCOL_PARITY.txt` del run
local, no versionado): las 8 wire strings de `WorkerCommandType` y las 14 wire strings de
`WorkerEventType` en `runtime_port.py` coinciden exactamente con `CommandTypeToWire`/
`EventTypeToWire` en el header creado. `INTERACTION_PROTOCOL_VERSION = 1` coincide con
`kProtocolVersion = 1`.

**Nota de desviación documentada**: el prompt de origen de este checkpoint listaba en su
sección 4 un subconjunto ilustrativo mínimo de eventos que incluía `activated`, `completed` y
`health` como nombres de evento — ninguno de los cuales existe como wire string real en
`WorkerEventType` de `runtime_port.py`. Implementarlos tal cual habría introducido una
divergencia de protocolo no justificada, exactamente lo que el propio prompt exige bloquear en
su gate de paridad. En su lugar, se implementó el conjunto completo real de comandos y eventos
de `runtime_port.py` (igual que ya hacía el skeleton de R2), documentando esta decisión en la
evidencia del checkpoint.

## 5. Separación respecto de `docs/legacy/**`

Los archivos originales del skeleton R2
(`docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/otto_jsonl_protocol.hpp`,
`otto_jsonl_shim.cpp`, `README_JSONL_SHIM.md`) no fueron movidos, editados ni eliminados.
Permanecen como evidencia histórica del diseño R2, tal como exigía IA-CXX-R4 §8. El
`CMakeLists.txt` creado en este checkpoint no referencia ni incluye ningún archivo bajo
`docs/legacy/**`.

## 6. Separación respecto de `otto_pipeline.cpp`

`otto_jsonl_shim.cpp` no incluye, invoca, ni enlaza contra `otto_pipeline.cpp`. No hay
`#include` de ningún archivo bajo `docs/legacy/**` en ningún archivo creado en este
checkpoint. El hash forense de `otto_pipeline.cpp` fue verificado idéntico antes y después de
este checkpoint.

## 7. Build offline realizado

Herramienta usada: `g++ (GCC) 15.2.0`, vía el fallback directo documentado en el propio
prompt de origen (CMake no estaba disponible en este entorno de ejecución). Comandos:

```
g++ -std=c++17 -Wall -Wextra -Icodigo ottoguide/src/interaction/cxx_runtime/include \
    codigo ottoguide/src/interaction/cxx_runtime/src/otto_jsonl_shim.cpp \
    -o otto_jsonl_shim_dummy

g++ -std=c++17 -Wall -Wextra -Icodigo ottoguide/src/interaction/cxx_runtime/include \
    codigo ottoguide/src/interaction/cxx_runtime/tests/protocol_contract_smoke.cpp \
    -o protocol_contract_smoke
```

Ambas compilaciones terminaron con código de salida 0, sin warnings de `-Wall -Wextra`. Los
binarios se generaron en un directorio de evidencia fuera del repositorio y fueron eliminados
tras confirmar el éxito de la compilación, precisamente para no dejar artefactos ejecutables
persistentes de un checkpoint que prohíbe su ejecución.

## 8. Confirmación de no ejecución de binarios

Confirmado — ningún binario producido por `g++` fue ejecutado en ningún momento de este
checkpoint. Solo se verificó el código de salida del propio compilador (`g++`), no de los
binarios resultantes.

## 9. Confirmación de no robot

Confirmado — ninguna acción de robot, SSH, audio, micrófono, Whisper, Ollama, Piper, ni SDK
Unitree en ningún momento de este checkpoint.

## 10. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| El header recreado diverge silenciosamente del protocolo real | Verificación byte a byte documentada en evidencia + `static_assert` en el propio código, que falla la compilación ante divergencia |
| El `CMakeLists.txt` termina dependiendo accidentalmente del build legacy | Aislamiento verificado: ningún `include()`/`add_subdirectory()` referencia `docs/legacy/**`; grep de dependencias prohibidas ejecutado sobre los 5 archivos nuevos, 0 coincidencias en código real (solo menciones en comentarios que documentan su ausencia) |
| Un binario dummy se ejecuta por error en este o un checkpoint futuro que reutilice esta evidencia | Binarios compilados eliminados inmediatamente tras verificar el build; README.md y este documento declaran explícitamente que la ejecución requiere autorización separada (R6) |
| El subconjunto mínimo sugerido por el prompt de origen introduce wire strings inventados | Resuelto usando el conjunto completo real de `runtime_port.py`, documentado explícitamente como desviación justificada (§4) |

## 11. Checkpoints futuros

- **R5B**: pre-push review de este commit (sin runtime, sin push).
- **R5C**: staging al mirror únicamente, con confirmación explícita del usuario.
- **R5D**: análisis read-only del mirror antes de promoción canónica.
- **R5E**: promoción al canónico, con confirmación explícita del usuario.
- **R5F**: verificación final de alineación bit-a-bit canónico/mirror, cierre del ciclo R5.
- **R6**: smoke test con binario dummy — ejecución controlada sin robot, validando ciclo de
  vida del proceso (spawn, heartbeat, terminate, emergency_stop) sin dependencias reales de
  Whisper/Ollama/Piper/Unitree.
- **R7**: validación HIL con robot real, exclusivamente bajo autorización explícita y
  separada del resto del ciclo, con su propio prompt autocontenido y confirmación del usuario.

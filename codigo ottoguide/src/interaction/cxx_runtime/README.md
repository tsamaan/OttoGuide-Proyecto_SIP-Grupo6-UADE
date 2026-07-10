# cxx_runtime — productive C++ runtime skeleton (IA-CXX-R5)

Compile-only offline skeleton. Not the physical conversation runtime yet — no robot, no
audio, no models, no network.

## What this is

This directory is the first productive (compilable, real, non-documental) recreation of the
JSONL shim/protocol design from IA-CXX-R2, placed at the location decided in IA-CXX-R4:
`codigo ottoguide/src/interaction/cxx_runtime/`. It replaces the *design intent* previously
expressed only as a non-compiled skeleton under
`docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/otto_jsonl_protocol.hpp` /
`otto_jsonl_shim.cpp` with a real, buildable C++17 target — without deleting or moving those
original files, which remain in `docs/` as historical design evidence per IA-CXX-R4 §8.

## What this is NOT

- **Not a runtime.** `otto_jsonl_shim` does not read stdin, does not write JSONL to stdout,
  does not spawn any process, does not open sockets, does not touch audio hardware, and does
  not call Whisper, Ollama, Piper, or the Unitree SDK.
- **Not executed in IA-CXX-R5.** The binaries produced by this `CMakeLists.txt` (or by direct
  `g++` compilation, see below) are compiled offline as part of this checkpoint's build-gate
  verification, but are never run. Execution of a dummy binary is explicitly deferred to a
  future checkpoint (IA-CXX-R6, smoke test, no robot).
- **Not a replacement for `otto_pipeline.cpp`.** The historical, physically-validated pipeline
  at `docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/otto_pipeline.cpp` remains the
  only implementation of real audio capture/STT/LLM/TTS/playback. This skeleton does not
  invoke it, include it, or link against it.
- **Not integrated with the legacy build.** This `CMakeLists.txt` is self-contained and does
  not reference or modify `docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/CMakeLists.txt`.

## Relationship to R2 and R4

- **R2** (`docs/Arquitectura/IA_CXX_R2_CXX_JSONL_SHIM_DESIGN.md`) designed the protocol layout
  and a non-compiled skeleton under `docs/legacy/...`. This directory recreates that design as
  real, compilable code — the wire-string mapping in `include/otto_jsonl_protocol.hpp` is a
  byte-for-byte port of R2's header, not a redesign.
- **R4** (`docs/Arquitectura/IA_CXX_R4_CXX_RUNTIME_CODE_PLACEMENT_AND_BUILD_GATES.md`) defined
  this exact location (`codigo ottoguide/src/interaction/cxx_runtime/` with `include/`, `src/`,
  `tests/`, and an isolated `CMakeLists.txt`) and the build/test/safety gates this skeleton is
  built against.

## Building offline

Preferred (if CMake is available):

```
cmake -S codigo ottoguide/src/interaction/cxx_runtime -B <build_dir>
cmake --build <build_dir>
```

Fallback (direct `g++`, C++17, no CMake required):

```
g++ -std=c++17 -Icodigo ottoguide/src/interaction/cxx_runtime/include \
    codigo ottoguide/src/interaction/cxx_runtime/src/otto_jsonl_shim.cpp \
    -o otto_jsonl_shim_dummy

g++ -std=c++17 -Icodigo ottoguide/src/interaction/cxx_runtime/include \
    codigo ottoguide/src/interaction/cxx_runtime/tests/protocol_contract_smoke.cpp \
    -o protocol_contract_smoke
```

Do not execute the resulting binaries as part of any checkpoint that has not explicitly
authorized binary execution.

## Protocol parity

Wire strings in `include/otto_jsonl_protocol.hpp` (`CommandTypeToWire`, `EventTypeToWire`)
must match `WorkerCommandType`/`WorkerEventType` in
`codigo ottoguide/src/interaction/runtime_port.py` exactly. This parity is checked both
manually (documented in the IA-CXX-R5 evidence trail) and via `static_assert` in
`tests/protocol_contract_smoke.cpp`, which fails to *compile* if a wire string diverges.

## Gates before any future execution

Before a future checkpoint executes any binary built from this directory (even a dummy
smoke test), it must satisfy the safety gates defined in IA-CXX-R4 §11: fail-closed behavior
if real dependencies are missing, `emergency_stop` behavior validated offline first, and
explicit authorization separate from this build-only checkpoint. No such authorization is
granted by the existence of this directory or its `CMakeLists.txt`.

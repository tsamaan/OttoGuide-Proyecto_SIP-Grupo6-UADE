# InteraccionIA legacy archive

This directory preserves historical InteraccionIA material imported during the R4 consolidation track.

## Contents

- `Ottoguide_IA/**`: recovered historical IA pipeline snapshot.
- `Robot_G1-EDU_Conversational_Integration.md`: historical integration note.
- `documentacion_general_del_proyecto/Interaccion/**`: historical interaction planning documents.

## Runtime status

This material is archival/reference material only.

It is not wired into the current Python/FastAPI OttoGuide runtime.

Do not compile or execute the C++ pipeline from this archive unless a future explicit HIL-safe checkpoint authorizes it.

## Forensic integrity

The recovered C++ pipeline file:

`Ottoguide_IA/src/otto_audio/cpp/otto_pipeline.cpp`

must preserve SHA-256:

`0d1cc4567387f4bc41e3705d95c16d80be2e61d76fe2ea99dbe8a9fa6a926bcf`

## IA-CXX-R1 update

This material is still legacy/no-runtime as of this checkpoint. The recommended path
forward is a supervised adapter, C++-first: the Python orchestrator supervises a C++
worker process (this pipeline or a JSONL-speaking shim around it), it does not reimplement
STT/LLM/TTS/audio in Python. Do not compile or execute anything in this archive without an
explicit, future authorized checkpoint.

## IA-CXX-R2 update

`Ottoguide_IA/src/otto_audio/cpp/` now also contains `otto_jsonl_shim.cpp`,
`otto_jsonl_protocol.hpp`, and `README_JSONL_SHIM.md` — a skeleton for the JSONL shim
described in IA-CXX-R1/R2. These new files are not compiled and not executed.
`otto_pipeline.cpp` remains unmodified, with the SHA-256 above unchanged.

## Related documentation

See:

- `docs/Arquitectura/INTERACCIONIA_CONSOLIDATION_R2.md`
- `docs/Arquitectura/IA_CXX_R1_CXX_FIRST_ORCHESTRATOR_ADAPTER_DESIGN.md`
- `docs/Arquitectura/IA_CXX_R2_CXX_JSONL_SHIM_DESIGN.md`
- `Ottoguide_IA/src/otto_audio/cpp/README_JSONL_SHIM.md`

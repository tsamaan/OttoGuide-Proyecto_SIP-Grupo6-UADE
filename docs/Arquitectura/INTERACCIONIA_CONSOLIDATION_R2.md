# InteraccionIA consolidation R2

## Scope

This document records the selective, static consolidation of historical `InteraccionIA` material into `review/orchestrator-unification`.

## Imported as archive/reference

* `docs/legacy/interaccionia/Ottoguide_IA/**`
* `docs/legacy/interaccionia/Robot_G1-EDU_Conversational_Integration.md`
* `docs/legacy/interaccionia/documentacion_general_del_proyecto/Interaccion/**`

## Historical IA pipeline

Recovered C++ pipeline:

UDP robot audio -> Whisper local -> Ollama local -> Piper local -> Unitree AudioClient.PlayStream.

## Runtime status

This material is not wired into the current Python/FastAPI orchestrator runtime.

It is preserved as reference implementation, historical HIL evidence, and source for future adapter design.

## Safety

This consolidation did not:

* access the robot;
* use SSH;
* compile C++;
* execute C++;
* start ROS/DDS/Unitree SDK;
* start backend;
* start frontend;
* issue motion commands.

## Exclusions

Not imported:

* `codigo ottoguide/data/main_v2.py`;
* third-party library `.gitignore` changes;
* builds;
* binaries;
* caches;
* credentials;
* runtime artifacts.

## Pending work

* Decide if C++ IA remains archival or becomes a supervised worker.
* Define adapter boundary before connecting to the Python orchestrator.
* Validate only in a future explicit HIL-safe checkpoint.

## IA-CXX-R1 update

As of IA-CXX-R1, this C++ pipeline is no longer treated as archival-only reference. It is
the designated primary runtime candidate for physical conversation, under a supervised
Python control-plane / C++ runtime split. No runtime was wired or executed in IA-CXX-R1 —
the full design (protocol reuse, supervisor reuse, shim vs direct-modification decision,
risks, and the R2-R6 plan) is documented in
`docs/Arquitectura/IA_CXX_R1_CXX_FIRST_ORCHESTRATOR_ADAPTER_DESIGN.md`.

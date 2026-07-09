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

# OttoGuide

**Release status:** `FINAL_CLOSURE_CANDIDATE`

OttoGuide is a UADE university guide robot project for Unitree G1 EDU hardware. The repository contains the integrated software, offline contracts, operational tooling, and evidence needed to close the project truthfully. It is not yet a final release or a claim of current autonomous physical operation.

## Product Vision

The project explores a guide-robot experience for university visits: navigation and robot integration tooling, supervised local interaction, and an operator-auditable software architecture. The target hardware context is Unitree G1 EDU, but the repository does not claim that every physical subsystem is currently validated on a robot.

## Software Implemented

- Integrated robot/core runtime, tooling, configuration, and tests under `codigo ottoguide/`.
- Integrated web application/frontend under `ottoguide_web_app/`.
- Offline ODOM/TF P2C contracts with explicit evidence, readiness, and provenance boundaries.
- Supervised interaction architecture and offline test coverage represented by the current candidate tree.
- Versioned architecture, HIL operations, audit history, and unification handoff under `docs/`.

## Offline Validated

The current candidate contains versioned tests and offline validation for the contracts that they exercise. In particular, P2C establishes software and provenance boundaries for frame, covariance, claims, and readiness handling. Offline validation is not evidence of physical sensor publication, navigation execution, or robot autonomy.

## Physically Validated Historically

Historical sessions observed portions of the Unitree, sensor, and integration environment. That material is retained as historical physical validation in `docs/Operaciones_HIL/` and related records. It supports provenance only; it is not a current validation statement for this candidate tree.

## Not Validated

The following are not claimed as currently validated by this repository candidate:

- Physical `/odom` publication or physical TF publication.
- Nav2 autonomous navigation, current SLAM/map operation, or a complete physical tour.
- Current robot audio execution, camera reliability, or live DDS/ROS runtime behavior.
- A current hardware deployment matching this exact Git tree.

## Known Limitations

- P2C is an offline/software contract and does not elevate physical readiness.
- Historical physical observations must be revalidated in a separately authorized HIL checkpoint before they become current capability claims.
- Robot, ROS, DDS, Nav2, SLAM, audio, and movement actions remain separately safety-gated.
- The final main release has not been created or published yet.

## Repository Structure

```text
.
|- AGENTS.md                 # repository governance and safety rules
|- README.md                 # this public truth contract
|- TODO.md                   # deferred scope and validation limitations
|- codigo ottoguide/         # robot/core runtime, tooling, configuration, tests
|- ottoguide_web_app/        # integrated web application/frontend software root
`- docs/                     # sole documentation root
   |- Arquitectura/
   |- Operaciones_HIL/
   |- audits/
   `- planning/
```

`docs/` is the sole documentation root. `codigo ottoguide/` and `ottoguide_web_app/` are the established software roots; no additional software root may be introduced without explicit architectural review.

## Release Status

The active candidate follows a finite, auditable release sequence:

```text
candidate feature
-> independent GitHub audit
-> SEALED_FINAL_TREE
-> mirror review (same commit/tree)
-> canonical review (same commit/tree)
-> one root commit on main in mirror and canonical
```

`review/orchestrator-unification` retains development and integration history. The future `main` release is a separate final deliverable snapshot with exactly one root commit. The current release authority and publication contract are defined in [CIERRE_FINAL_MVP.md](docs/Arquitectura/CIERRE_FINAL_MVP.md). [UNIFICACION_RAMAS_Y_HANDOFF.md](docs/Arquitectura/UNIFICACION_RAMAS_Y_HANDOFF.md) and [unification-state.json](docs/Arquitectura/unification-state.json) remain durable provenance and historical decision records; older `NEXT_ACTION` or microcheckpoint fields inside them are not active release instructions.

# Pre-Push Review — 3da2e9a72ff573bc1a8a88ac23a2a5012e94b59d

- **Parent:** `0d14de65165805793b6c7c752780e0472507a388`
- **Author:** LucasCap12
- **Date:** 2026-07-14 17:20:48 -0300
- **Subject:** `fix(web): expose real interaction runtime state`
- **Files changed:** 3, +82/-5, 162 diff lines total

## Files

| Path | Change |
|---|---|
| `ottoguide_web_app/frontend/src/components/ControlPanel.jsx` | +25/-... |
| `ottoguide_web_app/frontend/src/services/statusAdapter.js` | +20 |
| `ottoguide_web_app/frontend/test/statusAdapter.test.js` | +42 (new tests) |

## Message summary

Frontend-only follow-up to `0d14de6`. Adds `interactionStartBlockReasons(uiStatus)` to `statusAdapter.js`: a pure function computing why the physical-interaction button should be disabled, returning an empty array only when all of the following hold — FSM state is `idle`, the interaction runtime is `configured` and `ready`, the runtime is **not** mock, the runtime reports `physical=true`, and there is no active session. The function explicitly never hides a block reason (all applicable reasons are collected, not just the first).

`ControlPanel.jsx` wires this helper into the button's enable/title state and surfaces the active session's id/state/last_event when present.

`statusAdapter.test.js` adds 4 new tests covering: the empty-reasons (enabled) path, the mock-always-blocks path, the multi-reason path (FSM not idle + not ready + not physical + session active, asserting all four reasons appear), and the not-configured single-reason path.

## Verification performed during this audit (offline, this session)

- **Read the full diff** (reproduced in relevant part above). `physical` and `ready` are read directly from `uiStatus.interactionRuntime` (i.e., from whatever the backend reports), not locally inferred or defaulted — consistent with the commit message's claim.
- **Locomotion/motion symbol scan** of the full diff: zero matches. This commit touches only frontend status-adapter and control-panel UI code; no C++, no DDS, no locomotion API surface.
- **No changes to the protected file** — this commit does not touch `docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/otto_pipeline.cpp` at all (confirmed by file list above and by the protected-file hash check in this session's Phase A, which was unaffected).
- The new tests are readable directly from the diff (not re-executed against a build in this specific per-commit audit step; full-suite execution is captured separately in this session's Phase C test baseline capture, see `TEST_BASELINE_RESULTS.json` under the run output directory).

## Physical evidence status

This commit is a pure frontend/UI change with no hardware interaction of its own. Its correctness depends on the backend (`0d14de6`'s worker and the existing runtime/session status endpoints) actually reporting `physical`/`ready`/session fields truthfully — that dependency is evidence-grounded in `0d14de6`'s audit and in the harvest capture, not re-derived here.

## Known gaps

See `MVP_IA_CXX_R1_KNOWN_GAPS.md`. This commit does not introduce new gaps of its own beyond what `0d14de6` already carries forward into the UI layer (e.g. if the backend's `ready`/`physical` signal is itself unreliable per a known gap, the UI will faithfully reflect that unreliability rather than compensate for it — which is the intended behavior per "never hides a block reason").

## Verdict contribution

Small, focused, frontend-only commit consistent with its stated purpose. No evidence found contradicting the commit message's description during this offline audit. See `PHYSICAL_COMMITS_VERDICT.md` for the combined verdict.

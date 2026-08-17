# WEB-R6 canonical UI, launcher and legacy removal report

## Scope

Static/config-only checkpoint. No runtime executed, no robot access, no push. This document
records the WEB-R6 changes that make `ottoguide_web_app/frontend` the only operational UI
and remove the legacy dashboard as a silent fallback.

## Canonical UI

`ottoguide_web_app/frontend` (React + Vite) is the only canonical operational UI for
OttoGuide. It is started with `npm run dev` (port 3001) and talks to the FastAPI backend
(port 8000) via the endpoints declared in `src/config.js`.

The backend FastAPI process is an API only. It is never the UI, including its root path.

## Legacy dashboard: no longer a silent fallback

Before WEB-R6, `GET /` and `GET /dashboard` served `static/dashboard.html` whenever
`WEB_UI_PUBLIC_URL` was empty, marked only by a response header
(`X-OttoGuide-Dashboard: legacy-fallback`). An operator opening the backend root without
noticing the header would see a working-looking dashboard and could mistake it for the
canonical UI — this is exactly what was observed in the WEB-R2D checkpoint when opening
`http://192.168.123.164:8000/`.

WEB-R6 changes this behavior in `codigo ottoguide/main.py` (`create_app()`):

* If `WEB_UI_PUBLIC_URL` is set: `/` and `/dashboard` redirect (HTTP 307) to that URL, as
  before.
* If `WEB_UI_PUBLIC_URL` is **not** set: `/` and `/dashboard` now return **HTTP 503** with an
  explicit body pointing the operator at `WEB_UI_PUBLIC_URL` and naming the canonical UI. No
  HTML page is silently rendered.
* `static/dashboard.html` is not deleted. It remains reachable only at the new
  `/dashboard-legacy` endpoint, explicitly named as deprecated, still carrying
  `X-OttoGuide-Dashboard: legacy-fallback` plus a new `X-OttoGuide-Deprecated: true` header.
  This endpoint exists for diagnostic/debug access only and must not be treated as an
  operational path.

## Ports and origins

| Component | Port | Notes |
|---|---|---|
| Backend FastAPI | 8000 | `API_PORT` in `codigo ottoguide/.env.example`; `vite.config.js` and frontend tests assume `:8000` as the default robot base URL. |
| Frontend Vite | 3001 | `server.port` / `preview.port` in `ottoguide_web_app/frontend/vite.config.js`, both with `strictPort: true`. |

`WEB_UI_ALLOWED_ORIGINS` (backend) is the single source of truth for both HTTP CORS and the
manual `Origin` check on `WS /ws/telemetry` (`config/settings.py`). It must include whatever
origin the Vite frontend is actually served from.

## Variables (documented, not executed)

### Backend (`codigo ottoguide/.env.example`)

Profiles documented as commented examples (active assignments remain empty/false by
design — see `@SECURITY` note in the file and the existing
`test_env_example_active_assignments_are_fail_closed_for_real_mode` test):

* **Perfil A — notebook local, sin robot** (`ROBOT_MODE=mock`):
  `WEB_UI_ALLOWED_ORIGINS=http://localhost:3001,http://127.0.0.1:3001`
  `WEB_UI_PUBLIC_URL=http://127.0.0.1:3001`
* **Perfil B — desarrollo local en red** (`ROBOT_MODE=mock/sim/demo`): same values as
  Perfil A; the backend already defaults to them when the variable is left empty in those
  modes (`web_ui_allowed_origins_list` in `config/settings.py`).
* **Perfil C — robot/companion PC real** (`ROBOT_MODE=real`, mandatory, fail-closed if
  empty or `*`): `WEB_UI_ALLOWED_ORIGINS=http://<NOTEBOOK_IP>:3001`,
  `WEB_UI_PUBLIC_URL=http://<NOTEBOOK_IP>:3001`, with a concrete lab example
  (`192.168.123.101:3001`) also documented.

### Frontend (`ottoguide_web_app/frontend/.env.example`)

* Active/default profile (robot/companion PC): `VITE_ROBOT_BASE_URL=http://192.168.123.164:8000`, `VITE_MOCK_MODE=true`.
* Documented alternative (notebook local, no robot): `VITE_ROBOT_BASE_URL=http://127.0.0.1:8000`, `VITE_MOCK_MODE=true` (commented, to be swapped in by the operator).

## Launchers (not executed)

Two new launcher scripts were added, mirroring the existing
`codigo ottoguide/scripts/start_backend_mock_py310.sh` pattern but explicit about Web UI
variables:

* `codigo ottoguide/scripts/start_web_backend_mock_py310.sh` — bash launcher; exports
  `ROBOT_MODE=mock`, `NAVIGATION_BACKEND=stub`, `API_PORT=8000`,
  `WEB_UI_ALLOWED_ORIGINS=http://localhost:3001,http://127.0.0.1:3001`,
  `WEB_UI_PUBLIC_URL=http://127.0.0.1:3001`, then execs the backend.
* `codigo ottoguide/scripts/start_web_backend_mock_py310.ps1` — Windows PowerShell
  equivalent; prepares the same environment variables but does **not** exec the backend
  process automatically — it prints the manual command the operator must run
  (`& $env:PYTHON_BIN main.py`), consistent with this checkpoint's no-runtime constraint.

Neither script was executed as part of this checkpoint.

## Operating without a terminal (future checkpoint)

This checkpoint documents configuration and launcher scaffolding only. A true
no-terminal operational flow (e.g., a desktop shortcut or a single supervising process that
starts backend + frontend together and opens the browser at `WEB_UI_PUBLIC_URL`) is left for
a future checkpoint, once these launchers are validated manually.

## Limitations

* No robot access, no SSH, no runtime execution (backend, frontend, or otherwise) took place
  in this checkpoint — all changes are static edits validated by inspection only.
* Real voice interaction remains pending Wake Word/TTS integration (Phase 2); the "Interaccion
  por voz" control in `ControlPanel.jsx` is unchanged by this checkpoint and continues to be
  mock-only / simulated.
* The C++ IA pipeline (`otto_pipeline.cpp`) was not touched, per this checkpoint's scope.
* `docs/Operaciones_HIL/WEB_UI_NOTEBOOK_COMPANION_RUNBOOK.md` was not modified — it is outside
  this checkpoint's explicit file allowlist and was left as-is.

## Next checkpoint

`WEB-R6B_PRE_PUSH_REVIEW_CANONICAL_UI_NO_RUNTIME_NO_PUSH` — static pre-push review of this
commit before any remote write is considered.

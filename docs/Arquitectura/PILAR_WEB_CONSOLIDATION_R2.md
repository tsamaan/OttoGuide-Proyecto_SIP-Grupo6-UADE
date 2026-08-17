# Pilar Web consolidation R2

## Branch status

`pilar-web` is a historical/diverged branch. Full merge is not recommended.

## Current canonical frontend

The canonical frontend is:

`ottoguide_web_app/frontend`

It runs with Vite on the notebook, usually:

`http://127.0.0.1:3001`

and consumes the robot backend at:

`http://192.168.123.164:8000`

## Legacy dashboard distinction

As of WEB-R6, `/` and `/dashboard` no longer serve the legacy static dashboard as a silent
operational fallback. When `WEB_UI_PUBLIC_URL` is configured they redirect (307) to the
React UI; when it is not configured they return HTTP 503 with an explicit message telling
the operator to configure `WEB_UI_PUBLIC_URL`. The legacy dashboard HTML remains reachable
only at `/dashboard-legacy`, an explicit, deprecated diagnostic endpoint — never the default
response of `/` or `/dashboard`.

That legacy dashboard must not be treated as the new PilarWeb React UI, and must not be
opened as if it were the operational UI.

## WEB-R2D observation (historical)

WEB-R2D showed the backend and UI could run live. It also showed that opening
`http://192.168.123.164:8000/` could display the legacy dashboard instead of redirecting to
React. WEB-R6 closes this gap: without `WEB_UI_PUBLIC_URL` configured, opening the backend
root now surfaces an explicit 503 instead of silently rendering the legacy dashboard.

## What was not imported

The old `pilar-web` frontend source was not restored over the canonical frontend because `review/orchestrator-unification` already contains the current React/Vite frontend.

The old Docker/backend assumptions from `pilar-web` are preserved only as historical context, not as current runtime instructions.

## Next web work

* Configure `WEB_UI_PUBLIC_URL` for UI sessions (see `docs/Arquitectura/WEB_R6_CANONICAL_UI_LAUNCHER_REPORT.md` for topology profiles).
* Ensure WebSocket origin allowlist (`WEB_UI_ALLOWED_ORIGINS`) includes the actual Vite origin.
* Never open the backend root (`:8000/`) as the UI; the canonical UI is always the Vite origin (`:3001`).
* Open `http://127.0.0.1:3001` (notebook local) or the notebook's network IP `:3001` (robot/companion PC topology) as the UI.
* Keep mutating controls disabled or unused during visual smoke tests.
* Treat `/dashboard-legacy` and `static/dashboard.html` as deprecated; do not add new operational dependencies on them.

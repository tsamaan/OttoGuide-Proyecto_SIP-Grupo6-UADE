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

The backend FastAPI can still serve a legacy static dashboard at `/` or `/dashboard`.

That legacy dashboard must not be treated as the new PilarWeb React UI.

## WEB-R2D observation

WEB-R2D showed the backend and UI could run live. It also showed that opening `http://192.168.123.164:8000/` may display the legacy dashboard.

## What was not imported

The old `pilar-web` frontend source was not restored over the canonical frontend because `review/orchestrator-unification` already contains the current React/Vite frontend.

The old Docker/backend assumptions from `pilar-web` are preserved only as historical context, not as current runtime instructions.

## Next web work

* Configure `WEB_UI_PUBLIC_URL` for UI sessions.
* Ensure WebSocket origin allowlist includes the actual Vite origin.
* Avoid opening backend root as the UI.
* Open `http://127.0.0.1:3001` as the UI.
* Keep mutating controls disabled or unused during visual smoke tests.

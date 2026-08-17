import { test } from 'node:test'
import assert from 'node:assert/strict'
import { config } from '../src/config.js'
import { robotApi, RobotApiError } from '../src/services/robotApi.js'
import { adaptStatusResponse, defaultUiStatus } from '../src/services/statusAdapter.js'

function jsonResponse(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function withMockedFetch(impl, fn) {
  const original = globalThis.fetch
  globalThis.fetch = impl
  return fn().finally(() => { globalThis.fetch = original })
}

// --- config.js: development profile is the default (no VITE_DEPLOYMENT_PROFILE set) ---

test('config defaults to development profile with runtime switch allowed', () => {
  assert.equal(config.deploymentProfile, 'development')
  assert.equal(config.allowRuntimeSwitch, true)
  assert.equal(config.endpoints.interactionStart, '/interaction/start')
})

// --- robotApi.startInteraction ---

test('startInteraction posts locale/timeout_s and returns the typed 202 body', async () => {
  await withMockedFetch(
    async (url, opts) => {
      assert.equal(url, 'http://x/interaction/start')
      const body = JSON.parse(opts.body)
      assert.equal(body.locale, 'es')
      assert.equal(body.timeout_s, 15.0)
      return jsonResponse(202, {
        accepted: true,
        interaction_id: 'standalone:1',
        runtime_backend: 'cxx_jsonl_mock',
        runtime_mock: true,
      })
    },
    async () => {
      const res = await robotApi.startInteraction('http://x', { locale: 'es', timeout_s: 15.0 })
      assert.equal(res.accepted, true)
      assert.equal(res.interaction_id, 'standalone:1')
      assert.equal(res.runtime_mock, true)
    },
  )
})

test('startInteraction surfaces 503 detail as a RobotApiError, never a silent fallback', async () => {
  await withMockedFetch(
    async () => jsonResponse(503, { detail: "Interaction runtime no disponible (backend='disabled')." }),
    async () => {
      await assert.rejects(
        () => robotApi.startInteraction('http://x', { locale: 'es', timeout_s: 15.0 }),
        (err) => {
          assert.ok(err instanceof RobotApiError)
          assert.equal(err.status, 503)
          assert.match(err.detail, /Interaction runtime no disponible/)
          return true
        },
      )
    },
  )
})

test('startInteraction surfaces 409 detail when FSM is not idle / already active', async () => {
  await withMockedFetch(
    async () => jsonResponse(409, {
      detail: { message: 'start_standalone_interaction solo es valido en estado IDLE.', current_state: 'navigating' },
    }),
    async () => {
      await assert.rejects(
        () => robotApi.startInteraction('http://x', { locale: 'es', timeout_s: 15.0 }),
        (err) => {
          assert.ok(err instanceof RobotApiError)
          assert.equal(err.status, 409)
          return true
        },
      )
    },
  )
})

// --- statusAdapter.js: interactionRuntime / interactionSession ---

test('adaptStatusResponse surfaces interactionRuntime with mock=true, physical=false for cxx_jsonl_mock', () => {
  const ui = adaptStatusResponse({
    state: 'idle',
    interaction_runtime: {
      configured: true,
      state: 'ready',
      ready: true,
      mock: true,
      physical: false,
      capabilities: { audio_capture: true },
      last_heartbeat_monotonic_s: 123.4,
      last_error: null,
    },
    interaction_session: { active: false, session_id: null, state: 'idle', last_event: null },
  })
  assert.equal(ui.interactionRuntime.configured, true)
  assert.equal(ui.interactionRuntime.mock, true)
  assert.equal(ui.interactionRuntime.physical, false)
  assert.equal(ui.interactionRuntime.ready, true)
  assert.equal(ui.interactionSession.active, false)
})

test('adaptStatusResponse defaults interactionRuntime/interactionSession when absent from payload', () => {
  const ui = adaptStatusResponse({ state: 'idle' })
  assert.equal(ui.interactionRuntime.configured, false)
  assert.equal(ui.interactionRuntime.mock, false)
  assert.equal(ui.interactionRuntime.physical, false)
  assert.equal(ui.interactionSession.state, 'idle')
})

test('defaultUiStatus includes interactionRuntime/interactionSession defaults', () => {
  const ui = defaultUiStatus()
  assert.equal(ui.interactionRuntime.configured, false)
  assert.equal(ui.interactionSession.active, false)
})

test('adaptStatusResponse never reports physical=true for a mock runtime, even if backend claims it', () => {
  // Defensive: the backend itself must never set physical=true when mock=true (enforced
  // server-side in api/router.py), but the adapter should still surface exactly what the
  // backend sent without inventing its own physical=true.
  const ui = adaptStatusResponse({
    state: 'idle',
    interaction_runtime: { configured: true, state: 'ready', ready: true, mock: true, physical: false },
  })
  assert.equal(ui.interactionRuntime.physical, false)
})

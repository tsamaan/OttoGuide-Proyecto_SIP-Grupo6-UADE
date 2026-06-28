import { test } from 'node:test'
import assert from 'node:assert/strict'
import { robotApi, RobotApiError } from '../src/services/robotApi.js'

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

test('stopAll on a safe stop returns httpStatus 200 with terminal_safe=true', async () => {
  await withMockedFetch(
    async (url, opts) => {
      assert.equal(url, 'http://x/emergency')
      assert.equal(JSON.parse(opts.body).reason, 'web_operator')
      return jsonResponse(200, {
        executed: true, terminal_safe: true, already_emergency: false,
        reason: 'web_operator', state: 'emergency',
        nav_cancel_succeeded: true, zero_velocity_succeeded: true, damp_succeeded: true,
        errors: [],
      })
    },
    async () => {
      const res = await robotApi.stopAll('http://x', 'web_operator')
      assert.equal(res.httpStatus, 200)
      assert.equal(res.terminal_safe, true)
    },
  )
})

test('stopAll on an unsafe stop returns httpStatus 503 with terminal_safe=false and errors', async () => {
  await withMockedFetch(
    async () => jsonResponse(503, {
      executed: true, terminal_safe: false, already_emergency: false,
      reason: 'web_operator', state: 'emergency',
      nav_cancel_succeeded: true, zero_velocity_succeeded: true, damp_succeeded: false,
      errors: ['damp_failed:RuntimeError:simulated'],
    }),
    async () => {
      const res = await robotApi.stopAll('http://x', 'web_operator')
      assert.equal(res.httpStatus, 503)
      assert.equal(res.terminal_safe, false)
      assert.ok(res.errors.includes('damp_failed:RuntimeError:simulated'))
    },
  )
})

test('stopAll on a 500 (uncontrolled exception) throws RobotApiError, not a typed response', async () => {
  await withMockedFetch(
    async () => jsonResponse(500, { detail: 'Error ejecutando emergency_stop: boom' }),
    async () => {
      await assert.rejects(
        () => robotApi.stopAll('http://x', 'web_operator'),
        (err) => {
          assert.ok(err instanceof RobotApiError)
          assert.equal(err.kind, 'server')
          assert.equal(err.detail, 'Error ejecutando emergency_stop: boom')
          return true
        },
      )
    },
  )
})

test('stopAll on a network failure throws a network-kind RobotApiError', async () => {
  await withMockedFetch(
    async () => { throw new TypeError('fetch failed') },
    async () => {
      await assert.rejects(
        () => robotApi.stopAll('http://x', 'web_operator'),
        (err) => { assert.ok(err instanceof RobotApiError); assert.equal(err.kind, 'network'); return true },
      )
    },
  )
})

test('startTour posts the StartTourRequest body and surfaces 422 detail on rejection', async () => {
  await withMockedFetch(
    async (url, opts) => {
      assert.equal(url, 'http://x/tour/start')
      const body = JSON.parse(opts.body)
      assert.ok(Array.isArray(body.waypoints))
      return jsonResponse(422, { detail: 'waypoints: ensure this value has at least 1 item' })
    },
    async () => {
      await assert.rejects(
        () => robotApi.startTour('http://x', { waypoints: [], tour_id: 't1' }),
        (err) => {
          assert.ok(err instanceof RobotApiError)
          assert.equal(err.status, 422)
          assert.equal(err.kind, 'client')
          assert.match(err.detail, /waypoints/)
          return true
        },
      )
    },
  )
})

test('getScript calls GET /content/script', async () => {
  await withMockedFetch(
    async (url, opts) => {
      assert.equal(url, 'http://x/content/script')
      assert.equal(opts.method, 'GET')
      return jsonResponse(200, { version: '1.0.0', waypoints: [] })
    },
    async () => {
      const script = await robotApi.getScript('http://x')
      assert.equal(script.version, '1.0.0')
    },
  )
})

test('no robotApi method ever calls /chat/start or a bare /telemetry path', () => {
  const src = Object.values(robotApi).map((fn) => fn.toString()).join('\n')
  assert.doesNotMatch(src, /chat\/start/)
  assert.doesNotMatch(src, /['"`]\/telemetry['"`]/)
})

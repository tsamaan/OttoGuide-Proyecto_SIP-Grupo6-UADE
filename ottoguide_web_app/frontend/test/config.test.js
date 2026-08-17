import { test } from 'node:test'
import assert from 'node:assert/strict'
import { config, wsUrl } from '../src/config.js'

test('wsUrl builds a ws:// URL pointed at /ws/telemetry, not /telemetry', () => {
  const url = wsUrl('http://192.168.123.164:8000')
  assert.equal(url, 'ws://192.168.123.164:8000/ws/telemetry')
})

test('wsUrl upgrades https to wss', () => {
  const url = wsUrl('https://example.com')
  assert.equal(url, 'wss://example.com/ws/telemetry')
})

test('wsUrl returns empty string for an invalid base URL', () => {
  assert.equal(wsUrl('not-a-url'), '')
})

test('config.endpoints has no chatStart and no bare GET /telemetry endpoint', () => {
  assert.equal('chatStart' in config.endpoints, false)
  assert.equal(config.endpoints.telemetryWs, '/ws/telemetry')
  assert.notEqual(config.endpoints.telemetryWs, '/telemetry')
  for (const value of Object.values(config.endpoints)) {
    assert.notEqual(value, '/telemetry')
    assert.notEqual(value, '/chat/start')
  }
})

test('config.endpoints includes the canonical script endpoint used to build /tour/start', () => {
  assert.equal(config.endpoints.script, '/content/script')
})

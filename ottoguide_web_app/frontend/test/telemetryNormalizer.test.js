import { test } from 'node:test'
import assert from 'node:assert/strict'
import { normalizeTelemetryFrame, defaultTelemetryFrame } from '../src/services/telemetryNormalizer.js'

test('normalizeTelemetryFrame maps the canonical build_telemetry_payload() shape', () => {
  const frame = normalizeTelemetryFrame({
    timestamp: '2026-06-28T05:00:00+00:00',
    fsm_state: 'NAVIGATING',
    current_waypoint_id: '1',
    battery_level: 87.5,
    nlp_intent: 'SCRIPTED',
    nlp_source_pipeline: 'LOCAL',
    nlp_answer_preview: 'Bienvenidos a...',
  })
  assert.deepEqual(frame, {
    timestamp: '2026-06-28T05:00:00+00:00',
    fsmState: 'NAVIGATING',
    currentWaypointId: '1',
    batteryLevel: 87.5,
    nlpIntent: 'SCRIPTED',
    nlpSourcePipeline: 'LOCAL',
    nlpAnswerPreview: 'Bienvenidos a...',
  })
})

test('normalizeTelemetryFrame defaults missing fields instead of throwing', () => {
  const frame = normalizeTelemetryFrame({})
  assert.equal(frame.fsmState, 'UNKNOWN')
  assert.equal(frame.batteryLevel, null)
})

test('normalizeTelemetryFrame handles null/non-object input', () => {
  assert.deepEqual(normalizeTelemetryFrame(null), defaultTelemetryFrame())
  assert.deepEqual(normalizeTelemetryFrame(undefined), defaultTelemetryFrame())
  assert.deepEqual(normalizeTelemetryFrame('not-an-object'), defaultTelemetryFrame())
})

test('normalizeTelemetryFrame rejects a non-numeric battery_level rather than passing it through', () => {
  const frame = normalizeTelemetryFrame({ battery_level: 'N/A' })
  assert.equal(frame.batteryLevel, null)
})

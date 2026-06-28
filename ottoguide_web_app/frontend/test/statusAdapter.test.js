import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  adaptStatusResponse,
  defaultUiStatus,
  tourStartBlockReasons,
  FSM_STATE_LABELS,
} from '../src/services/statusAdapter.js'

test('adaptStatusResponse maps FSM state to a Spanish label, never inventing llm_enabled', () => {
  const ui = adaptStatusResponse({
    state: 'navigating',
    tour_id: 't-1',
    current_waypoint_index: 2,
    operational_ready: true,
    readiness_errors: [],
    navigation_backend_requested: 'legacy',
    navigation_backend_resolved: 'legacy',
    navigation_started: true,
    script_loaded: true,
    script_version: '1.2.0',
    script_waypoint_count: 5,
    conversation_runtime_degraded: false,
    conversation_runtime_error: null,
  })
  assert.equal(ui.fsmState, 'navigating')
  assert.equal(ui.fsmStateLabel, 'recorrido')
  assert.equal(ui.tourId, 't-1')
  assert.equal(ui.currentWaypointIndex, 2)
  assert.equal(ui.operationalReady, true)
  assert.equal(ui.scriptVersion, '1.2.0')
  assert.equal('llm_enabled' in ui, false)
  assert.equal('llmEnabled' in ui, false)
})

test('FSM_STATE_LABELS covers all four canonical states', () => {
  assert.equal(FSM_STATE_LABELS.idle, 'reposo')
  assert.equal(FSM_STATE_LABELS.navigating, 'recorrido')
  assert.equal(FSM_STATE_LABELS.interacting, 'interaccion')
  assert.equal(FSM_STATE_LABELS.emergency, 'emergencia')
})

test('adaptStatusResponse falls back to defaults on null/invalid input', () => {
  assert.deepEqual(adaptStatusResponse(null), defaultUiStatus())
  assert.deepEqual(adaptStatusResponse(undefined), defaultUiStatus())
})

test('tourStartBlockReasons reports every blocking condition, never hides one', () => {
  const ui = adaptStatusResponse({
    state: 'idle',
    operational_ready: false,
    readiness_errors: ['navigation backend unavailable'],
    script_loaded: false,
    script_waypoint_count: 0,
  })
  const reasons = tourStartBlockReasons(ui, { apiReachable: false })
  assert.ok(reasons.includes('API no disponible'))
  assert.ok(reasons.includes('Sistema no operational_ready'))
  assert.ok(reasons.includes('Guion no cargado (script_loaded=false)'))
  assert.ok(reasons.includes('El guion no contiene waypoints'))
  assert.ok(reasons.includes('navigation backend unavailable'))
})

test('tourStartBlockReasons is empty when everything is ready', () => {
  const ui = adaptStatusResponse({
    state: 'idle',
    operational_ready: true,
    readiness_errors: [],
    script_loaded: true,
    script_waypoint_count: 3,
  })
  assert.deepEqual(tourStartBlockReasons(ui, { apiReachable: true }), [])
})

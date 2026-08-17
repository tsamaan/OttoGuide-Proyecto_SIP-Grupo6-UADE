import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  tourScriptToStartTourRequest,
  waypointContentToNavWaypoint,
  generateTourId,
  TourScriptValidationError,
} from '../src/services/tourMapper.js'

test('waypointContentToNavWaypoint maps pose_2d {x,y,theta} to {x,y,yaw_rad,frame_id}', () => {
  const dto = waypointContentToNavWaypoint({
    waypoint_id: 'I',
    pose_2d: { x: 1.5, y: -2.25, theta: 0.785 },
  })
  assert.deepEqual(dto, { x: 1.5, y: -2.25, yaw_rad: 0.785, frame_id: 'map' })
})

test('waypointContentToNavWaypoint rejects missing pose_2d', () => {
  assert.throws(
    () => waypointContentToNavWaypoint({ waypoint_id: 'I' }),
    TourScriptValidationError,
  )
})

test('tourScriptToStartTourRequest transforms a full script into a StartTourRequest body', () => {
  const script = {
    version: '1.0.0',
    waypoints: [
      { waypoint_id: 'I', pose_2d: { x: 0, y: 0, theta: 0 } },
      { waypoint_id: '1', pose_2d: { x: 1, y: 2, theta: 3.14 } },
    ],
  }
  const body = tourScriptToStartTourRequest(script, { tourId: 'fixed-id' })
  assert.deepEqual(body, {
    waypoints: [
      { x: 0, y: 0, yaw_rad: 0, frame_id: 'map' },
      { x: 1, y: 2, yaw_rad: 3.14, frame_id: 'map' },
    ],
    tour_id: 'fixed-id',
  })
})

test('tourScriptToStartTourRequest rejects a script with zero waypoints', () => {
  assert.throws(
    () => tourScriptToStartTourRequest({ version: '1.0.0', waypoints: [] }),
    TourScriptValidationError,
  )
})

test('tourScriptToStartTourRequest rejects a script with no waypoints field at all', () => {
  assert.throws(
    () => tourScriptToStartTourRequest({ version: '1.0.0' }),
    TourScriptValidationError,
  )
})

test('generateTourId produces unique-enough non-empty strings', () => {
  const a = generateTourId()
  const b = generateTourId()
  assert.ok(a.length > 0)
  assert.ok(b.length > 0)
  assert.notEqual(a, b)
})

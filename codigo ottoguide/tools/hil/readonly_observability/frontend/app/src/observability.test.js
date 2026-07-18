// NB-HIL-WEB-R0 pruebas puras (node:test, sin bundler ni DOM). Verifican las invariantes
// de seguridad del perfil y el contrato del normalizador. Se ejecutan con `npm run test`.
import test from 'node:test'
import assert from 'node:assert/strict'
import { resolveDeploymentConfig } from './config.js'
import { normalizeTelemetryFrame } from './services/telemetryNormalizer.js'
import { hasRichTelemetry, deriveChartsModel } from './components/chartsModel.js'
import { mergeAndOrder } from './services/backfillMerge.js'

const mk = (sid, seq, extra = {}) => ({ session_id: sid, seq, ...extra })

test('perfil real: nunca mock, sin switch en UI, read-only, badge REAL', () => {
  const c = resolveDeploymentConfig({
    VITE_DEPLOYMENT_PROFILE: 'real',
    VITE_MOCK_MODE: 'true',            // aunque el entorno pida mock...
    VITE_ALLOW_RUNTIME_SWITCH: 'true', // ...y pida permitir switch...
  })
  assert.equal(c.mockMode, false)          // ...el perfil real lo ignora
  assert.equal(c.allowRuntimeSwitch, false)
  assert.equal(c.demoReadOnly, true)
  assert.equal(c.isReal, true)
  assert.equal(c.profileLabel, 'REAL')
})

test('perfil replay: read-only, sin mock, badge REPLAY (no marca live)', () => {
  const c = resolveDeploymentConfig({ VITE_DEPLOYMENT_PROFILE: 'replay' })
  assert.equal(c.mockMode, false)
  assert.equal(c.allowRuntimeSwitch, false)
  assert.equal(c.isReplay, true)
  assert.equal(c.profileLabel, 'REPLAY')
  assert.equal(c.isReal, false)
})

test('normalizer: conserva identidad/procedencia y NO convierte null en 0', () => {
  const f = normalizeTelemetryFrame({
    seq: 42, session_id: 'sess-1', source_profile: 'REAL',
    server_utc: '2026-07-17T00:00:00Z', server_monotonic_ns: 123,
    availability: { imu: true, bms: false, energy: false },
    power_v: null, power_a: null, bms: null, foot_force: null,
    motors: [{ index: 0, name: 'X', group: 'G', q_deg: 1, temperature: 30 }],
  })
  assert.equal(f.seq, 42)
  assert.equal(f.sessionId, 'sess-1')
  assert.equal(f.sourceProfile, 'REAL')
  assert.equal(f.availability.bms, false)
  assert.equal(f.power_v, null) // nunca 0
  assert.equal(f.bms, null)
  assert.equal(f.motors.length, 1)
})

test('chartsModel: no hay telemetria rica sin muestras de motores', () => {
  assert.equal(hasRichTelemetry([]), false)
  assert.equal(hasRichTelemetry([{ motors: [] }]), false)
  assert.equal(hasRichTelemetry([{ motors: [{ name: 'X', group: 'G' }] }]), true)
  const m = deriveChartsModel([{ motors: [{ name: 'X', group: 'G' }] }])
  assert.equal(m.richTelemetryAvailable, true)
  assert.deepEqual(m.groups, ['G'])
})

// ---- FASE H: backfill ordenado ----
test('backfill 101-120 + live 121-123 durante el GET -> 101-123 ordenado, sin duplicados', () => {
  const backfill = []
  for (let s = 101; s <= 120; s++) backfill.push(mk('S1', s))
  const live = [mk('S1', 121), mk('S1', 122), mk('S1', 123)] // llegaron mientras el GET estaba en vuelo
  const { ordered } = mergeAndOrder({ backfill, live, seen: new Set() })
  const seqs = ordered.map((f) => f.seq)
  assert.deepEqual(seqs, Array.from({ length: 23 }, (_, i) => 101 + i))
  assert.equal(new Set(seqs).size, seqs.length) // sin duplicados
})

test('backfill/live solapados se deduplican por session_id+seq', () => {
  const backfill = [mk('S1', 118), mk('S1', 119), mk('S1', 120)]
  const live = [mk('S1', 119), mk('S1', 120), mk('S1', 121)] // 119,120 duplicados
  const { ordered } = mergeAndOrder({ backfill, live, seen: new Set() })
  assert.deepEqual(ordered.map((f) => f.seq), [118, 119, 120, 121])
})

test('respeta el set seen y ordena aun con entrada desordenada', () => {
  const seen = new Set(['S1#100'])
  const backfill = [mk('S1', 103), mk('S1', 100), mk('S1', 101)] // 100 ya visto, desordenado
  const live = [mk('S1', 102)]
  const { ordered, seen: ns } = mergeAndOrder({ backfill, live, seen })
  assert.deepEqual(ordered.map((f) => f.seq), [101, 102, 103])
  assert.ok(ns.has('S1#103'))
})

import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  sampleMotors, hasRichTelemetry, deriveChartsModel, buildRows,
} from '../src/components/chartsModel.js'
import { resolveDeploymentConfig } from '../src/config.js'
import { adaptStatusResponse, tourStartBlockReasons } from '../src/services/statusAdapter.js'
import ErrorBoundary from '../src/components/ErrorBoundary.js'

// Helper: adapta un interaction_session crudo usando el adaptador de status exportado.
const interactionStateOf = (rawSession) =>
  adaptStatusResponse({ interaction_session: rawSession }).interactionSession
import {
  canonicalTelemetryHistory, canonicalBackendStatus, mockRichHistory,
} from './fixtures/canonicalTelemetry.js'

// Regresion WEB-UI-R0: el contrato canonico del backend real no incluye `motors`; antes del
// fix, ChartsGrid hacia `history.at(-1).motors.map(...)` y lanzaba TypeError, derribando el
// arbol React entero en perfil real.

// #1 — frame canonico sin motors no produce excepcion
test('#1 deriveChartsModel sobre frame canonico sin motors no lanza', () => {
  assert.doesNotThrow(() => deriveChartsModel([canonicalTelemetryHistory.at(-1)]))
  const model = deriveChartsModel([canonicalTelemetryHistory.at(-1)])
  assert.deepEqual(model.motors, [])
  assert.deepEqual(model.groups, [])
})

// #2 — history canonico completo sin motors no produce excepcion (incl. buildRows)
test('#2 deriveChartsModel + buildRows sobre history canonico no lanza', () => {
  assert.doesNotThrow(() => {
    const { safeHistory } = deriveChartsModel(canonicalTelemetryHistory)
    buildRows(safeHistory, (f, row) => {
      sampleMotors(f).forEach((m) => { row[m.name] = m.temperature })
    })
  })
})

// #3 — con frames canonicos el panel debe declarar telemetria rica NO disponible
test('#3 richTelemetryAvailable=false para frames canonicos', () => {
  const model = deriveChartsModel(canonicalTelemetryHistory)
  assert.equal(model.richTelemetryAvailable, false)
  assert.equal(hasRichTelemetry(canonicalTelemetryHistory), false)
})

// #4 — datos mock con motores siguen produciendo grupos/series (graficos disponibles)
test('#4 datos mock con motores: richTelemetryAvailable=true y grupos derivados', () => {
  const model = deriveChartsModel(mockRichHistory)
  assert.equal(model.richTelemetryAvailable, true)
  assert.deepEqual(model.groups, ['left_leg', 'right_leg'])
  const rows = buildRows(model.safeHistory, (f, row) => {
    sampleMotors(f).forEach((m) => { row[m.name] = m.q_deg })
  })
  assert.equal(rows.length, mockRichHistory.length)
})

// #5 — un array motors vacio es valido (no rico, sin excepcion)
test('#5 motors:[] es valido y no rico', () => {
  const model = deriveChartsModel([{ timestamp: 1, motors: [] }])
  assert.deepEqual(model.motors, [])
  assert.equal(model.richTelemetryAvailable, false)
  assert.equal(sampleMotors({ motors: [] }).length, 0)
})

// #6 — bms ausente es valido
test('#6 bms ausente no lanza en buildRows (soc/cell_vol)', () => {
  assert.doesNotThrow(() => {
    buildRows(canonicalTelemetryHistory, (f, row) => {
      row.SOC = f.bms?.soc ?? null;
      (f.bms?.cell_vol || []).forEach((mv, i) => { row[`c${i}`] = mv })
    })
  })
})

// #7 — power_v/power_a ausentes son validos
test('#7 power_v/power_a ausentes no lanzan', () => {
  assert.doesNotThrow(() => {
    buildRows(canonicalTelemetryHistory, (f, row) => { row.A = f.power_a; row.V = f.power_v })
  })
  const rows = buildRows(canonicalTelemetryHistory, (f, row) => { row.A = f.power_a })
  assert.equal(rows[0].A, undefined)
})

// #8 — WebSocket active -> completed actualiza la interaccion
test('#8 interaction_session transiciona active -> completed en los frames reales', () => {
  const states = canonicalTelemetryHistory
    .map((f) => interactionStateOf(f.interaction_session).state)
  assert.ok(states.includes('active'), 'debe existir un frame active')
  assert.ok(states.includes('completed'), 'debe existir un frame completed')
  assert.equal(states.indexOf('active') < states.lastIndexOf('completed'), true)
  const last = interactionStateOf(canonicalTelemetryHistory.at(-1).interaction_session)
  assert.equal(last.state, 'completed')
  assert.equal(last.lastEvent, 'playback_completed')
})

// #9 — perfil real nunca activa mock ni permite alternar (regla de seguridad)
test('#9 perfil real: mockMode=false y allowRuntimeSwitch=false', () => {
  const real = resolveDeploymentConfig({ VITE_DEPLOYMENT_PROFILE: 'real', VITE_MOCK_MODE: 'true', VITE_ALLOW_RUNTIME_SWITCH: 'true' })
  assert.equal(real.deploymentProfile, 'real')
  assert.equal(real.mockMode, false)
  assert.equal(real.allowRuntimeSwitch, false)
  // development conserva el toggle
  const dev = resolveDeploymentConfig({ VITE_DEPLOYMENT_PROFILE: 'development' })
  assert.equal(dev.deploymentProfile, 'development')
  assert.equal(dev.allowRuntimeSwitch, true)
})

// #10 — /tour/start permanece bloqueado con el status real (status-only)
test('#10 tour bloqueado: status real produce motivos de bloqueo no vacios', () => {
  const ui = adaptStatusResponse(canonicalBackendStatus)
  const reasons = tourStartBlockReasons(ui, { apiReachable: true })
  assert.ok(reasons.length > 0, 'el tour debe estar bloqueado')
  assert.ok(reasons.some((r) => /operational_ready|navigation disabled/i.test(r)))
  assert.equal(ui.navigationStarted, false)
  assert.equal(ui.interactionRuntime.mock, true)
  assert.equal(ui.interactionRuntime.physical, false)
})

// #11 — un error de panel no borra el resto de la UI (contrato del ErrorBoundary)
test('#11 ErrorBoundary atrapa el fallo y expone estado de error (fallback local)', () => {
  const next = ErrorBoundary.getDerivedStateFromError(new Error('boom'))
  assert.equal(next.hasError, true)
  assert.equal(next.message, 'boom')
  // Instancia: en estado de error renderiza fallback en vez de children.
  const inst = new ErrorBoundary({ label: 'Graficos', children: 'contenido-original' })
  inst.state = { hasError: false, message: '' }
  assert.equal(inst.render(), 'contenido-original')
  inst.state = { hasError: true, message: 'boom' }
  const fallback = inst.render()
  assert.notEqual(fallback, 'contenido-original')
  assert.equal(typeof fallback, 'object') // elemento React de fallback, no los children
})

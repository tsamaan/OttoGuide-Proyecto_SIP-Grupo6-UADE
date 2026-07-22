// Configuracion central del front. Lo unico que hay que tocar para apuntar al robot.
// import.meta.env solo existe bajo Vite; con `node --test` (sin bundler) cae a {} para
// que este modulo siga siendo importable por los tests puros de node:test.
const env = (typeof import.meta !== 'undefined' && import.meta.env) || {}

// NB-HIL-WEB-R0: dos perfiles operativos, ambos read-only, sin mock y sin toggle en la UI.
//   real   -> bridge fisico del Companion a traves del tunel SSH (source_profile=REAL)
//   replay -> reproduccion offline de frames fisicos grabados (source_profile=REPLAY)
// deploymentProfile "development" queda solo como fallback interno para tests; ni real ni
// replay permiten alternar a mock ni editar la URL desde la interfaz.
export function resolveDeploymentConfig(rawEnv) {
  const e = rawEnv || {}
  const raw = e.VITE_DEPLOYMENT_PROFILE
  const deploymentProfile = raw === 'real' ? 'real' : raw === 'replay' ? 'replay' : 'development'
  const isReal = deploymentProfile === 'real'
  const isReplay = deploymentProfile === 'replay'
  const locked = isReal || isReplay // perfiles operativos: sin autoridad de switch en UI
  return {
    deploymentProfile,
    // En real/replay el operador nunca alterna mock/real desde la UI.
    allowRuntimeSwitch: locked ? false : (e.VITE_ALLOW_RUNTIME_SWITCH ?? 'true') !== 'false',
    // URL del bridge (real: tunel 127.0.0.1:8000 ; replay: replay server local 127.0.0.1:8000).
    robotBaseUrl: e.VITE_ROBOT_BASE_URL || 'http://127.0.0.1:8000',
    // real/replay ignoran cualquier localStorage de mock previo: mockMode siempre false.
    mockMode: locked ? false : (e.VITE_MOCK_MODE ?? 'true') !== 'false',
    // Demo de solo lectura: sin autoridad de movimiento. Real/replay siempre read-only.
    demoReadOnly: locked ? true : (e.VITE_DEMO_READ_ONLY ?? 'false') === 'true',
    isReal,
    isReplay,
    // Etiqueta de badge que ve el operador: nunca marca replay como live.
    profileLabel: isReal ? 'REAL' : isReplay ? 'REPLAY' : 'DEVELOPMENT',
  }
}

const _flags = resolveDeploymentConfig(env)

export const config = {
  deploymentProfile: _flags.deploymentProfile,
  allowRuntimeSwitch: _flags.allowRuntimeSwitch,
  robotBaseUrl: _flags.robotBaseUrl,
  mockMode: _flags.mockMode,
  demoReadOnly: _flags.demoReadOnly,
  isReal: _flags.isReal,
  isReplay: _flags.isReplay,
  profileLabel: _flags.profileLabel,

  // Endpoints del bridge read-only (ottoguide_readonly_bridge.py).
  endpoints: {
    script: '/content/script',
    status: '/status',
    health: '/health',
    backfill: '/telemetry/backfill',
    telemetryWs: '/ws/telemetry',
  },

  // Timeout de requests HTTP via AbortController.
  requestTimeoutMs: 5000,

  // Frecuencias de actualizacion.
  dataHz: 10, // muestras por segundo (tarjetas y tabla)
  chartRefreshMs: 200, // refresco de los graficos
  historySeconds: 30, // ventana de tiempo de los graficos

  // C6: reconexion WebSocket con backoff 0.5s -> 1s -> 2s (tope 2s) y backfill.
  wsBackoffMs: [500, 1000, 2000],
  wsBackoffMaxMs: 2000,
  backfillLimit: 1800,
}

// Deriva la URL de WebSocket de telemetria a partir de la URL HTTP del backend.
export function wsUrl(baseUrl) {
  try {
    const u = new URL(baseUrl)
    const proto = u.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${u.host}${config.endpoints.telemetryWs}`
  } catch {
    return ''
  }
}

export const HISTORY_SAMPLES = config.dataHz * config.historySeconds

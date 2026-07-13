// Configuracion central del front. Lo unico que hay que tocar para apuntar al robot.
// import.meta.env solo existe bajo Vite; con `node --test` (sin bundler) cae a {} para
// que este modulo siga siendo importable por los tests puros de node:test.
const env = (typeof import.meta !== 'undefined' && import.meta.env) || {}

// deploymentProfile: "development" (default, permite mock toggle) | "real" (ignora
// localStorage de mock previo, bloquea el toggle, nunca reemplaza silenciosamente la URL).
const deploymentProfile = env.VITE_DEPLOYMENT_PROFILE === 'real' ? 'real' : 'development'
const isRealProfile = deploymentProfile === 'real'

export const config = {
  deploymentProfile,
  // En perfil real el operador nunca puede alternar mock/real desde la UI, sin importar
  // VITE_ALLOW_RUNTIME_SWITCH; en development, default true salvo que se deshabilite.
  allowRuntimeSwitch: isRealProfile ? false : (env.VITE_ALLOW_RUNTIME_SWITCH ?? 'true') !== 'false',

  // URL del backend en el robot (companion PC, FastAPI canonico). Editable tambien desde la UI
  // solo en perfil development; en perfil real la URL configurada nunca se reemplaza silenciosamente.
  robotBaseUrl: env.VITE_ROBOT_BASE_URL || 'http://192.168.123.164:8000',
  // Perfil real ignora cualquier localStorage de mock previo: mockMode siempre false ahi.
  mockMode: isRealProfile ? false : (env.VITE_MOCK_MODE ?? 'true') !== 'false',

  // Endpoints del backend canonico (api/router.py). Si cambian las rutas, se ajustan aca.
  endpoints: {
    script: '/content/script',
    tourStart: '/tour/start',
    stop: '/emergency',
    status: '/status',
    interactionStart: '/interaction/start',
    telemetryWs: '/ws/telemetry', // WebSocket; no existe GET /telemetry de fallback
  },

  // Timeout de requests HTTP via AbortController.
  requestTimeoutMs: 5000,

  // Frecuencias de actualizacion.
  dataHz: 10, // muestras por segundo (tarjetas y tabla)
  chartRefreshMs: 200, // refresco de los graficos (mas lento = mas fluido con muchas curvas)
  historySeconds: 30, // ventana de tiempo de los graficos
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

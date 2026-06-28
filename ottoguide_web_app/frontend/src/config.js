// Configuracion central del front. Lo unico que hay que tocar para apuntar al robot.
// import.meta.env solo existe bajo Vite; con `node --test` (sin bundler) cae a {} para
// que este modulo siga siendo importable por los tests puros de node:test.
const env = (typeof import.meta !== 'undefined' && import.meta.env) || {}

export const config = {
  // URL del backend en el robot (companion PC, FastAPI canonico). Editable tambien desde la UI.
  robotBaseUrl: env.VITE_ROBOT_BASE_URL || 'http://192.168.123.164:8000',
  // Arranca en modo simulacion (sin robot). Toggle en la UI.
  mockMode: (env.VITE_MOCK_MODE ?? 'true') !== 'false',

  // Endpoints del backend canonico (api/router.py). Si cambian las rutas, se ajustan aca.
  // No existe /chat/start en el backend canonico: la interaccion por voz queda pendiente
  // de Wake Word/TTS (Fase 2) y solo se simula en mock mode.
  endpoints: {
    script: '/content/script',
    tourStart: '/tour/start',
    stop: '/emergency',
    status: '/status',
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

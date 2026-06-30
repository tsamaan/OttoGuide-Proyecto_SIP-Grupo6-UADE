// Configuracion central del front. Lo unico que hay que tocar para apuntar al robot.
const env = import.meta.env

export const config = {
  // URL del backend en el robot (puerto 8000). Editable tambien desde la UI.
  robotBaseUrl: env.VITE_ROBOT_BASE_URL || 'http://192.168.123.164:8000',
  // Arranca en modo simulacion (sin robot). Toggle en la UI.
  mockMode: (env.VITE_MOCK_MODE ?? 'true') !== 'false',

  // Endpoints del backend. Si en el robot cambian las rutas, se ajustan aca.
  endpoints: {
    tourStart: '/tour/start',
    tourPause: '/tour/pause',
    script: '/content/script',
    scriptReload: '/content/script/reload',
    stop: '/emergency',
    status: '/status',
    telemetry: '/ws/telemetry', // sirve para WS (ws://.../ws/telemetry)
  },

  // Frecuencias de actualizacion.
  dataHz: 10, // muestras por segundo (tarjetas y tabla)
  chartRefreshMs: 200, // refresco de los graficos (mas lento = mas fluido con muchas curvas)
  historySeconds: 30, // ventana de tiempo de los graficos
}

// Deriva la URL de WebSocket a partir de la URL HTTP del backend.
export function wsUrl(baseUrl) {
  try {
    const u = new URL(baseUrl)
    const proto = u.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${u.host}${config.endpoints.telemetry}`
  } catch {
    return ''
  }
}

export const HISTORY_SAMPLES = config.dataHz * config.historySeconds

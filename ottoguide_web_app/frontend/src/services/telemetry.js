// Conexion de telemetria con el backend canonico. Intenta WebSocket (/ws/telemetry);
// si falla, cae a polling de GET /status (no existe GET /telemetry en el backend canonico —
// ese endpoint roto del backend especulativo de pilar-web fue eliminado de este cliente).
import { config, wsUrl } from '../config.js'
import { normalizeTelemetryFrame } from './telemetryNormalizer.js'

// GET /status no tiene el mismo shape que un frame de telemetria; se sintetiza un frame
// minimo compatible para que el normalizador y la UI no necesiten dos caminos distintos.
function statusResponseToTelemetryFrame(statusResponse) {
  return {
    timestamp: new Date().toISOString(),
    fsm_state: (statusResponse?.state ?? 'unknown').toUpperCase(),
    current_waypoint_id: statusResponse?.current_waypoint_index != null
      ? String(statusResponse.current_waypoint_index)
      : 'N/A',
    battery_level: null,
    nlp_intent: 'UNKNOWN',
    nlp_source_pipeline: 'N/A',
    nlp_answer_preview: '',
  }
}

export function connectTelemetry(baseUrl, { onFrame, onState }) {
  let ws = null
  let pollTimer = null
  let retryTimer = null
  let closed = false

  const setState = (s) => onState && onState(s)
  const emitFrame = (rawFrame) => onFrame(normalizeTelemetryFrame(rawFrame))

  function startPolling() {
    setState('polling')
    const tick = async () => {
      try {
        const res = await fetch(`${baseUrl}${config.endpoints.status}`)
        if (res.ok) {
          emitFrame(statusResponseToTelemetryFrame(await res.json()))
          setState('polling')
        } else {
          setState('error')
        }
      } catch {
        setState('error')
      }
    }
    tick()
    pollTimer = setInterval(tick, Math.round(1000 / config.dataHz))
  }

  function startWs() {
    const url = wsUrl(baseUrl)
    if (!url) {
      startPolling()
      return
    }
    try {
      ws = new WebSocket(url)
    } catch {
      startPolling()
      return
    }
    setState('connecting')
    ws.onopen = () => setState('connected')
    ws.onmessage = (ev) => {
      try {
        emitFrame(JSON.parse(ev.data))
      } catch {
        /* frame invalido, lo ignoramos */
      }
    }
    ws.onerror = () => {
      // si el WS no levanta, probamos polling de /status
      if (ws) { try { ws.close() } catch {} }
    }
    ws.onclose = () => {
      ws = null
      if (closed) return
      // fallback: polling de /status + reintento de WS mas adelante
      if (!pollTimer) startPolling()
      setState('reconnecting')
      retryTimer = setTimeout(() => {
        if (closed) return
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
        startWs()
      }, 4000)
    }
  }

  startWs()

  // Devuelve la funcion para cortar todo limpio.
  return function disconnect() {
    closed = true
    if (ws) { try { ws.close() } catch {} ws = null }
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
    if (retryTimer) { clearTimeout(retryTimer); retryTimer = null }
  }
}

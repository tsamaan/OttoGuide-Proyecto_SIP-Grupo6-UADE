// Conexion de telemetria con el backend del robot.
// Intenta WebSocket; si falla, reporta error y reintenta. No hay fallback HTTP por requerimiento de seguridad.
import { wsUrl } from '../config.js'

export function connectTelemetry(baseUrl, { onFrame, onState }) {
  let ws = null
  let retryTimer = null
  let closed = false

  const setState = (s) => onState && onState(s)

  function startWs() {
    const url = wsUrl(baseUrl)
    if (!url) {
      setState('error')
      return
    }
    try {
      ws = new WebSocket(url)
    } catch {
      setState('error')
      return
    }
    setState('connecting')
    ws.onopen = () => setState('connected')
    ws.onmessage = (ev) => {
      try {
        onFrame(JSON.parse(ev.data))
      } catch {
        /* frame invalido, lo ignoramos */
      }
    }
    ws.onerror = () => {
      // si el WS no levanta, cerramos para forzar onclose
      if (ws) { try { ws.close() } catch {} }
    }
    ws.onclose = () => {
      ws = null
      if (closed) return
      setState('error')
      retryTimer = setTimeout(() => {
        if (closed) return
        startWs()
      }, 4000)
    }
  }

  startWs()

  // Devuelve la funcion para cortar todo limpio.
  return function disconnect() {
    closed = true
    if (ws) { try { ws.close() } catch {} ws = null }
    if (retryTimer) { clearTimeout(retryTimer); retryTimer = null }
  }
}

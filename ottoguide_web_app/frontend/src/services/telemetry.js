// Conexion de telemetria con el backend del robot.
// Intenta WebSocket; si falla, cae a polling por GET. Reintenta solo.
import { config, wsUrl } from '../config.js'

export function connectTelemetry(baseUrl, { onFrame, onState }) {
  let ws = null
  let pollTimer = null
  let retryTimer = null
  let closed = false

  const setState = (s) => onState && onState(s)

  function startPolling() {
    setState('polling')
    const tick = async () => {
      try {
        const res = await fetch(`${baseUrl}${config.endpoints.telemetry}`)
        if (res.ok) {
          onFrame(await res.json())
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
        onFrame(JSON.parse(ev.data))
      } catch {
        /* frame invalido, lo ignoramos */
      }
    }
    ws.onerror = () => {
      // si el WS no levanta, probamos polling
      if (ws) { try { ws.close() } catch {} }
    }
    ws.onclose = () => {
      ws = null
      if (closed) return
      // fallback: polling + reintento de WS mas adelante
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

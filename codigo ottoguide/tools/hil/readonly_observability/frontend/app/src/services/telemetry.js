// NB-HIL-WEB-R0A conexion de telemetria read-only con el bridge fisico (o el replay server).
// Solo WebSocket (/ws/telemetry). No hay POST/PUT/PATCH/DELETE: el bridge los responde 405.
//
// Resiliencia de enlace (C6 + FASE H):
//   * conserva session_id y last_seq entre reconexiones;
//   * reintenta el WebSocket con backoff 0.5s -> 1s -> 2s (tope 2s);
//   * al (re)conectar BUFFERIZA los frames live mientras el GET /telemetry/backfill esta en
//     vuelo, luego combina backfill+live, deduplica por session_id+seq, ORDENA por seq y
//     emite; despues continua el stream live;
//   * ante cambio de session_id: cierra la secuencia previa, limpia el dedupe y arranca nueva;
//   * marca cada frame con su tiempo real de recepcion (_recvMs) para la edad real del frame WS.
import { config, wsUrl } from '../config.js'
import { normalizeTelemetryFrame } from './telemetryNormalizer.js'
import { mergeAndOrder, frameKey } from './backfillMerge.js'

export function connectTelemetry(baseUrl, { onFrame, onState }) {
  let ws = null
  let retryTimer = null
  let closed = false
  let attempt = 0
  let sessionId = null
  let lastSeq = null
  let seen = new Set()
  const seenOrder = []
  const SEEN_MAX = 4000

  // Buffer de live mientras el backfill esta en vuelo (FASE H).
  let buffering = false
  let liveBuffer = []

  const setState = (s) => onState && onState(s)

  function trackSeen(key) {
    if (!key) return
    if (!seen.has(key)) { seen.add(key); seenOrder.push(key) }
    if (seenOrder.length > SEEN_MAX) {
      const old = seenOrder.splice(0, seenOrder.length - SEEN_MAX)
      old.forEach((k) => seen.delete(k))
    }
  }

  function noteSession(rawFrame) {
    const sid = rawFrame.session_id ?? rawFrame.sessionId ?? null
    if (sid != null && sessionId !== null && sid !== sessionId) {
      // Cambio de sesion: cerrar secuencia previa, limpiar dedupe, iniciar nueva.
      seen = new Set()
      seenOrder.length = 0
      lastSeq = null
    }
    if (sid != null) sessionId = sid
    const seq = rawFrame.seq ?? null
    if (typeof seq === 'number' && (lastSeq === null || seq > lastSeq)) lastSeq = seq
  }

  function emitNormalized(rawFrame, fromBackfill) {
    noteSession(rawFrame)
    trackSeen(frameKey(rawFrame))
    const norm = normalizeTelemetryFrame(rawFrame)
    norm._recvMs = Date.now()
    norm._fromBackfill = !!fromBackfill
    onFrame(norm)
  }

  // Frame live entrante: si estamos bufferizando (backfill en vuelo), acumular; si no, emitir.
  function onLiveFrame(rawFrame) {
    if (!rawFrame || typeof rawFrame !== 'object') return
    if (buffering) { liveBuffer.push(rawFrame); return }
    const k = frameKey(rawFrame)
    if (k && seen.has(k)) return
    emitNormalized(rawFrame, false)
  }

  async function runBackfillThenFlush() {
    buffering = true
    liveBuffer = []
    let backfill = []
    if (lastSeq !== null) {
      const url = `${baseUrl}${config.endpoints.backfill}?after_seq=${encodeURIComponent(lastSeq)}&limit=${config.backfillLimit}`
      try {
        const res = await fetch(url)
        if (res.ok) {
          const body = await res.json()
          backfill = Array.isArray(body) ? body : Array.isArray(body?.frames) ? body.frames : []
        }
      } catch { /* best-effort */ }
    }
    // Combinar backfill + live bufferizado, deduplicar y ordenar por seq antes de emitir.
    const live = liveBuffer
    liveBuffer = []
    buffering = false
    const { ordered, seen: nextSeen } = mergeAndOrder({ backfill, live, seen })
    seen = nextSeen
    for (const f of ordered) {
      noteSession(f)
      const k = frameKey(f)
      if (k) { if (!seenOrder.includes(k)) seenOrder.push(k) }
      const norm = normalizeTelemetryFrame(f)
      norm._recvMs = Date.now()
      norm._fromBackfill = true
      onFrame(norm)
    }
  }

  function scheduleReconnect() {
    if (closed) return
    const delay = config.wsBackoffMs[Math.min(attempt, config.wsBackoffMs.length - 1)] ?? config.wsBackoffMaxMs
    attempt += 1
    setState('reconnecting')
    retryTimer = setTimeout(startWs, delay)
  }

  function startWs() {
    if (closed) return
    const url = wsUrl(baseUrl)
    if (!url) { scheduleReconnect(); return }
    try {
      ws = new WebSocket(url)
    } catch {
      scheduleReconnect(); return
    }
    setState('connecting')
    ws.onopen = async () => {
      attempt = 0
      setState('connected')
      await runBackfillThenFlush()
    }
    ws.onmessage = (ev) => {
      try { onLiveFrame(JSON.parse(ev.data)) } catch { /* frame invalido: ignorar */ }
    }
    ws.onerror = () => { if (ws) { try { ws.close() } catch {} } }
    ws.onclose = () => {
      ws = null
      buffering = false
      if (closed) return
      scheduleReconnect()
    }
  }

  startWs()

  return function disconnect() {
    closed = true
    if (ws) { try { ws.close() } catch {} ws = null }
    if (retryTimer) { clearTimeout(retryTimer); retryTimer = null }
  }
}

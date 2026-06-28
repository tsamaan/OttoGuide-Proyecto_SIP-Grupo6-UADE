import { useEffect, useRef, useState } from 'react'
import { Play, Mic, Square } from 'lucide-react'
import { robotApi } from '../services/robotApi.js'
import { tourScriptToStartTourRequest, TourScriptValidationError } from '../services/tourMapper.js'
import { tourStartBlockReasons } from '../services/statusAdapter.js'

export default function ControlPanel({ mockMode, baseUrl, status, apiReachable, setStatus, refresh }) {
  const [busy, setBusy] = useState(null) // 'tour' | 'voice' | 'stop' | null
  const [msg, setMsg] = useState(null) // { text, kind: 'ok' | 'error' | 'critical' }
  const [voiceMockActive, setVoiceMockActive] = useState(false)
  const timers = useRef([])

  const clearTimers = () => {
    timers.current.forEach(clearTimeout)
    timers.current.forEach(clearInterval)
    timers.current = []
  }
  useEffect(() => clearTimers, [])

  const running = status.fsmState === 'navigating' || status.fsmState === 'interacting'

  // Bloqueo del boton de tour: nunca oculta un motivo (operational_ready, script_loaded,
  // guion vacio, API inalcanzable, etc.) — section 8 del task brief.
  const tourBlockReasons = mockMode ? [] : tourStartBlockReasons(status, { apiReachable })
  const tourBlocked = tourBlockReasons.length > 0

  async function startTour() {
    setBusy('tour'); setMsg(null)
    try {
      if (mockMode) {
        setStatus((s) => ({ ...s, fsmState: 'navigating', fsmStateLabel: 'recorrido' }))
        setMsg({ text: 'Recorrido iniciado (simulacion).', kind: 'ok' })
      } else {
        const script = await robotApi.getScript(baseUrl)
        const payload = tourScriptToStartTourRequest(script)
        await robotApi.startTour(baseUrl, payload)
        await refresh()
        setMsg({ text: `Recorrido iniciado (tour_id=${payload.tour_id}).`, kind: 'ok' })
      }
    } catch (err) {
      if (err instanceof TourScriptValidationError) {
        setMsg({ text: `Guion invalido: ${err.message}`, kind: 'error' })
      } else if (err?.status) {
        // Nunca ocultar 409/422/503: mostrar el detail que devuelve FastAPI.
        setMsg({ text: `No se pudo iniciar el recorrido (HTTP ${err.status}): ${err.detail ?? err.message}`, kind: 'error' })
      } else {
        setMsg({ text: `No se pudo iniciar el recorrido: ${err.message}`, kind: 'error' })
      }
    } finally {
      setBusy(null)
    }
  }

  // "Interaccion por voz": el backend canonico NO expone /chat/start. Este control nunca
  // hace una llamada real (tampoco sustituye con /tour/pause + audio vacio, que seria un
  // mock silencioso disfrazado de funcionalidad real). Solo anima localmente en mock mode.
  function startVoiceInteraction() {
    if (!mockMode) return
    setBusy('voice'); setMsg(null)
    setVoiceMockActive(true)
    setMsg({ text: 'Interaccion por voz simulada (mock mode). No hay llamada real al backend.', kind: 'ok' })
    const id = setTimeout(() => setVoiceMockActive(false), 4000)
    timers.current.push(id)
    setBusy(null)
  }

  async function stopAll() {
    if (!window.confirm('Vas a terminar la ejecucion en curso. Continuar?')) return
    setBusy('stop'); setMsg(null)
    try {
      if (mockMode) {
        clearTimers()
        setVoiceMockActive(false)
        setStatus((s) => ({ ...s, fsmState: 'idle', fsmStateLabel: 'reposo' }))
        setMsg({ text: 'Ejecucion terminada (simulacion).', kind: 'ok' })
      } else {
        const res = await robotApi.stopAll(baseUrl, 'web_operator')
        await refresh()
        if (res.terminal_safe === true) {
          setMsg({ text: 'Ejecucion terminada. Parada de emergencia confirmada (terminal_safe).', kind: 'ok' })
        } else {
          // Nunca un mensaje ambiguo de "exito" si la seguridad terminal no se confirmo.
          const errList = (res.errors ?? []).join('; ')
          setMsg({
            text: `ATENCION: la parada de emergencia NO confirmo seguridad terminal (HTTP ${res.httpStatus}).` +
              (errList ? ` Detalle: ${errList}` : ''),
            kind: 'critical',
          })
        }
      }
    } catch (err) {
      setMsg({
        text: `ERROR CRITICO ejecutando /emergency: ${err.detail ?? err.message}`,
        kind: 'critical',
      })
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="controls">
      <div className="controls-head">
        <h2 className="controls-title">Control del robot</h2>
        <div className="status-pills">
          <span className={`pill ${running ? 'pill-live' : 'pill-idle'}`}>{status.fsmStateLabel}</span>
          {status.tourId && <span className="pill pill-conv">Tour: {status.tourId}</span>}
          <span className="pill">Waypoint: {status.currentWaypointIndex}</span>
          {status.conversationRuntimeDegraded && (
            <span className="pill pill-llm-off" title={status.conversationRuntimeError ?? ''}>
              Conversacion degradada
            </span>
          )}
        </div>
      </div>

      <div className="controls-buttons">
        <button className="btn btn-primary" onClick={startTour}
          disabled={busy !== null || running || tourBlocked}
          title={tourBlocked ? tourBlockReasons.join('; ') : undefined}>
          <Play size={18} /> Iniciar recorrido
        </button>

        <button className="btn btn-accent" onClick={startVoiceInteraction}
          disabled={busy !== null || !mockMode}
          title={!mockMode ? 'Pendiente de integracion Wake Word/TTS - Fase 2' : undefined}>
          <Mic size={18} /> Interaccion por voz{voiceMockActive ? ' (simulando...)' : ''}
        </button>

        <button className="btn btn-danger" onClick={stopAll}
          disabled={busy !== null}>
          <Square size={18} /> Detener
        </button>
      </div>

      {!mockMode && (
        <p className="controls-note">
          Interaccion por voz: pendiente de integracion Wake Word/TTS — Fase 2.
        </p>
      )}
      {tourBlocked && (
        <p className="controls-note is-error">
          Recorrido bloqueado: {tourBlockReasons.join('; ')}
        </p>
      )}

      {msg && (
        <p className={`controls-msg ${msg.kind === 'critical' ? 'is-critical' : msg.kind === 'error' ? 'is-error' : 'is-ok'}`}>
          {msg.text}
        </p>
      )}
    </section>
  )
}

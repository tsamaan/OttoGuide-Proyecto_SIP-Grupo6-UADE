import { useEffect, useRef, useState } from 'react'
import { Play, Mic, Square } from 'lucide-react'
import { robotApi } from '../services/robotApi.js'
import { tourScriptToStartTourRequest, TourScriptValidationError } from '../services/tourMapper.js'
import { tourStartBlockReasons, interactionStartBlockReasons } from '../services/statusAdapter.js'

export default function ControlPanel({ mockMode, baseUrl, status, apiReachable, setStatus, refresh }) {
  const [busy, setBusy] = useState(null) // 'tour' | 'voice' | 'stop' | null
  const [msg, setMsg] = useState(null) // { text, kind: 'ok' | 'error' | 'critical' }
  const [voiceMockActive, setVoiceMockActive] = useState(false)
  const timers = useRef([])

  const runtime = status.interactionRuntime ?? {}
  const session = status.interactionSession ?? {}

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

  // Interaccion: en mock mode del frontend, solo animacion local (sin llamada real). Fuera
  // de mock mode, POST /interaction/start real contra el interaction runtime del backend
  // (C++ JSONL worker). Nunca se sustituye con un fallback local que simule exito.
  async function startVoiceInteraction() {
    if (mockMode) {
      setBusy('voice'); setMsg(null)
      setVoiceMockActive(true)
      setMsg({ text: 'Interaccion simulada (mock mode). No hay llamada real al backend.', kind: 'ok' })
      const id = setTimeout(() => setVoiceMockActive(false), 4000)
      timers.current.push(id)
      setBusy(null)
      return
    }
    setBusy('voice'); setMsg(null)
    try {
      const res = await robotApi.startInteraction(baseUrl, { locale: 'es', timeout_s: 15.0 })
      await refresh()
      const label = runtime.mock ? 'Interaccion C++ de protocolo' : (runtime.physical ? 'Interaccion fisica C++' : 'Interaccion')
      setMsg({ text: `${label} iniciada (interaction_id=${res.interaction_id}).`, kind: 'ok' })
    } catch (err) {
      setMsg({
        text: `No se pudo iniciar la interaccion (HTTP ${err.status ?? '?'}): ${err.detail ?? err.message}`,
        kind: 'error',
      })
    } finally {
      setBusy(null)
    }
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
        // Semantica software-only: software_motion_terminal/posture_preserved/damp_attempted
        // describen unicamente que hizo el software. Nunca se afirma seguridad mecanica
        // ("Robot mecanicamente seguro") — eso es responsabilidad exclusiva del operador.
        if (res.software_motion_terminal === true) {
          const opNote = res.operator_intervention_required
            ? ' Verificacion fisica del operador requerida.'
            : ''
          setMsg({
            text: `El software detuvo sus productores de movimiento (StopMove).${opNote}`,
            kind: 'ok',
          })
        } else {
          const errList = (res.errors ?? []).join('; ')
          setMsg({
            text: `ATENCION: el software NO confirmo el cese de sus productores de movimiento ` +
              `(HTTP ${res.httpStatus}). Verificacion fisica del operador requerida.` +
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

  // MVP-IA-CXX-R1 (FASE E): fuera de mock mode, el boton de Interaccion fisica solo se habilita
  // cuando TODAS estas condiciones se cumplen, y nunca se oculta un motivo de bloqueo:
  //   FSM = idle, runtime configured, runtime ready, runtime NO mock, runtime physical,
  //   y no hay una interaccion activa. El estado physical/ready se lee del backend (grounded en
  //   capabilities del worker), nunca se infiere localmente.
  const interactionBlockReasons = mockMode ? [] : interactionStartBlockReasons(status)
  const interactionBlocked = interactionBlockReasons.length > 0
  const interactionLabel = runtime.mock
    ? 'Interaccion C++ de protocolo'
    : (runtime.physical ? 'Interaccion fisica C++' : 'Interaccion')

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
          {!mockMode && runtime.configured && (
            <span
              className={`pill ${runtime.mock ? 'pill-mock' : (runtime.physical ? 'pill-physical' : '')}`}
              title={`heartbeat=${runtime.lastHeartbeatMonotonicS ?? 'N/A'} capabilities=${JSON.stringify(runtime.capabilities)}`}
            >
              {runtime.mock ? 'CXX PROTOCOL MOCK' : (runtime.physical ? 'PHYSICAL' : runtime.state.toUpperCase())}
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
          disabled={busy !== null || interactionBlocked}
          title={interactionBlocked ? `Interaccion bloqueada: ${interactionBlockReasons.join('; ')}` : undefined}>
          <Mic size={18} /> {interactionLabel}{voiceMockActive ? ' (simulando...)' : ''}
          {session.active ? ` — sesion: ${session.state}` : ''}
        </button>

        <button className="btn btn-danger" onClick={stopAll}
          disabled={busy !== null}>
          <Square size={18} /> Detener
        </button>
      </div>

      {!mockMode && !runtime.configured && (
        <p className="controls-note">
          Interaction runtime deshabilitado (INTERACTION_RUNTIME_BACKEND=disabled).
        </p>
      )}
      {!mockMode && runtime.configured && !runtime.ready && (
        <p className="controls-note is-error">
          Interaction runtime no listo: state={runtime.state} last_error={runtime.lastError ?? 'N/A'}
        </p>
      )}
      {!mockMode && runtime.configured && runtime.ready && interactionBlocked && (
        <p className="controls-note is-error">
          Interaccion bloqueada: {interactionBlockReasons.join('; ')}
        </p>
      )}
      {!mockMode && (session.active || session.sessionId) && (
        <p className="controls-note">
          Interaccion: id={session.sessionId ?? 'N/A'} state={session.state}
          {session.lastEvent ? ` last_event=${session.lastEvent}` : ''}
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

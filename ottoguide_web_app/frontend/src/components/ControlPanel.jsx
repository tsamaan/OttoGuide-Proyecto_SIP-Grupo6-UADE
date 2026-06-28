import { useEffect, useRef, useState } from 'react'
import { Play, MessageSquare, Square } from 'lucide-react'
import { robotApi } from '../services/robotApi.js'

const MODE_LABEL = { idle: 'En reposo', tour: 'Recorrido en curso', chat: 'Charla activa' }
const CONV_LABEL = {
  hibernacion: 'Hibernacion', escuchando: 'Escuchando', procesando: 'Procesando',
}

export default function ControlPanel({ mockMode, baseUrl, status, setStatus, refresh }) {
  const [busy, setBusy] = useState(null) // 'tour' | 'chat' | 'stop' | null
  const [msg, setMsg] = useState(null) // { text, kind: 'ok' | 'error' }
  const timers = useRef([])

  const clearTimers = () => {
    timers.current.forEach(clearTimeout)
    timers.current.forEach(clearInterval)
    timers.current = []
  }
  useEffect(() => clearTimers, [])

  const running = status.running
  const mode = status.mode

  // En simulacion, anima el estado de la conversacion para que se vea vivo.
  useEffect(() => {
    if (!(mockMode && mode === 'chat')) return
    const seq = ['hibernacion', 'escuchando', 'procesando', 'escuchando']
    let i = 0
    const id = setInterval(() => {
      i = (i + 1) % seq.length
      setStatus((s) => ({ ...s, conversation_state: seq[i] }))
    }, 2500)
    timers.current.push(id)
    return () => clearInterval(id)
  }, [mockMode, mode, setStatus])

  async function startTour() {
    setBusy('tour'); setMsg(null)
    try {
      if (mockMode) {
        setStatus({ mode: 'tour', running: true, llm_enabled: false, conversation_state: 'hibernacion' })
        // Simula que al terminar el recorrido el orquestador habilita el LLM.
        const id = setTimeout(() => setStatus((s) => (s.mode === 'tour' ? { ...s, llm_enabled: true } : s)), 8000)
        timers.current.push(id)
        setMsg({ text: 'Recorrido iniciado (simulacion).', kind: 'ok' })
      } else {
        await robotApi.startTour(baseUrl)
        await refresh()
        setMsg({ text: 'Recorrido iniciado.', kind: 'ok' })
      }
    } catch {
      setMsg({ text: 'No se pudo iniciar el recorrido. Revisa el cable y la IP del robot.', kind: 'error' })
    } finally {
      setBusy(null)
    }
  }

  async function startChat() {
    setBusy('chat'); setMsg(null)
    try {
      if (mockMode) {
        setStatus({ mode: 'chat', running: true, llm_enabled: true, conversation_state: 'hibernacion' })
        setMsg({ text: 'Charla iniciada (simulacion).', kind: 'ok' })
      } else {
        await robotApi.startChat(baseUrl)
        await refresh()
        setMsg({ text: 'Charla iniciada.', kind: 'ok' })
      }
    } catch {
      setMsg({ text: 'No se pudo iniciar la charla. Revisa el cable y la IP del robot.', kind: 'error' })
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
        setStatus({ mode: 'idle', running: false, llm_enabled: false, conversation_state: 'hibernacion' })
        setMsg({ text: 'Ejecucion terminada (simulacion).', kind: 'ok' })
      } else {
        await robotApi.stopAll(baseUrl)
        await refresh()
        setMsg({ text: 'Ejecucion terminada.', kind: 'ok' })
      }
    } catch {
      setMsg({ text: 'No se pudo terminar la ejecucion. Revisa la conexion con el robot.', kind: 'error' })
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="controls">
      <div className="controls-head">
        <h2 className="controls-title">Control del robot</h2>
        <div className="status-pills">
          <span className={`pill ${running ? 'pill-live' : 'pill-idle'}`}>{MODE_LABEL[mode] || mode}</span>
          {mode === 'chat' && (
            <span className="pill pill-conv">Dialogo: {CONV_LABEL[status.conversation_state] || status.conversation_state}</span>
          )}
          <span className={`pill ${status.llm_enabled ? 'pill-llm-on' : 'pill-llm-off'}`}>
            LLM {status.llm_enabled ? 'habilitado' : 'apagado'}
          </span>
        </div>
      </div>

      <div className="controls-buttons">
        <button className="btn btn-primary" onClick={startTour}
          disabled={busy !== null || running}>
          <Play size={18} /> Iniciar recorrido
        </button>

        <button className="btn btn-accent" onClick={startChat}
          disabled={busy !== null || running}>
          <MessageSquare size={18} /> Iniciar charla
        </button>

        <button className="btn btn-danger" onClick={stopAll}
          disabled={busy !== null || !running}>
          <Square size={18} /> Terminar ejecucion
        </button>
      </div>

      {msg && <p className={`controls-msg ${msg.kind === 'error' ? 'is-error' : 'is-ok'}`}>{msg.text}</p>}
    </section>
  )
}

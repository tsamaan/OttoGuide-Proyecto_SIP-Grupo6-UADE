// NB-HIL-WEB-R0 hook de telemetria (perfil real/replay, siempre read-only, nunca mock).
// Devuelve:
//   frame     -> ultimo paquete (tarjetas, tabla y resumen), ~10 Hz
//   history   -> ultimos N segundos de frames (para graficos), refresco mas lento
//   connState -> connecting | connected | reconnecting | error
import { useEffect, useRef, useState } from 'react'
import { config, HISTORY_SAMPLES } from '../config.js'
import { connectTelemetry } from '../services/telemetry.js'

export function useTelemetry() {
  const [frame, setFrame] = useState(null)
  const [history, setHistory] = useState([])
  const [connState, setConnState] = useState('connecting')

  // buffer mutable: se actualiza a 10 Hz sin re-renderizar el arbol de graficos.
  const bufferRef = useRef([])

  function pushFrame(f) {
    const buf = bufferRef.current
    buf.push(f)
    if (buf.length > HISTORY_SAMPLES) buf.splice(0, buf.length - HISTORY_SAMPLES)
    setFrame(f)
  }

  useEffect(() => {
    bufferRef.current = []
    setHistory([])
    setFrame(null)
    setConnState('connecting')
    const disconnect = connectTelemetry(config.robotBaseUrl, {
      onFrame: pushFrame,
      onState: setConnState,
    })
    return disconnect
  }, [])

  // Snapshot del buffer hacia los graficos, a ritmo mas lento (fluidez con muchas curvas).
  useEffect(() => {
    const id = setInterval(() => setHistory(bufferRef.current.slice()), config.chartRefreshMs)
    return () => clearInterval(id)
  }, [])

  return { frame, history, connState }
}

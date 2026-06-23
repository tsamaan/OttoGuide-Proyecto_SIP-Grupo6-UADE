// Hook que entrega la telemetria del robot, ya sea simulada (mock) o real (backend).
// Devuelve:
//   frame   -> ultimo paquete (para tarjetas y tabla), ~10 Hz
//   history -> ultimos N segundos de frames (para graficos), refresco mas lento
//   connState -> estado de la conexion: mock | connecting | connected | polling | reconnecting | error
import { useEffect, useRef, useState } from 'react'
import { config, HISTORY_SAMPLES } from '../config.js'
import { mockFrame, resetMock } from '../mock/mockTelemetry.js'
import { connectTelemetry } from '../services/telemetry.js'

export function useTelemetry({ mockMode, baseUrl }) {
  const [frame, setFrame] = useState(null)
  const [history, setHistory] = useState([])
  const [connState, setConnState] = useState(mockMode ? 'mock' : 'connecting')

  // buffer mutable: se actualiza a 10 Hz sin re-renderizar.
  const bufferRef = useRef([])

  // Recibe un frame, lo guarda en buffer y actualiza el frame visible.
  function pushFrame(f) {
    const buf = bufferRef.current
    buf.push(f)
    if (buf.length > HISTORY_SAMPLES) buf.splice(0, buf.length - HISTORY_SAMPLES)
    setFrame(f)
  }

  // Fuente de datos.
  useEffect(() => {
    bufferRef.current = []
    setHistory([])
    setFrame(null)

    if (mockMode) {
      setConnState('mock')
      resetMock()
      const id = setInterval(() => pushFrame(mockFrame()), Math.round(1000 / config.dataHz))
      return () => clearInterval(id)
    }

    setConnState('connecting')
    const disconnect = connectTelemetry(baseUrl, {
      onFrame: pushFrame,
      onState: setConnState,
    })
    return disconnect
  }, [mockMode, baseUrl])

  // Snapshot del buffer hacia los graficos, a un ritmo mas lento (fluidez con muchas curvas).
  useEffect(() => {
    const id = setInterval(() => setHistory(bufferRef.current.slice()), config.chartRefreshMs)
    return () => clearInterval(id)
  }, [])

  return { frame, history, connState }
}

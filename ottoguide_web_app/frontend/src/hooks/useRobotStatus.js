// Hook de estado del sistema (mode / running / llm_enabled / conversation_state).
// En modo real, lo consulta al backend periodicamente.
// En modo simulacion, lo maneja localmente (lo setean los botones).
import { useCallback, useEffect, useState } from 'react'
import { robotApi } from '../services/robotApi.js'

const IDLE = { mode: 'idle', running: false, llm_enabled: false, conversation_state: 'hibernacion' }

export function useRobotStatus({ mockMode, baseUrl }) {
  const [status, setStatus] = useState(IDLE)

  const refresh = useCallback(async () => {
    if (mockMode) return
    try {
      setStatus(await robotApi.getStatus(baseUrl))
    } catch {
      /* sin conexion: dejamos el ultimo estado conocido */
    }
  }, [mockMode, baseUrl])

  useEffect(() => {
    setStatus(IDLE)
    if (mockMode) return
    refresh()
    const id = setInterval(refresh, 1500)
    return () => clearInterval(id)
  }, [mockMode, baseUrl, refresh])

  return { status, setStatus, refresh }
}

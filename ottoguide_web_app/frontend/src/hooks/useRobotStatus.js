// Hook de estado del sistema, adaptado desde el StatusResponse canonico (GET /status).
// En modo real, lo consulta al backend periodicamente. En modo simulacion, usa un estado
// local explicitamente etiquetado como mock (nunca presentado como estado fisico real).
import { useCallback, useEffect, useState } from 'react'
import { robotApi } from '../services/robotApi.js'
import { adaptStatusResponse, defaultUiStatus } from '../services/statusAdapter.js'

const MOCK_IDLE = { ...defaultUiStatus(), mock: true }

export function useRobotStatus({ mockMode, baseUrl }) {
  const [status, setStatus] = useState(MOCK_IDLE)
  const [apiReachable, setApiReachable] = useState(true)

  const refresh = useCallback(async () => {
    if (mockMode) return
    try {
      const raw = await robotApi.getStatus(baseUrl)
      setStatus(adaptStatusResponse(raw))
      setApiReachable(true)
    } catch {
      // Sin conexion: dejamos el ultimo estado conocido, pero marcamos la API inalcanzable
      // para que la UI bloquee acciones en lugar de operar a ciegas sobre datos viejos.
      setApiReachable(false)
    }
  }, [mockMode, baseUrl])

  useEffect(() => {
    setStatus(mockMode ? MOCK_IDLE : defaultUiStatus())
    setApiReachable(true)
    if (mockMode) return
    refresh()
    const id = setInterval(refresh, 1500)
    return () => clearInterval(id)
  }, [mockMode, baseUrl, refresh])

  return { status, setStatus, refresh, apiReachable }
}

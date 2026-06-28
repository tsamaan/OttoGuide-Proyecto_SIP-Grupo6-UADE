// Capa de acceso al backend canonico del robot. Es lo unico que conoce las rutas concretas.
// Si en el robot cambian endpoints o puerto, se ajusta aca y en config.js.
import { config } from '../config.js'

// Error tipado para que la UI distinga 4xx (rechazo del backend, ej. 409/422/503),
// 5xx (fallo del backend) y errores de red/timeout (backend inalcanzable).
export class RobotApiError extends Error {
  constructor(message, { kind, status = null, detail = null } = {}) {
    super(message)
    this.name = 'RobotApiError'
    this.kind = kind // 'client' (4xx) | 'server' (5xx) | 'network' | 'timeout'
    this.status = status
    this.detail = detail
  }
}

function classifyStatus(status) {
  if (status >= 500) return 'server'
  if (status >= 400) return 'client'
  return null
}

async function parseErrorDetail(res) {
  try {
    const body = await res.json()
    return body?.detail ?? null
  } catch {
    return null
  }
}

async function request(baseUrl, path, { method = 'GET', body = null } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), config.requestTimeoutMs)

  let res
  try {
    res = await fetch(`${baseUrl}${path}`, {
      method,
      headers: body !== null ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== null ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })
  } catch (err) {
    if (err?.name === 'AbortError') {
      throw new RobotApiError(`Timeout esperando respuesta de ${path}`, { kind: 'timeout' })
    }
    throw new RobotApiError(`No se pudo conectar con ${path}: ${err?.message ?? err}`, { kind: 'network' })
  } finally {
    clearTimeout(timer)
  }

  if (!res.ok) {
    const detail = await parseErrorDetail(res)
    throw new RobotApiError(
      detail ? `HTTP ${res.status} en ${path}: ${detail}` : `HTTP ${res.status} en ${path}`,
      { kind: classifyStatus(res.status), status: res.status, detail },
    )
  }

  // Algunas respuestas (ej. ciertos 2xx) pueden no traer JSON; tratamos cuerpo vacio como null.
  const text = await res.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    throw new RobotApiError(`Respuesta no JSON de ${path}`, { kind: 'client', status: res.status })
  }
}

function get(baseUrl, path) {
  return request(baseUrl, path, { method: 'GET' })
}

function post(baseUrl, path, body = null) {
  return request(baseUrl, path, { method: 'POST', body })
}

// POST /emergency es un caso especial: 503/504 son respuestas TIPADAS validas (terminal_safe
// explicito en el cuerpo), no errores genericos a descartar. No usamos request()/post() — leemos
// el body en todos los casos (2xx, 4xx, 5xx) y dejamos que el caller decida segun terminal_safe.
async function postEmergency(baseUrl, path, body) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), config.requestTimeoutMs)

  let res
  try {
    res = await fetch(`${baseUrl}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
  } catch (err) {
    if (err?.name === 'AbortError') {
      throw new RobotApiError(`Timeout esperando respuesta de ${path}`, { kind: 'timeout' })
    }
    throw new RobotApiError(`No se pudo conectar con ${path}: ${err?.message ?? err}`, { kind: 'network' })
  } finally {
    clearTimeout(timer)
  }

  // 500 no es un EmergencyResponse tipado (excepcion no controlada en el backend) — error generico.
  if (res.status >= 500 && res.status !== 503 && res.status !== 504) {
    const detail = await parseErrorDetail(res)
    throw new RobotApiError(detail ?? `HTTP ${res.status} en ${path}`, {
      kind: 'server', status: res.status, detail,
    })
  }

  const text = await res.text()
  if (!text) {
    throw new RobotApiError(`Respuesta vacia de ${path} (HTTP ${res.status})`, {
      kind: classifyStatus(res.status) ?? 'server', status: res.status,
    })
  }
  const parsed = JSON.parse(text)
  return { httpStatus: res.status, ...parsed }
}

export const robotApi = {
  // Guion canonico de tour (para construir el body de /tour/start)
  getScript: (baseUrl) => get(baseUrl, config.endpoints.script),
  // Boton "Iniciar recorrido" — requiere el body canonico {waypoints, tour_id}
  startTour: (baseUrl, payload) => post(baseUrl, config.endpoints.tourStart, payload),
  // Boton "Detener" — envia {reason} y devuelve {httpStatus, executed, terminal_safe,
  // already_emergency, errors, ...} tal como lo emite el backend. 200/503/504 son
  // respuestas tipadas validas; 500/network/timeout se manejan como RobotApiError.
  stopAll: (baseUrl, reason = 'web_operator') => postEmergency(baseUrl, config.endpoints.stop, { reason }),
  // Estado del sistema
  getStatus: (baseUrl) => get(baseUrl, config.endpoints.status),
}

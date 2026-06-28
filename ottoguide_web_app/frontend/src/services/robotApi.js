// Capa de acceso al backend del robot. Es lo unico que conoce las rutas concretas.
// Si en el robot cambian endpoints o puerto, se ajusta aca y en config.js.
import { config } from '../config.js'

async function post(baseUrl, path) {
  const res = await fetch(`${baseUrl}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })
  if (!res.ok) throw new Error(`HTTP ${res.status} en ${path}`)
  return res.json()
}

async function get(baseUrl, path) {
  const res = await fetch(`${baseUrl}${path}`)
  if (!res.ok) throw new Error(`HTTP ${res.status} en ${path}`)
  return res.json()
}

export const robotApi = {
  // Boton "Iniciar recorrido"
  startTour: (baseUrl) => post(baseUrl, config.endpoints.tourStart),
  // Boton "Iniciar charla"
  startChat: (baseUrl) => post(baseUrl, config.endpoints.chatStart),
  // Boton "Terminar ejecucion"
  stopAll: (baseUrl) => post(baseUrl, config.endpoints.stop),
  // Estado del sistema
  getStatus: (baseUrl) => get(baseUrl, config.endpoints.status),
}

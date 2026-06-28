// Transforma el TourScript canonico (GET /content/script) en el body de POST /tour/start.
// Modulo puro: sin fetch, sin React, sin estado — testeable con node --test.

export class TourScriptValidationError extends Error {
  constructor(message) {
    super(message)
    this.name = 'TourScriptValidationError'
  }
}

// Genera un tour_id unico sin depender de crypto.randomUUID (no disponible en todos los
// contextos de test); suficiente unicidad para correlacionar sesiones, no para seguridad.
export function generateTourId() {
  const rand = Math.random().toString(36).slice(2, 10)
  return `tour-${Date.now()}-${rand}`
}

// Convierte un solo WaypointContent.pose_2d {x,y,theta} en un NavWaypointDTO {x,y,yaw_rad,frame_id}.
export function waypointContentToNavWaypoint(waypointContent) {
  const pose = waypointContent?.pose_2d
  if (!pose || typeof pose.x !== 'number' || typeof pose.y !== 'number' || typeof pose.theta !== 'number') {
    throw new TourScriptValidationError(
      `Waypoint '${waypointContent?.waypoint_id ?? '?'}' tiene pose_2d invalido o incompleto.`,
    )
  }
  return { x: pose.x, y: pose.y, yaw_rad: pose.theta, frame_id: 'map' }
}

// Convierte un TourScript completo {version, waypoints:[...]} en un StartTourRequest
// {waypoints:[...], tour_id}. Lanza TourScriptValidationError si no hay waypoints.
export function tourScriptToStartTourRequest(tourScript, { tourId = generateTourId() } = {}) {
  const waypoints = tourScript?.waypoints
  if (!Array.isArray(waypoints) || waypoints.length === 0) {
    throw new TourScriptValidationError('El guion no contiene waypoints; no se puede iniciar el tour.')
  }
  return {
    waypoints: waypoints.map(waypointContentToNavWaypoint),
    tour_id: tourId,
  }
}

// Adapta el StatusResponse canonico (GET /status) a un modelo de UI explicito.
// Reemplaza el viejo vocabulario mode/running/llm_enabled/conversation_state, que el
// backend canonico nunca informo (era propio de un backend especulativo de pilar-web).
// Modulo puro: testeable con node --test.

export const FSM_STATE_LABELS = {
  idle: 'reposo',
  navigating: 'recorrido',
  interacting: 'interaccion',
  emergency: 'emergencia',
}

const DEFAULT_UI_STATUS = Object.freeze({
  fsmState: 'idle',
  fsmStateLabel: FSM_STATE_LABELS.idle,
  tourId: null,
  currentWaypointIndex: 0,
  operationalReady: false,
  readinessErrors: [],
  navigationBackendRequested: 'unknown',
  navigationBackendResolved: 'unknown',
  navigationStarted: false,
  scriptLoaded: false,
  scriptVersion: null,
  scriptWaypointCount: 0,
  conversationRuntimeDegraded: false,
  conversationRuntimeError: null,
})

// statusResponse: el JSON crudo devuelto por GET /status (api/schemas.py::StatusResponse).
// No inventa campos que el backend no informe (ej. nunca deriva un llm_enabled).
export function adaptStatusResponse(statusResponse) {
  if (!statusResponse || typeof statusResponse !== 'object') {
    return { ...DEFAULT_UI_STATUS }
  }
  const fsmState = statusResponse.state ?? 'idle'
  return {
    fsmState,
    fsmStateLabel: FSM_STATE_LABELS[fsmState] ?? fsmState,
    tourId: statusResponse.tour_id ?? null,
    currentWaypointIndex: statusResponse.current_waypoint_index ?? 0,
    operationalReady: Boolean(statusResponse.operational_ready),
    readinessErrors: statusResponse.readiness_errors ?? [],
    navigationBackendRequested: statusResponse.navigation_backend_requested ?? 'unknown',
    navigationBackendResolved: statusResponse.navigation_backend_resolved ?? 'unknown',
    navigationStarted: Boolean(statusResponse.navigation_started),
    scriptLoaded: Boolean(statusResponse.script_loaded),
    scriptVersion: statusResponse.script_version ?? null,
    scriptWaypointCount: statusResponse.script_waypoint_count ?? 0,
    conversationRuntimeDegraded: Boolean(statusResponse.conversation_runtime_degraded),
    conversationRuntimeError: statusResponse.conversation_runtime_error ?? null,
  }
}

export function defaultUiStatus() {
  return { ...DEFAULT_UI_STATUS }
}

// Determina si el boton de iniciar tour debe estar deshabilitado, y por que.
// Nunca oculta un motivo: si hay mas de uno, todos se reportan.
export function tourStartBlockReasons(uiStatus, { apiReachable = true } = {}) {
  const reasons = []
  if (!apiReachable) reasons.push('API no disponible')
  if (!uiStatus.operationalReady) reasons.push('Sistema no operational_ready')
  if (!uiStatus.scriptLoaded) reasons.push('Guion no cargado (script_loaded=false)')
  if (uiStatus.scriptWaypointCount === 0) reasons.push('El guion no contiene waypoints')
  for (const err of uiStatus.readinessErrors ?? []) reasons.push(err)
  return reasons
}

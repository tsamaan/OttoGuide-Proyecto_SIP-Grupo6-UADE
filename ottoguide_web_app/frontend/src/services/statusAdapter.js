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

const DEFAULT_INTERACTION_RUNTIME = Object.freeze({
  configured: false,
  state: 'not_configured',
  ready: false,
  mock: false,
  physical: false,
  capabilities: {},
  lastHeartbeatMonotonicS: null,
  lastError: null,
})

const DEFAULT_INTERACTION_SESSION = Object.freeze({
  active: false,
  sessionId: null,
  state: 'idle',
  lastEvent: null,
})

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
  interactionRuntime: DEFAULT_INTERACTION_RUNTIME,
  interactionSession: DEFAULT_INTERACTION_SESSION,
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
    interactionRuntime: adaptInteractionRuntime(statusResponse.interaction_runtime),
    interactionSession: adaptInteractionSession(statusResponse.interaction_session),
  }
}

// interactionRuntime: refleja InteractionRuntimeStatusResponse (api/schemas.py). mock=true
// y physical=false deben mostrarse siempre que el backend configurado sea cxx_jsonl_mock;
// nunca se infiere "physical" localmente, solo se lee lo que el backend ya calculo.
function adaptInteractionRuntime(raw) {
  if (!raw || typeof raw !== 'object') return { ...DEFAULT_INTERACTION_RUNTIME }
  return {
    configured: Boolean(raw.configured),
    state: raw.state ?? 'not_configured',
    ready: Boolean(raw.ready),
    mock: Boolean(raw.mock),
    physical: Boolean(raw.physical),
    capabilities: raw.capabilities ?? {},
    lastHeartbeatMonotonicS: raw.last_heartbeat_monotonic_s ?? null,
    lastError: raw.last_error ?? null,
  }
}

function adaptInteractionSession(raw) {
  if (!raw || typeof raw !== 'object') return { ...DEFAULT_INTERACTION_SESSION }
  return {
    active: Boolean(raw.active),
    sessionId: raw.session_id ?? null,
    state: raw.state ?? 'idle',
    lastEvent: raw.last_event ?? null,
  }
}

export function defaultUiStatus() {
  return { ...DEFAULT_UI_STATUS }
}

// MVP-IA-CXX-R1 (FASE E): motivos por los que el boton de Interaccion fisica debe estar
// bloqueado. Nunca oculta un motivo. El boton se habilita solo con lista vacia, lo que exige:
//   FSM=idle, runtime configured, ready, NO mock, physical, y sin interaccion activa.
// physical/ready se leen del backend (grounded en las capabilities del worker), nunca se infieren.
export function interactionStartBlockReasons(uiStatus) {
  const runtime = uiStatus?.interactionRuntime ?? {}
  const session = uiStatus?.interactionSession ?? {}
  const reasons = []
  if (!runtime.configured) {
    reasons.push('runtime no configurado')
    return reasons
  }
  if (uiStatus?.fsmState !== 'idle') reasons.push(`FSM=${uiStatus?.fsmState} (requiere idle)`)
  if (!runtime.ready) reasons.push(`runtime no listo (state=${runtime.state})`)
  if (runtime.mock) reasons.push('runtime es mock (protocol test double)')
  else if (!runtime.physical) reasons.push('runtime no reporta physical=true')
  if (session.active) reasons.push(`interaccion activa (state=${session.state})`)
  return reasons
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

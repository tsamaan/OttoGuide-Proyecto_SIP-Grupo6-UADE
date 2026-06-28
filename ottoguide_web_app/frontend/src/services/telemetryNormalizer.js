// Normaliza frames de telemetria del backend canonico (build_telemetry_payload() en
// src/core/tour_orchestrator.py, transmitido via WS /ws/telemetry) a un shape estable
// para la UI, con defaults defensivos si el backend omite un campo. Modulo puro.

const DEFAULT_FRAME = Object.freeze({
  timestamp: null,
  fsmState: 'UNKNOWN',
  currentWaypointId: 'N/A',
  batteryLevel: null,
  nlpIntent: 'UNKNOWN',
  nlpSourcePipeline: 'N/A',
  nlpAnswerPreview: '',
})

export function normalizeTelemetryFrame(rawFrame) {
  if (!rawFrame || typeof rawFrame !== 'object') {
    return { ...DEFAULT_FRAME }
  }
  return {
    timestamp: rawFrame.timestamp ?? null,
    fsmState: rawFrame.fsm_state ?? 'UNKNOWN',
    currentWaypointId: rawFrame.current_waypoint_id ?? 'N/A',
    batteryLevel: typeof rawFrame.battery_level === 'number' ? rawFrame.battery_level : null,
    nlpIntent: rawFrame.nlp_intent ?? 'UNKNOWN',
    nlpSourcePipeline: rawFrame.nlp_source_pipeline ?? 'N/A',
    nlpAnswerPreview: rawFrame.nlp_answer_preview ?? '',
  }
}

export function defaultTelemetryFrame() {
  return { ...DEFAULT_FRAME }
}

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

    // LIVE-WEB-DEMO-R2: telemetria fisica rica del bridge read-only. Se conservan tal cual
    // (nunca se convierte null en 0): un campo ausente en el mensaje DDS real permanece null.
    robot: rawFrame.robot ?? null,
    readOnlyDemo: rawFrame.read_only_demo === true,
    modeMachine: rawFrame.mode_machine ?? null,
    motors: Array.isArray(rawFrame.motors) ? rawFrame.motors : [],
    imu: rawFrame.imu ?? {},
    power_v: rawFrame.power_v ?? null,
    power_a: rawFrame.power_a ?? null,
    foot_force: rawFrame.foot_force ?? null,
    bms: rawFrame.bms ?? null,
    odom: rawFrame.odom ?? {},
    lf_odom: rawFrame.lf_odom ?? {},
    lidar: rawFrame.lidar ?? {},
    rates: rawFrame.rates ?? {},

    // NB-HIL-WEB-R0: identidad y procedencia del frame (bridge read-only).
    // availability: mapa {imu,bms,energy,...} calculado en el bridge tras validar cada dato;
    // la UI oculta cards/graficos cuando availability.<x> !== true. Un campo ausente => false.
    seq: typeof rawFrame.seq === 'number' ? rawFrame.seq : null,
    sessionId: rawFrame.session_id ?? rawFrame.sessionId ?? null,
    serverUtc: rawFrame.server_utc ?? null,
    serverMonotonicNs: rawFrame.server_monotonic_ns ?? null,
    sourceProfile: rawFrame.source_profile ?? null, // 'REAL' | 'REPLAY' | null
    availability: (rawFrame.availability && typeof rawFrame.availability === 'object')
      ? rawFrame.availability : {},
  }
}

export function defaultTelemetryFrame() {
  return { ...DEFAULT_FRAME }
}

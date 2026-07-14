// Fixtures sanitizados de la sesion fisica FINAL-ROBOT-R0 (backend real 97c5de4).
// Capturados de ws_frames.jsonl y backend_status.json del companion. Sin IPs ni datos
// privados. El contrato canonico del backend real NO incluye `motors`, `bms` ni `power_*`;
// esta es la causa del crash de render que estos fixtures reproducen y protegen.

// Frames canonicos reales (WS /ws/telemetry), tal como llegan del backend real.
export const canonicalTelemetryHistory = [
  { timestamp: '2026-07-13T21:24:49.295553+00:00', fsm_state: 'IDLE', current_waypoint_id: 'N/A', battery_level: 100.0, nlp_intent: 'UNKNOWN', nlp_source_pipeline: 'N/A', nlp_answer_preview: '', interaction_session: { session_id: 'standalone:3', state: 'completed', last_event: 'playback_completed' } },
  { timestamp: '2026-07-13T21:24:52.309947+00:00', fsm_state: 'IDLE', current_waypoint_id: 'N/A', battery_level: 100.0, nlp_intent: 'UNKNOWN', nlp_source_pipeline: 'N/A', nlp_answer_preview: '', interaction_session: { session_id: 'standalone:4', state: 'active', last_event: null } },
  { timestamp: '2026-07-13T21:24:52.311815+00:00', fsm_state: 'IDLE', current_waypoint_id: 'N/A', battery_level: 100.0, nlp_intent: 'UNKNOWN', nlp_source_pipeline: 'N/A', nlp_answer_preview: '', interaction_session: { session_id: 'standalone:4', state: 'completed', last_event: 'playback_completed' } },
]

// StatusResponse canonico real (GET /status), sanitizado (URL de diagnostico de fabrica
// reemplazada). operational_ready=false: navegacion deshabilitada (runtime status-only).
export const canonicalBackendStatus = {
  state: 'idle',
  tour_id: null,
  current_waypoint_index: 0,
  last_error: null,
  operational_ready: false,
  readiness_errors: ['navigation disabled: status-only real runtime'],
  navigation_backend_requested: 'disabled',
  navigation_backend_resolved: 'disabled',
  navigation_started: false,
  script_loaded: true,
  script_version: '2.0.0',
  script_waypoint_count: 5,
  conversation_runtime_degraded: false,
  conversation_runtime_error: null,
  interaction_runtime: {
    configured: true, protocol_version: 1, state: 'ready', ready: true, mock: true, physical: false,
    capabilities: { audio_capture: false, spanish_tts: false, physical_playback: false },
    last_heartbeat_monotonic_s: 6543.865271586, last_error: null, termination_reason: null,
  },
  interaction_session: { active: false, session_id: null, state: 'idle', last_event: null },
}

// Frame rico representativo del modo simulacion (mock/mockTelemetry.js): SI trae motores,
// bms y potencia. Usado para verificar que los graficos siguen funcionando con datos ricos.
export const mockRichFrame = {
  robot: 'G1',
  timestamp: 12.3,
  power_v: 27.5,
  power_a: 3.4,
  motors: [
    { index: 0, name: 'L_HIP', group: 'left_leg', q_deg: 1.2, temperature: 33 },
    { index: 3, name: 'L_KNEE', group: 'left_leg', q_deg: -2.4, temperature: 47 },
    { index: 6, name: 'R_HIP', group: 'right_leg', q_deg: 0.8, temperature: 31 },
  ],
  bms: { soc: 74, cell_vol: [3520, 3518, 3525, 3530, 3522, 3519] },
}

export const mockRichHistory = [
  { ...mockRichFrame, timestamp: 12.1 },
  { ...mockRichFrame, timestamp: 12.2 },
  { ...mockRichFrame, timestamp: 12.3 },
]

// Derivacion pura y sin DOM del modelo de graficos a partir del historial de telemetria.
//
// El contrato canonico del backend real (build_telemetry_payload() en
// src/core/tour_orchestrator.py) NO incluye arrays por motor (`motors`), bateria (`bms`)
// ni potencia (`power_v`/`power_a`); esos campos solo existen en el frame de simulacion
// (mock/mockTelemetry.js). Antes de este modulo, ChartsGrid asumia el shape rico del mock
// y hacia `history.at(-1).motors.map(...)`, lo que lanzaba
// `TypeError: Cannot read properties of undefined (reading 'map')` y derribaba todo el
// arbol React en perfil real. Este modulo tolera la ausencia de esos campos.

// Devuelve siempre un array de motores para una muestra dada (vacio si el frame no lo trae).
export function sampleMotors(sample) {
  return Array.isArray(sample?.motors) ? sample.motors : []
}

// True si hay telemetria rica de motores disponible: el ultimo frame trae motores, o
// alguna muestra del historial los trae. Un array `motors` vacio es valido (no rico).
export function hasRichTelemetry(history) {
  const safeHistory = Array.isArray(history) ? history : []
  return safeHistory.some((f) => sampleMotors(f).length > 0)
}

// Modelo derivado, defensivo, consumido por ChartsGrid.
export function deriveChartsModel(history) {
  const safeHistory = Array.isArray(history) ? history : []
  const latest = safeHistory.at(-1) ?? {}
  const motors = sampleMotors(latest)
  const groups = [...new Set(motors.map((m) => m.group))]
  return {
    safeHistory,
    motors,
    groups,
    richTelemetryAvailable: hasRichTelemetry(safeHistory),
  }
}

// Construye filas {t, ...valores} a partir del historial de frames. Tolera history no-array
// y frames sin timestamp numerico (el mock usa segundos numericos; los frames reales usan
// ISO string y no producen graficos ricos, pero nunca deben lanzar).
export function buildRows(history, valueFor) {
  const safeHistory = Array.isArray(history) ? history : []
  if (!safeHistory.length) return []
  const t0 = safeHistory[0].timestamp
  return safeHistory.map((f) => {
    const row = { t: +(f.timestamp - t0).toFixed(1) }
    valueFor(f, row)
    return row
  })
}

// C4: una serie es valida solo si tiene al menos una muestra numerica en `keys`. Un grafico
// cuyas series estan completamente null/undefined/sin muestras NO debe renderizarse.
export function seriesHasData(rows, keys) {
  if (!Array.isArray(rows) || !rows.length) return false
  const ks = Array.isArray(keys) ? keys : [keys]
  return rows.some((row) => ks.some((k) => typeof row[k] === 'number' && Number.isFinite(row[k])))
}

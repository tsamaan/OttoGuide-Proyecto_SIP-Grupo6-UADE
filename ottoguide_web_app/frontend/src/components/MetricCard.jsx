// Tarjeta generica para un grupo de metricas.
// notAvailable: true cuando el contrato actual del backend canonico no expone estos datos
// en real mode (motores/IMU/fuerzas/energia no estan en build_telemetry_payload()). Nunca
// se sustituye en silencio por datos mock — se etiqueta explicitamente.
export default function MetricCard({ title, icon, children, notAvailable = false, mockMode = false }) {
  return (
    <section className="card">
      <header className="card-head">
        <span className="card-icon">{icon}</span>
        <h3 className="card-title">{title}</h3>
        {mockMode && <span className="card-badge card-badge-mock">simulado</span>}
      </header>
      <div className="card-body">
        {notAvailable
          ? <p className="card-not-available">No disponible en el contrato actual</p>
          : children}
      </div>
    </section>
  )
}

// Fila etiqueta + valor.
export function MetricRow({ label, value, unit }) {
  return (
    <div className="metric-row">
      <span className="metric-label">{label}</span>
      <span className="metric-value">
        {value}
        {unit ? <span className="metric-unit"> {unit}</span> : null}
      </span>
    </div>
  )
}

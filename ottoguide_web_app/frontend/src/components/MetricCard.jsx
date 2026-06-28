// Tarjeta generica para un grupo de metricas.
export default function MetricCard({ title, icon, children }) {
  return (
    <section className="card">
      <header className="card-head">
        <span className="card-icon">{icon}</span>
        <h3 className="card-title">{title}</h3>
      </header>
      <div className="card-body">{children}</div>
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

// Tarjeta generica para un grupo de metricas.
// NB-HIL-WEB-R0 (C3): una card sin datos NO se renderiza vacia ni con leyenda de "no
// disponible" — devuelve null y desaparece del DOM. Asi .card-not-available = 0 y no queda
// ninguna card vacia. El texto "No disponible en el contrato actual" se elimina por completo.
export default function MetricCard({ title, icon, children, notAvailable = false }) {
  if (notAvailable) return null
  return (
    <section className="card">
      <header className="card-head">
        <span className="card-icon">{icon}</span>
        <h3 className="card-title">{title}</h3>
      </header>
      <div className="card-body">
        {children}
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

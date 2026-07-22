import { memo } from 'react'

// Color de la celda de temperatura: verde <40, amarillo 40-60, rojo >60.
function tempClass(t) {
  if (t >= 60) return 'temp-crit'
  if (t >= 40) return 'temp-warn'
  return 'temp-ok'
}

function MotorsTable({ motors }) {
  const rows = motors || []
  return (
    <div className="table-wrap">
      <table className="motors-table">
        <thead>
          <tr>
            <th>Grupo</th>
            <th>Motor</th>
            <th className="num">Angulo (°)</th>
            <th className="num">Vel. (rad/s)</th>
            <th className="num">Torque (N·m)</th>
            <th className="num">Temp (°C)</th>
            <th className="num">Indice</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={7} className="table-empty">Sin datos. Inicia el robot o activa el modo simulacion.</td>
            </tr>
          ) : (
            rows.map((m) => (
              <tr key={m.index}>
                <td>{m.group}</td>
                <td className="mono">{m.name}</td>
                <td className="num mono">{m.q_deg.toFixed(2)}</td>
                <td className="num mono">{m.dq.toFixed(4)}</td>
                <td className="num mono">{m.tau_est.toFixed(4)}</td>
                <td className={`num mono temp-cell ${tempClass(m.temperature)}`}>{m.temperature}</td>
                <td className="num mono">{m.index}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

export default memo(MotorsTable)

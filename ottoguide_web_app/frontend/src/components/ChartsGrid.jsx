import { useMemo, useState } from 'react'
import TimeSeriesChart from './charts/TimeSeriesChart.jsx'

// Paleta para curvas por motor / celda.
const PALETTE = [
  '#60A5FA', '#F472B6', '#34D399', '#FBBF24', '#A78BFA', '#22D3EE',
  '#FB7185', '#4ADE80', '#FCD34D', '#818CF8', '#2DD4BF', '#F59E0B',
  '#38BDF8', '#A3E635', '#FB923C', '#E879F9', '#5EEAD4', '#93C5FD',
  '#FCA5A5', '#86EFAC', '#FDE047', '#C4B5FD', '#67E8F9', '#F0ABFC',
  '#7DD3FC', '#BEF264', '#FDBA74', '#D8B4FE', '#99F6E4',
]

const CHART_DEFS = [
  { key: 'angle', label: 'Angulo por motor' },
  { key: 'temp', label: 'Temperatura motores' },
  { key: 'current', label: 'Corriente sistema' },
  { key: 'voltage', label: 'Tension sistema' },
  { key: 'soc', label: 'Carga bateria (SOC)' },
  { key: 'cells', label: 'Tension de celdas' },
]

// Construye filas {t, ...valores} a partir del historial de frames.
function buildRows(history, valueFor) {
  if (!history.length) return []
  const t0 = history[0].timestamp
  return history.map((f) => {
    const row = { t: +(f.timestamp - t0).toFixed(1) }
    valueFor(f, row)
    return row
  })
}

export default function ChartsGrid({ history }) {
  const [visible, setVisible] = useState(
    Object.fromEntries(CHART_DEFS.map((c) => [c.key, true]))
  )

  const motors = history.length ? history[history.length - 1].motors : []
  const groups = useMemo(() => [...new Set(motors.map((m) => m.group))], [motors])
  const [group, setGroup] = useState('')
  const activeGroup = group && groups.includes(group) ? group : groups[0] || ''

  const toggle = (k) => setVisible((v) => ({ ...v, [k]: !v[k] }))

  // --- Datos por grafico ---
  const angleMotors = useMemo(
    () => motors.filter((m) => m.group === activeGroup),
    [motors, activeGroup]
  )
  const angleSeries = angleMotors.map((m, i) => ({
    key: m.name, name: m.name, color: PALETTE[i % PALETTE.length],
  }))
  const angleData = useMemo(
    () => buildRows(history, (f, row) => {
      f.motors.forEach((m) => { if (m.group === activeGroup) row[m.name] = m.q_deg })
    }),
    [history, activeGroup]
  )

  const tempSeries = motors.map((m, i) => ({
    key: m.name, name: m.name, color: PALETTE[i % PALETTE.length],
  }))
  const tempData = useMemo(
    () => buildRows(history, (f, row) => {
      f.motors.forEach((m) => { row[m.name] = m.temperature })
    }),
    [history]
  )

  const currentData = useMemo(
    () => buildRows(history, (f, row) => { row.A = f.power_a }), [history]
  )
  const voltageData = useMemo(
    () => buildRows(history, (f, row) => { row.V = f.power_v }), [history]
  )
  const socData = useMemo(
    () => buildRows(history, (f, row) => { row.SOC = f.bms?.soc ?? null }), [history]
  )
  const cellsData = useMemo(
    () => buildRows(history, (f, row) => {
      (f.bms?.cell_vol || []).forEach((mv, i) => { row[`Celda ${i + 1}`] = mv })
    }),
    [history]
  )
  const cellCount = motors.length && history.length
    ? (history[history.length - 1].bms?.cell_vol?.length || 0) : 6
  const cellSeries = Array.from({ length: cellCount }, (_, i) => ({
    key: `Celda ${i + 1}`, name: `Celda ${i + 1}`, color: PALETTE[i % PALETTE.length],
  }))

  return (
    <div className="charts-panel">
      <div className="charts-toolbar">
        <span className="toolbar-label">Graficos:</span>
        {CHART_DEFS.map((c) => (
          <label key={c.key} className="check">
            <input type="checkbox" checked={visible[c.key]} onChange={() => toggle(c.key)} />
            {c.label}
          </label>
        ))}
        {visible.angle && groups.length > 0 && (
          <span className="group-select">
            <span className="toolbar-label">Grupo (angulos):</span>
            <select value={activeGroup} onChange={(e) => setGroup(e.target.value)}>
              {groups.map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
          </span>
        )}
      </div>

      {history.length === 0 ? (
        <div className="charts-empty">Sin datos todavia. Inicia el robot o activa el modo simulacion.</div>
      ) : (
        <div className="charts-grid">
          {visible.angle && (
            <TimeSeriesChart title={`Angulo por motor — ${activeGroup} (°)`} data={angleData} series={angleSeries} unit="°" showLegend />
          )}
          {visible.temp && (
            <TimeSeriesChart
              title="Temperatura de motores (°C)" data={tempData} series={tempSeries}
              refLines={[{ y: 40, color: '#FACC15' }, { y: 60, color: '#EF4444' }]}
            />
          )}
          {visible.current && (
            <TimeSeriesChart title="Corriente del sistema (A)" data={currentData}
              series={[{ key: 'A', name: 'Corriente', color: '#60A5FA' }]} />
          )}
          {visible.voltage && (
            <TimeSeriesChart title="Tension del sistema (V)" data={voltageData}
              series={[{ key: 'V', name: 'Tension', color: '#F472B6' }]}
              refLines={[{ y: 27.5, color: '#5b6b8a' }]} />
          )}
          {visible.soc && (
            <TimeSeriesChart title="Carga de bateria (%)" data={socData}
              series={[{ key: 'SOC', name: 'SOC', color: '#34D399' }]}
              yDomain={[0, 100]} refLines={[{ y: 20, color: '#EF4444' }]} />
          )}
          {visible.cells && (
            <TimeSeriesChart title="Tension de celdas (mV)" data={cellsData} series={cellSeries} showLegend
              refLines={[{ y: 3500, color: '#5b6b8a' }]} />
          )}
        </div>
      )}
    </div>
  )
}

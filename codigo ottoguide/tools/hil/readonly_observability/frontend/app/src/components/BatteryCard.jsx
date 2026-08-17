import { BatteryMedium } from 'lucide-react'
import MetricCard, { MetricRow } from './MetricCard.jsx'

// C3/C4: la card de Bateria consume SOLO el contrato canonico del BMS
// (soc, soh, voltage_v, current_a, temperature_c[], cell_vol_v[], cycle). Se muestra solo con
// BMS validado (availability.bms). Nunca se etiquetan crudos como V/A ni se rellenan ceros.
const f = (n, d) => (typeof n === 'number' ? n.toFixed(d) : '—')

export default function BatteryCard({ frame }) {
  const bms = frame?.bms || null
  const avail = frame?.availability || {}
  const notAvailable = !(bms && avail.bms === true)
  const temps = Array.isArray(bms?.temperature_c) && bms.temperature_c.length
    ? bms.temperature_c.map((t) => f(t, 1)).join(', ') : '—'
  const cells = Array.isArray(bms?.cell_vol_v) && bms.cell_vol_v.length
    ? bms.cell_vol_v.map((c) => f(c, 3)).join(', ') : '—'
  return (
    <MetricCard title="Bateria" icon={<BatteryMedium size={18} />} notAvailable={notAvailable}>
      <MetricRow label="Carga (SOC)" value={f(bms?.soc, 1)} unit="%" />
      <MetricRow label="Salud (SOH)" value={f(bms?.soh, 1)} unit="%" />
      <MetricRow label="Tension" value={f(bms?.voltage_v, 2)} unit="V" />
      <MetricRow label="Corriente" value={f(bms?.current_a, 2)} unit="A" />
      <MetricRow label="Ciclos" value={bms?.cycle ?? '—'} />
      <MetricRow label="Temp" value={temps} unit="°C" />
      <MetricRow label="Celdas" value={cells} unit="V" />
    </MetricCard>
  )
}

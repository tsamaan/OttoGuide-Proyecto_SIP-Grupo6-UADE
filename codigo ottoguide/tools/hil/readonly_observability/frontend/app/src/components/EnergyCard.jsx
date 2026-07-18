import { Zap } from 'lucide-react'
import MetricCard, { MetricRow } from './MetricCard.jsx'

// C3/C4: la card de Energia consume el contrato canonico del BMS (voltage_v/current_a/power_w).
// Solo se muestra con availability.energy (BMS validado). power_w llega calculado del bridge
// (voltage_v * current_a, con signo); si faltara, se deriva localmente. Sin dato -> null.
export default function EnergyCard({ frame }) {
  const bms = frame?.bms || {}
  const avail = frame?.availability || {}
  const v = typeof bms.voltage_v === 'number' ? bms.voltage_v : frame?.power_v
  const a = typeof bms.current_a === 'number' ? bms.current_a : frame?.power_a
  const notAvailable = !(avail.energy === true)
  const w = typeof bms.power_w === 'number'
    ? bms.power_w
    : (typeof v === 'number' && typeof a === 'number' ? v * a : null)
  return (
    <MetricCard title="Energia" icon={<Zap size={18} />} notAvailable={notAvailable}>
      <MetricRow label="Tension" value={typeof v === 'number' ? v.toFixed(2) : '—'} unit="V" />
      <MetricRow label="Corriente" value={typeof a === 'number' ? a.toFixed(2) : '—'} unit="A" />
      <MetricRow label="Potencia" value={typeof w === 'number' ? w.toFixed(1) : '—'} unit="W" />
    </MetricCard>
  )
}

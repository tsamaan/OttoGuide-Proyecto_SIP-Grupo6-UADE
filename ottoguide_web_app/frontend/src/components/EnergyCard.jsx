import { Zap } from 'lucide-react'
import MetricCard, { MetricRow } from './MetricCard.jsx'

export default function EnergyCard({ frame, mockMode }) {
  const v = frame?.power_v
  const a = frame?.power_a
  const w = v != null && a != null ? (v * a).toFixed(1) : '—'
  return (
    <MetricCard title="Energia" icon={<Zap size={18} />} mockMode={mockMode} notAvailable={!mockMode}>
      <MetricRow label="Voltaje" value={v != null ? v.toFixed(1) : '—'} unit="V" />
      <MetricRow label="Corriente" value={a != null ? a.toFixed(2) : '—'} unit="A" />
      <MetricRow label="Potencia" value={w} unit="W" />
    </MetricCard>
  )
}

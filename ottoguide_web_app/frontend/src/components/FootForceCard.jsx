import { Footprints } from 'lucide-react'
import MetricCard, { MetricRow } from './MetricCard.jsx'

export default function FootForceCard({ frame }) {
  const ff = frame?.foot_force || [null, null, null, null]
  return (
    <MetricCard title="Fuerza en patas" icon={<Footprints size={18} />}>
      <MetricRow label="FR" value={ff[0] ?? '—'} />
      <MetricRow label="FL" value={ff[1] ?? '—'} />
      <MetricRow label="RR" value={ff[2] ?? '—'} />
      <MetricRow label="RL" value={ff[3] ?? '—'} />
    </MetricCard>
  )
}

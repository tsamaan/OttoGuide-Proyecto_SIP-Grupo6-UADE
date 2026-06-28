import { BatteryMedium } from 'lucide-react'
import MetricCard, { MetricRow } from './MetricCard.jsx'

export default function BatteryCard({ frame }) {
  const bms = frame?.bms || {}
  const ntc = bms.mcu_ntc?.length ? bms.mcu_ntc.join(', ') : '—'
  const cells = bms.cell_vol?.length ? bms.cell_vol.join(', ') : '—'
  return (
    <MetricCard title="Bateria" icon={<BatteryMedium size={18} />}>
      <MetricRow label="Carga" value={bms.soc ?? '—'} unit="%" />
      <MetricRow label="Corriente BMS" value={bms.current ?? '—'} unit="mA" />
      <MetricRow label="Temp NTC" value={ntc} unit="C" />
      <MetricRow label="Ciclos" value={bms.cycle ?? '—'} />
      <MetricRow label="Celdas" value={cells} unit="mV" />
    </MetricCard>
  )
}

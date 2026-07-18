import { memo } from 'react'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ReferenceLine, Legend,
} from 'recharts'

// Grafico de lineas en el tiempo, reutilizable.
// data: [{ t, [key]: value, ... }]
// series: [{ key, name, color }]
function TimeSeriesChart({ title, data, series, unit, yDomain, refLines = [], showLegend = false }) {
  return (
    <div className="chart-card">
      <h4 className="chart-title">{title}</h4>
      <div className="chart-area">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 6, right: 12, bottom: 4, left: -6 }}>
            <CartesianGrid stroke="#1F2A3C" strokeDasharray="3 3" />
            <XAxis
              dataKey="t"
              tick={{ fill: '#7E8AA0', fontSize: 11 }}
              stroke="#1F2A3C"
              tickFormatter={(v) => `${Math.round(v)}s`}
              minTickGap={28}
            />
            <YAxis
              tick={{ fill: '#7E8AA0', fontSize: 11 }}
              stroke="#1F2A3C"
              domain={yDomain || ['auto', 'auto']}
              width={46}
              unit={unit ? ` ${unit}` : ''}
            />
            <Tooltip
              contentStyle={{
                background: '#0E1422', border: '1px solid #25324A',
                borderRadius: 8, fontSize: 12,
              }}
              labelStyle={{ color: '#94A3B8' }}
              labelFormatter={(v) => `t = ${Number(v).toFixed(1)} s`}
              isAnimationActive={false}
            />
            {refLines.map((r, i) => (
              <ReferenceLine key={i} y={r.y} stroke={r.color || '#5b6b8a'} strokeDasharray="4 4" />
            ))}
            {showLegend ? <Legend wrapperStyle={{ fontSize: 11 }} /> : null}
            {series.map((s) => (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.name}
                stroke={s.color}
                strokeWidth={1.6}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export default memo(TimeSeriesChart)

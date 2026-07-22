import { useMemo, useState } from 'react'
import TimeSeriesChart from './charts/TimeSeriesChart.jsx'
import { deriveChartsModel, sampleMotors, buildRows, seriesHasData } from './chartsModel.js'

// Paleta para curvas por motor / celda / eje.
const PALETTE = [
  '#60A5FA', '#F472B6', '#34D399', '#FBBF24', '#A78BFA', '#22D3EE',
  '#FB7185', '#4ADE80', '#FCD34D', '#818CF8', '#2DD4BF', '#F59E0B',
  '#38BDF8', '#A3E635', '#FB923C', '#E879F9', '#5EEAD4', '#93C5FD',
  '#FCA5A5', '#86EFAC', '#FDE047', '#C4B5FD', '#67E8F9', '#F0ABFC',
  '#7DD3FC', '#BEF264', '#FDBA74', '#D8B4FE', '#99F6E4',
]
const AXIS3 = ['#60A5FA', '#F472B6', '#34D399']

// NB-HIL-WEB-R0 (C4): se muestran solo las series con datos validos. Cada grafico se monta
// unicamente si su data tiene al menos una muestra numerica; series completamente
// null/undefined/sin muestras no se renderizan -> graficos vacios = 0.
export default function ChartsGrid({ history }) {
  const model = useMemo(() => deriveChartsModel(history), [history])
  const { safeHistory, motors, groups, richTelemetryAvailable } = model
  const [group, setGroup] = useState('')
  const activeGroup = group && groups.includes(group) ? group : groups[0] || ''

  // --- por-motor del grupo activo: angulo, velocidad angular, torque ---
  const groupMotors = useMemo(() => motors.filter((m) => m.group === activeGroup), [motors, activeGroup])
  const groupSeries = groupMotors.map((m, i) => ({ key: m.name, name: m.name, color: PALETTE[i % PALETTE.length] }))
  const mkGroupData = (field) => buildRows(safeHistory, (f, row) => {
    sampleMotors(f).forEach((m) => { if (m.group === activeGroup) row[m.name] = m[field] })
  })
  const angleData = useMemo(() => mkGroupData('q_deg'), [safeHistory, activeGroup])
  const velData = useMemo(() => mkGroupData('dq'), [safeHistory, activeGroup])
  const torqueData = useMemo(() => mkGroupData('tau_est'), [safeHistory, activeGroup])

  // --- temperatura de todos los motores ---
  const allMotorSeries = motors.map((m, i) => ({ key: m.name, name: m.name, color: PALETTE[i % PALETTE.length] }))
  const tempData = useMemo(() => buildRows(safeHistory, (f, row) => {
    sampleMotors(f).forEach((m) => { row[m.name] = m.temperature })
  }), [safeHistory])

  // --- IMU: rpy, acelerometro, giroscopio ---
  const imuRpyData = useMemo(() => buildRows(safeHistory, (f, row) => {
    const r = f.imu?.rpy_deg || []; row.roll = r[0]; row.pitch = r[1]; row.yaw = r[2]
  }), [safeHistory])
  const imuAccData = useMemo(() => buildRows(safeHistory, (f, row) => {
    const a = f.imu?.accelerometer || []; row.ax = a[0]; row.ay = a[1]; row.az = a[2]
  }), [safeHistory])
  const imuGyrData = useMemo(() => buildRows(safeHistory, (f, row) => {
    const g = f.imu?.gyroscope || []; row.gx = g[0]; row.gy = g[1]; row.gz = g[2]
  }), [safeHistory])

  // --- odometria: velocidad, posicion, yaw speed ---
  const odomVelData = useMemo(() => buildRows(safeHistory, (f, row) => {
    const v = f.odom?.velocity || []; row.vx = v[0]; row.vy = v[1]; row.yaw_speed = f.odom?.yaw_speed
  }), [safeHistory])
  const odomPosData = useMemo(() => buildRows(safeHistory, (f, row) => {
    const p = f.odom?.position || []; row.x = p[0]; row.y = p[1]; row.z = p[2]
  }), [safeHistory])

  // --- LiDAR puntos y frecuencias de topics ---
  const lidarData = useMemo(() => buildRows(safeHistory, (f, row) => { row.points = f.lidar?.points }), [safeHistory])
  const ratesData = useMemo(() => buildRows(safeHistory, (f, row) => {
    const r = f.rates || {}
    row.lowstate = r.lowstate_hz; row.odom = r.odom_hz; row.lf_odom = r.lf_odom_hz; row.lidar = r.lidar_hz
  }), [safeHistory])

  // --- BMS canonico (C4): voltage_v / current_a / power_w / soc / cell_vol_v ---
  const currentData = useMemo(() => buildRows(safeHistory, (f, row) => { row.A = f.bms?.current_a ?? null }), [safeHistory])
  const voltageData = useMemo(() => buildRows(safeHistory, (f, row) => { row.V = f.bms?.voltage_v ?? null }), [safeHistory])
  const powerData = useMemo(() => buildRows(safeHistory, (f, row) => { row.W = f.bms?.power_w ?? null }), [safeHistory])
  const socData = useMemo(() => buildRows(safeHistory, (f, row) => { row.SOC = f.bms?.soc ?? null }), [safeHistory])
  const cellsData = useMemo(() => buildRows(safeHistory, (f, row) => {
    (f.bms?.cell_vol_v || []).forEach((v, i) => { row[`Celda ${i + 1}`] = v })
  }), [safeHistory])
  const cellCount = safeHistory.length ? (safeHistory.at(-1).bms?.cell_vol_v?.length || 0) : 0
  const cellSeries = Array.from({ length: cellCount }, (_, i) => ({
    key: `Celda ${i + 1}`, name: `Celda ${i + 1}`, color: PALETTE[i % PALETTE.length],
  }))

  if (safeHistory.length === 0) {
    return (
      <div className="charts-panel">
        <div className="charts-empty">Sin datos todavia. Esperando frames del bridge…</div>
      </div>
    )
  }
  if (!richTelemetryAvailable) {
    return (
      <div className="charts-panel">
        <div className="charts-empty">
          Sin telemetria de motores en los frames recibidos; los graficos por motor permanecen ocultos.
        </div>
      </div>
    )
  }

  // Cada entrada se monta solo si tiene datos (C4: nada de graficos vacios).
  const groupKeys = groupSeries.map((s) => s.key)
  const charts = [
    seriesHasData(angleData, groupKeys) &&
      <TimeSeriesChart key="angle" title={`Angulo por motor — ${activeGroup} (°)`} data={angleData} series={groupSeries} unit="°" showLegend />,
    seriesHasData(velData, groupKeys) &&
      <TimeSeriesChart key="vel" title={`Velocidad angular — ${activeGroup} (rad/s)`} data={velData} series={groupSeries} showLegend />,
    seriesHasData(torqueData, groupKeys) &&
      <TimeSeriesChart key="torque" title={`Torque estimado — ${activeGroup} (N·m)`} data={torqueData} series={groupSeries} showLegend />,
    seriesHasData(tempData, allMotorSeries.map((s) => s.key)) &&
      <TimeSeriesChart key="temp" title="Temperatura de motores (°C)" data={tempData} series={allMotorSeries}
        refLines={[{ y: 40, color: '#FACC15' }, { y: 60, color: '#EF4444' }]} />,
    seriesHasData(imuRpyData, ['roll', 'pitch', 'yaw']) &&
      <TimeSeriesChart key="rpy" title="IMU roll / pitch / yaw (°)" data={imuRpyData} showLegend
        series={[{ key: 'roll', name: 'roll', color: AXIS3[0] }, { key: 'pitch', name: 'pitch', color: AXIS3[1] }, { key: 'yaw', name: 'yaw', color: AXIS3[2] }]} />,
    seriesHasData(imuAccData, ['ax', 'ay', 'az']) &&
      <TimeSeriesChart key="acc" title="Acelerometro (m/s²)" data={imuAccData} showLegend
        series={[{ key: 'ax', name: 'x', color: AXIS3[0] }, { key: 'ay', name: 'y', color: AXIS3[1] }, { key: 'az', name: 'z', color: AXIS3[2] }]} />,
    seriesHasData(imuGyrData, ['gx', 'gy', 'gz']) &&
      <TimeSeriesChart key="gyr" title="Giroscopio (rad/s)" data={imuGyrData} showLegend
        series={[{ key: 'gx', name: 'x', color: AXIS3[0] }, { key: 'gy', name: 'y', color: AXIS3[1] }, { key: 'gz', name: 'z', color: AXIS3[2] }]} />,
    seriesHasData(odomVelData, ['vx', 'vy', 'yaw_speed']) &&
      <TimeSeriesChart key="ovel" title="Velocidad odometrica (m/s, rad/s)" data={odomVelData} showLegend
        series={[{ key: 'vx', name: 'vx', color: AXIS3[0] }, { key: 'vy', name: 'vy', color: AXIS3[1] }, { key: 'yaw_speed', name: 'yaw', color: AXIS3[2] }]} />,
    seriesHasData(odomPosData, ['x', 'y', 'z']) &&
      <TimeSeriesChart key="opos" title="Posicion odometrica (m)" data={odomPosData} showLegend
        series={[{ key: 'x', name: 'x', color: AXIS3[0] }, { key: 'y', name: 'y', color: AXIS3[1] }, { key: 'z', name: 'z', color: AXIS3[2] }]} />,
    seriesHasData(lidarData, ['points']) &&
      <TimeSeriesChart key="lidar" title="Puntos LiDAR" data={lidarData} series={[{ key: 'points', name: 'puntos', color: '#22D3EE' }]} />,
    seriesHasData(ratesData, ['lowstate', 'odom', 'lf_odom', 'lidar']) &&
      <TimeSeriesChart key="rates" title="Frecuencias de topics (Hz)" data={ratesData} showLegend
        series={[{ key: 'lowstate', name: 'lowstate', color: PALETTE[0] }, { key: 'odom', name: 'odom', color: PALETTE[1] }, { key: 'lf_odom', name: 'lf_odom', color: PALETTE[2] }, { key: 'lidar', name: 'lidar', color: PALETTE[3] }]} />,
    seriesHasData(currentData, ['A']) &&
      <TimeSeriesChart key="cur" title="Corriente del sistema (A)" data={currentData} series={[{ key: 'A', name: 'Corriente', color: '#60A5FA' }]} />,
    seriesHasData(voltageData, ['V']) &&
      <TimeSeriesChart key="volt" title="Tension del pack (V)" data={voltageData} series={[{ key: 'V', name: 'Tension', color: '#F472B6' }]} />,
    seriesHasData(powerData, ['W']) &&
      <TimeSeriesChart key="power" title="Potencia (W)" data={powerData} series={[{ key: 'W', name: 'Potencia', color: '#FBBF24' }]} />,
    seriesHasData(socData, ['SOC']) &&
      <TimeSeriesChart key="soc" title="Carga de bateria (%)" data={socData} series={[{ key: 'SOC', name: 'SOC', color: '#34D399' }]} yDomain={[0, 100]} />,
    cellSeries.length && seriesHasData(cellsData, cellSeries.map((s) => s.key)) &&
      <TimeSeriesChart key="cells" title="Tension de celdas (V)" data={cellsData} series={cellSeries} showLegend />,
  ].filter(Boolean)

  return (
    <div className="charts-panel">
      <div className="charts-toolbar">
        {groups.length > 0 && (
          <span className="group-select">
            <span className="toolbar-label">Grupo (motores):</span>
            <select value={activeGroup} onChange={(e) => setGroup(e.target.value)}>
              {groups.map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
          </span>
        )}
        <span className="toolbar-label">{charts.length} graficos con datos</span>
      </div>
      <div className="charts-grid">{charts}</div>
    </div>
  )
}

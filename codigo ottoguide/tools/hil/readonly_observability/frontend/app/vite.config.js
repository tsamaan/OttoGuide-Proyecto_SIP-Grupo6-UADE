import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import fs from 'node:fs'

// NB-HIL-WEB-R0: el front se sirve en 127.0.0.1:5173 (FASE Q). host:127.0.0.1 lo mantiene
// solo local (no expuesto en la red).
//
// WEB-HIL-R1B (FASE C2): el perfil de deployment (real|replay) queda HORNEADO en el bundle
// via VITE_DEPLOYMENT_PROFILE (ver src/config.js), asi que un build 'real' y un build
// 'replay' NO pueden compartir directorio de salida sin que uno pise al otro (mismo layout
// de fuente -> mismo nombre de asset generado, y el ganador silencioso seria arbitrario).
// Cada modo escribe a su propio outDir (dist-real/ o dist-replay/), y 'emptyOutDir' solo
// vacia ESE directorio, nunca el del otro perfil.
//
// Bug encontrado y corregido en este checkpoint (R1B): Vite SOLO autocarga '.env.<mode>'
// (sin sufijo). Este repo versiona '.env.real.example'/'.env.replay.example' (sin
// secretos: solo flags de perfil y una URL loopback fija) para no versionar archivos
// '.env.*' por convencion, pero como ninguno matcheaba el nombre exacto que Vite busca,
// 'import.meta.env.VITE_DEPLOYMENT_PROFILE' quedaba SIEMPRE undefined en ambos builds ->
// 'resolveDeploymentConfig' caia a 'development' en los dos, y los bundles 'real' y
// 'replay' resultaban byte-identicos (verificado: mismo SHA-256). Se corrige leyendo
// manualmente el '.env.<mode>' local si existe (override de operador, no versionado) y si
// no, el '.env.<mode>.example' versionado como fuente de verdad, e inyectando el resultado
// via 'define' -- asi el valor SIEMPRE queda horneado correctamente, sin depender de un
// paso manual de copiar archivos antes de buildear.
function readDotEnv(filePath) {
  if (!fs.existsSync(filePath)) return {}
  const out = {}
  for (const line of fs.readFileSync(filePath, 'utf-8').split(/\r?\n/)) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const eq = trimmed.indexOf('=')
    if (eq === -1) continue
    const key = trimmed.slice(0, eq).trim()
    const value = trimmed.slice(eq + 1).trim()
    if (key.startsWith('VITE_')) out[key] = value
  }
  return out
}

export default defineConfig(({ mode }) => {
  const appDir = path.dirname(fileURLToPath(import.meta.url))
  const exampleEnv = readDotEnv(path.join(appDir, `.env.${mode}.example`))
  const localEnv = readDotEnv(path.join(appDir, `.env.${mode}`))
  const effective = { ...exampleEnv, ...localEnv }
  const defineEnv = Object.fromEntries(
    Object.entries(effective).map(([k, v]) => [`import.meta.env.${k}`, JSON.stringify(v)])
  )
  return {
    plugins: [react()],
    server: { host: '127.0.0.1', port: 5173, strictPort: true },
    preview: { host: '127.0.0.1', port: 5173, strictPort: true },
    build: { outDir: mode === 'replay' ? '../dist-replay' : '../dist-real', emptyOutDir: true },
    define: defineEnv,
  }
})

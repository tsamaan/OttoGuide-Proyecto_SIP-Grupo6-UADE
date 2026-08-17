import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// El front corre en el puerto 3001. host:true lo hace accesible en la red local.
export default defineConfig({
  plugins: [react()],
  server: { port: 3001, host: true, strictPort: true },
  preview: { port: 3001, host: true, strictPort: true },
})

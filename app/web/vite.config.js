import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Dev: http://localhost:5173. /api, /clips and /mock go to the app backend (python server.py, port 8000).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    proxy: {
      '/api': 'http://localhost:8000',
      '/clips': 'http://localhost:8000',
      '/mock': { target: 'http://localhost:8000', ws: true },
    },
  },
})

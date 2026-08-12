import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

// BACKEND_PLAN.md §5.1: assets are served from disk by the backend, no CDN.
// `npm run build` writes straight into backend/static so `app.mount("/", StaticFiles(...))`
// in backend/app.py picks it up with no extra copy step.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: fileURLToPath(new URL('../backend/static', import.meta.url)),
    emptyOutDir: true,
  },
  server: {
    // `npm run dev` proxies API calls to the FastAPI service (BIND_HOST = 127.0.0.1,
    // per DC-1/NFR-S2) so the dev server never needs its own CORS handling.
    // 8420 is backend/__main__.py's default --port; override via VITE_BACKEND_PORT
    // if you started the service with a different --port.
    proxy: {
      '/health': `http://127.0.0.1:${process.env.VITE_BACKEND_PORT || 8420}`,
      '/runs': `http://127.0.0.1:${process.env.VITE_BACKEND_PORT || 8420}`,
    },
  },
})

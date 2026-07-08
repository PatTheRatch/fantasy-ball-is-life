import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Listen on all interfaces (IPv4) so cloudflared can reach `127.0.0.1:5173` — default `localhost`
    // often binds IPv6-only and causes “502 Unable to reach the origin service”.
    host: true,
    port: 5173,
    // Quick tunnels use a random *.trycloudflare.com Host header; allow any host in dev only.
    allowedHosts: true,
    // Same-origin `/api/*` → FastAPI (no CORS issues in dev). Set VITE_API_BASE=/api in .env
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,
        // Default proxy timeouts are short; slow ESPN calls otherwise surface as 502 Bad Gateway
        timeout: 300_000,
        proxyTimeout: 300_000,
        rewrite: (path) => path.replace(/^\/api/, '') || '/',
      },
    },
  },
})

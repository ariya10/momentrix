import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const backend = process.env.MOMENTRIX_DEV_API || 'http://127.0.0.1:8000'
export default defineConfig({
  base: '/studio/',
  plugins: [react(), tailwindcss()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy: { '/api': backend } },
  test: { environment: 'jsdom', include: ['src/**/*.test.{ts,tsx}'], globals: true }
})

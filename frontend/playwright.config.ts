import { existsSync } from 'node:fs'
import { defineConfig } from '@playwright/test'

const edge = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const studio = new URL(process.env.MOMENTRIX_E2E_URL || 'http://127.0.0.1:5173/studio/')

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: {
    baseURL: studio.origin,
    headless: true,
    launchOptions: existsSync(edge) ? { executablePath: edge, args: ['--no-sandbox'] } : undefined,
  },
  webServer: studio.port === '5173' ? {
    command: 'npm run dev -- --host 127.0.0.1',
    url: 'http://127.0.0.1:5173/studio/',
    reuseExistingServer: true,
  } : undefined,
})

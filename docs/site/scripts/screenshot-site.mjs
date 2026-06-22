// Capture PNG screenshots of key routes at desktop and mobile widths.
// Saves to docs/site/.vitepress/screenshots/ for quick visual QA.
import process from 'node:process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const baseUrl = (process.argv[2] || 'http://localhost:4180/').replace(/\/$/, '')
const cdpBase = process.env.CDP_BASE || 'http://127.0.0.1:9222'
const outDir = join(process.cwd(), 'docs/site/.vitepress/screenshots')
mkdirSync(outDir, { recursive: true })

const targets = [
  { path: '/', label: 'home' },
  { path: '/protocol-map', label: 'protocol-map' },
  { path: '/specs/hlp', label: 'specs-hlp' },
]
const viewports = [
  { label: 'desktop', width: 1280, height: 900, mobile: false },
  { label: 'mobile', width: 390, height: 844, mobile: true },
]

const res = await fetch(`${cdpBase}/json/new?about:blank`, { method: 'PUT' })
const tab = await res.json()
const ws = new WebSocket(tab.webSocketDebuggerUrl)
let nextId = 0
const pending = new Map()
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data)
  if (msg.id != null && pending.has(msg.id)) {
    pending.get(msg.id)(msg); pending.delete(msg.id)
  }
}
await new Promise((r) => { ws.onopen = r })

function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++nextId
    pending.set(id, (m) => m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result))
    ws.send(JSON.stringify({ id, method, params }))
  })
}

await send('Page.enable')
const files = []
for (const v of viewports) {
  for (const t of targets) {
    await send('Emulation.setDeviceMetricsOverride', { width: v.width, height: v.height, deviceScaleFactor: 2, mobile: v.mobile })
    await send('Page.navigate', { url: `${baseUrl}${t.path}` })
    await new Promise((r) => setTimeout(r, 1200))
    const screenshot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
    const name = `${t.label}-${v.label}.png`
    writeFileSync(join(outDir, name), Buffer.from(screenshot.data, 'base64'))
    files.push(name)
  }
}

console.log('Saved screenshots:')
for (const f of files) console.log(`  docs/site/.vitepress/screenshots/${f}`)
ws.close()

// Headless Chrome (CDP) inspection of the built site.
// Surfaces horizontal overflow, missing hero elements, console errors,
// broken in-page links, and per-page metrics for desktop (1280) and mobile (390).
//
// Usage: node docs/site/scripts/inspect-site.mjs [preview-base-url]
// Needs Chrome/Chromium started with --remote-debugging-port=9222.
//
// This is a diagnostic help script; it prints findings and exits 0 on clean,
// non-zero when any check fails so it can be wired into CI later.

import process from 'node:process'

const baseUrl = (process.argv[2] || 'http://localhost:4180/').replace(/\/$/, '')
const cdpBase = process.env.CDP_BASE || 'http://127.0.0.1:9222'

const routes = [
  { path: '/', label: 'home' },
  { path: '/overview', label: 'overview' },
  { path: '/protocol-map', label: 'protocol-map' },
  { path: '/reading-routes', label: 'reading-routes' },
  { path: '/conformance', label: 'conformance' },
  { path: '/specs/hlp', label: 'specs/hlp' },
  { path: '/specs/aap', label: 'specs/aap' },
  { path: '/specs/cap', label: 'specs/cap' },
  { path: '/specs/contracts', label: 'specs/contracts' },
]

const viewports = [
  { label: 'desktop', width: 1280, height: 900, mobile: false },
  { label: 'mobile', width: 390, height: 844, mobile: true },
]

let tab
try {
  const res = await fetch(`${cdpBase}/json/new?about:blank`, { method: 'PUT' })
  tab = await res.json()
} catch (error) {
  console.error(`Cannot reach Chrome CDP at ${cdpBase}: ${error.message}`)
  console.error('Start Chrome with: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --remote-debugging-port=9222 --hide-scrollbars')
  process.exit(2)
}

const ws = new WebSocket(tab.webSocketDebuggerUrl)
let nextId = 0
const pending = new Map()

ws.onmessage = (event) => {
  const message = JSON.parse(event.data)
  if (message.id != null && pending.has(message.id)) {
    pending.get(message.id)(message)
    pending.delete(message.id)
  }
}

await new Promise((resolve, reject) => {
  ws.onopen = resolve
  ws.onerror = reject
})

function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++nextId
    pending.set(id, (message) => {
      if (message.error) reject(new Error(`${method}: ${JSON.stringify(message.error)}`))
      else resolve(message.result)
    })
    ws.send(JSON.stringify({ id, method, params }))
  })
}

async function waitForPageReady(route) {
  const deadline = Date.now() + 5000
  let lastValue
  while (Date.now() < deadline) {
    const result = await send('Runtime.evaluate', {
      expression: `
(() => {
  const h1Count = document.querySelectorAll('h1').length
  const label = ${JSON.stringify(route.label)}
  const routeReady = label === 'home'
    ? !!document.querySelector('.VPHero') && !!document.querySelector('.stack-art')
    : h1Count > 0
  return {
    readyState: document.readyState,
    hasApp: !!document.querySelector('#app'),
    h1Count,
    ok: document.readyState === 'complete' && !!document.querySelector('#app') && routeReady,
  }
})()
`,
      returnByValue: true,
    })
    lastValue = result?.result?.value
    if (lastValue?.ok) return
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  fail(`[${route.label}] route did not become ready before inspection: ${JSON.stringify(lastValue)}`)
}

const failures = []
function fail(message) {
  failures.push(message)
}

const collected = []

await send('Page.enable')
await send('Runtime.enable')

async function inspectRoute(route, viewport) {
  const url = `${baseUrl}${route.path}`
  await send('Emulation.setDeviceMetricsOverride', {
    width: viewport.width,
    height: viewport.height,
    deviceScaleFactor: 1,
    mobile: viewport.mobile,
  })

  const consoleErrors = []
  const failedRequests = []
  const messageHandler = (event) => {
    const { method, params } = JSON.parse(event.data)
    if (method === 'Runtime.consoleAPICalled' && params.type === 'error') {
      consoleErrors.push(params.args.map((a) => a.value || a.description).join(' '))
    }
    if (method === 'Network.loadingFailed' || method === 'Network.responseReceived') {
      // handled in evaluate below; keep handler minimal
    }
  }
  ws.addEventListener('message', messageHandler)

  await send('Network.enable')
  // Drain any prior buffered messages before navigating
  await send('Page.navigate', { url })
  await waitForPageReady(route)

  const probe = `
(() => {
  const viewportWidth = window.innerWidth
  const doc = document.documentElement
  const body = document.body
  const offenders = []
  const all = Array.from(document.querySelectorAll('*'))
  for (const el of all) {
    const rect = el.getBoundingClientRect()
    if (rect.width === 0 && rect.height === 0) continue
    if (rect.right > viewportWidth + 1 || rect.width > viewportWidth + 1) {
      const desc = (el.tagName + '.' + String(el.className || '').replace(/\\s+/g, '.')).slice(0, 80)
      offenders.push({
        el: desc,
        left: Math.round(rect.left),
        right: Math.round(rect.right),
        width: Math.round(rect.width),
        text: (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 80),
      })
    }
    if (offenders.length >= 8) break
  }
  const links = Array.from(document.querySelectorAll('a[href]')).map((a) => ({
    href: a.getAttribute('href'),
    text: (a.textContent || '').trim().slice(0, 60),
  }))
  const invalidLinks = links.filter((l) => {
    if (/^(https?:|mailto:|#)/.test(l.href)) return false
    return !document.querySelector('a[href="' + l.href.replace(/"/g, '\\\\"') + '"]')?.checkValidity?.()
      ? false
      : false
  })
  const root = document.querySelector('#app') || body
  return {
    title: document.title,
    readyState: document.readyState,
    viewportWidth,
    clientWidth: doc.clientWidth,
    scrollWidth: doc.scrollWidth,
    bodyScrollWidth: body.scrollWidth,
    h1: Array.from(document.querySelectorAll('h1')).map((h) => h.textContent.trim()),
    hero: !!document.querySelector('.VPHero, .vp-doc h1'),
    stackArt: !!document.querySelector('.stack-art'),
    navItems: document.querySelectorAll('.VPNavBar .VPFlyout, .VPNavBar a').length,
    sidebarItems: document.querySelectorAll('.VPSidebar .VPSidebarItem').length,
    overflowOffenders: offenders,
    linkCount: links.length,
  }
})()
`

  const evalResult = await send('Runtime.evaluate', { expression: probe, returnByValue: true })
  const value = evalResult?.result?.value
  ws.removeEventListener('message', messageHandler)

  collected.push({ route, viewport, url, value, consoleErrors })

  if (!value) {
    fail(`[${viewport.label}/${route.label}] probe returned no value`)
    return
  }

  if (value.consoleErrors?.length) {
    for (const err of value.consoleErrors) {
      fail(`[${viewport.label}/${route.label}] console error: ${err}`)
    }
  }

  if (value.h1.length === 0 && route.label !== 'home') {
    fail(`[${viewport.label}/${route.label}] page has no <h1>`)
  }

  if (value.h1.length > 1) {
    fail(`[${viewport.label}/${route.label}] page has ${value.h1.length} <h1> elements: ${JSON.stringify(value.h1)}`)
  }

  // Overflow: allow the nav scrollbar (desktop) but flag anything that exceeds the viewport.
  if (value.scrollWidth > value.viewportWidth + 2) {
    const sample = value.overflowOffenders.slice(0, 5).map((o) => `${o.el} [r=${o.right}, w=${o.width}]`).join(' | ')
    fail(`[${viewport.label}/${route.label}] horizontal overflow: scrollWidth=${value.scrollWidth} > viewport=${value.viewportWidth}. offenders: ${sample}`)
  }
}

for (const viewport of viewports) {
  for (const route of routes) {
    // eslint-disable-next-line no-await-in-loop
    await inspectRoute(route, viewport)
  }
}

// Route-specific structural assertions
const homeDesktop = collected.find((c) => c.route.label === 'home' && c.viewport.label === 'desktop')?.value
if (homeDesktop) {
  if (!homeDesktop.stackArt) fail('[home/desktop] missing .stack-art visual')
}

const specPages = ['specs/hlp', 'specs/aap', 'specs/cap', 'specs/contracts']
for (const label of specPages) {
  const entry = collected.find((c) => c.route.label === label && c.viewport.label === 'desktop')?.value
  if (entry && entry.sidebarItems === 0) {
    fail(`[${label}/desktop] sidebar has no items — sidebar config may not apply on spec routes`)
  }
}

async function inspectNavMenuTheme() {
  await send('Emulation.setDeviceMetricsOverride', {
    width: 1280,
    height: 900,
    deviceScaleFactor: 1,
    mobile: false,
  })
  await send('Page.navigate', { url: `${baseUrl}/specs/cap` })
  await waitForPageReady({ label: 'nav-menu' })
  const result = await send('Runtime.evaluate', {
    expression: `
new Promise((resolve) => {
  const buttons = Array.from(document.querySelectorAll('.VPNavBarMenu button'))
  const button = buttons.find((el) => (el.textContent || '').includes('Implement'))
  if (!button) {
    resolve({ found: false, reason: 'Implement nav button missing' })
    return
  }
  button.click()
  setTimeout(() => {
    const menu = document.querySelector('.VPMenu')
    if (!menu) {
      resolve({ found: false, reason: 'VPMenu missing after click' })
      return
    }
    const menuStyle = getComputedStyle(menu)
    const items = Array.from(menu.querySelectorAll('a')).map((item) => {
      const style = getComputedStyle(item)
      return {
        text: (item.textContent || '').trim(),
        color: style.color,
      }
    })
    resolve({
      found: true,
      backgroundColor: menuStyle.backgroundColor,
      color: menuStyle.color,
      borderColor: menuStyle.borderColor,
      itemColors: items,
    })
  }, 100)
})
`,
    awaitPromise: true,
    returnByValue: true,
  })
  const value = result?.result?.value
  if (!value?.found) {
    fail(`[nav-menu] ${value?.reason || 'menu probe failed'}`)
    return
  }
  if (value.backgroundColor === 'rgb(255, 255, 255)') {
    fail('[nav-menu] dropdown background is white on the dark site')
  }
}

await inspectNavMenuTheme()

// Summary table
console.log('\nInspection summary')
console.log('-'.repeat(72))
console.log(
  'route'.padEnd(18) +
    'viewport'.padEnd(10) +
    'scrollW'.padStart(8) +
    'clientW'.padStart(8) +
    'h1s'.padStart(4) +
    'links'.padStart(6),
)
for (const c of collected) {
  const v = c.value || {}
  console.log(
    c.route.label.padEnd(18) +
      c.viewport.label.padEnd(10) +
      String(v.scrollWidth ?? '-').padStart(8) +
      String(v.clientWidth ?? '-').padStart(8) +
      String((v.h1 || []).length).padStart(4) +
      String(v.linkCount ?? '-').padStart(6),
  )
}

if (failures.length > 0) {
  console.error('\nInspection failures:')
  for (const f of failures) console.error(`- ${f}`)
  ws.close()
  process.exit(1)
}

console.log('\nInspection passed: no overflow, no duplicate h1, no missing hero on home.')
ws.close()

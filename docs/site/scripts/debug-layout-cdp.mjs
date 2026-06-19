const cdpBase = process.env.CDP_BASE || 'http://127.0.0.1:9223'
const targetUrl = process.argv[2] || 'http://localhost:4174/loops/'

const target = await fetch(`${cdpBase}/json/new?${encodeURIComponent(targetUrl)}`, {
  method: 'PUT',
}).then((response) => response.json())

const ws = new WebSocket(target.webSocketDebuggerUrl)
let id = 0
const pending = new Map()

ws.onmessage = (event) => {
  const message = JSON.parse(event.data)
  if (message.id && pending.has(message.id)) {
    pending.get(message.id)(message)
    pending.delete(message.id)
  }
}

await new Promise((resolve) => {
  ws.onopen = resolve
})

function send(method, params = {}) {
  return new Promise((resolve) => {
    const messageId = ++id
    pending.set(messageId, resolve)
    ws.send(JSON.stringify({ id: messageId, method, params }))
  })
}

await send('Emulation.setDeviceMetricsOverride', {
  width: 390,
  height: 844,
  deviceScaleFactor: 1,
  mobile: true,
})
await send('Page.enable')
await send('Runtime.enable')
await send('Page.navigate', { url: targetUrl })
await new Promise((resolve) => setTimeout(resolve, 2000))

const expression = `
(() => {
  const viewportWidth = window.innerWidth
  const elements = Array.from(document.querySelectorAll('*'))
  const wide = elements
    .map((element) => {
      const rect = element.getBoundingClientRect()
      return {
        tag: element.tagName,
        className: String(element.className || '').slice(0, 120),
        text: (element.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 90),
        left: Math.round(rect.left),
        right: Math.round(rect.right),
        width: Math.round(rect.width),
      }
    })
    .filter((item) => item.right > viewportWidth + 1 || item.width > viewportWidth + 1)
    .sort((a, b) => b.right - a.right)
    .slice(0, 30)

  return {
    href: location.href,
    viewportWidth,
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    bodyScrollWidth: document.body.scrollWidth,
    wide,
  }
})()
`

const result = await send('Runtime.evaluate', {
  expression,
  returnByValue: true,
})

console.log(JSON.stringify(result.result.result.value, null, 2))
ws.close()

import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import process from 'node:process'

const rootDir = process.cwd()
const siteDir = join(rootDir, 'docs/site')
const distDir = join(siteDir, '.vitepress/dist')
const sourceExtensions = new Set(['.css', '.json', '.md', '.mjs', '.svg', '.ts', '.yaml', '.yml'])
const cjkPattern = /[\u3400-\u9fff\uf900-\ufaff]/

const expectedRoutes = [
  'index.html',
  '404.html',
  'overview.html',
  'protocol-map.html',
  'reading-routes.html',
  'conformance.html',
  'specs/hlp.html',
  'specs/aap.html',
  'specs/cap.html',
  'specs/contracts.html',
]

const failures = []

function fail(message) {
  failures.push(message)
}

function assert(condition, message) {
  if (!condition) fail(message)
}

function readText(path) {
  return readFileSync(path, 'utf8')
}

function walkFiles(dir, shouldSkip = () => false) {
  const files = []

  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    const rel = relative(rootDir, path)
    if (shouldSkip(rel, path)) continue

    const stats = statSync(path)
    if (stats.isDirectory()) {
      files.push(...walkFiles(path, shouldSkip))
    } else if (stats.isFile()) {
      files.push(path)
    }
  }

  return files
}

function extensionOf(path) {
  const match = path.match(/\.[^.]+$/)
  return match ? match[0] : ''
}

function assertNoCjk(files, label) {
  for (const path of files) {
    const content = readText(path)
    assert(!cjkPattern.test(content), `${label} contains CJK text: ${relative(rootDir, path)}`)
  }
}

function expectedSitemapPath(route) {
  const basePath = process.env.BASE_PATH || '/'
  const cleanBase = basePath === '/' ? '' : basePath.replace(/\/$/, '')
  if (route === 'index.html') return `${cleanBase}/`
  return `${cleanBase}/${route.replace(/index\.html$/, '').replace(/\.html$/, '')}`
}

assert(existsSync(distDir), 'VitePress dist directory is missing. Run the site build before verification.')

if (existsSync(distDir)) {
  for (const route of expectedRoutes) {
    assert(existsSync(join(distDir, route)), `Missing built route: ${route}`)
  }

  const sourceFiles = walkFiles(siteDir, (rel) => {
    if (rel.startsWith('docs/site/.vitepress/dist')) return true
    if (rel.startsWith('docs/site/.vitepress/cache')) return true
    return false
  }).filter((path) => sourceExtensions.has(extensionOf(path)))

  const builtHtmlFiles = walkFiles(distDir).filter((path) => path.endsWith('.html'))

  assertNoCjk(sourceFiles, 'Site source')
  assertNoCjk(builtHtmlFiles, 'Rendered HTML')

  const homeHtml = readText(join(distDir, 'index.html'))
  assert(homeHtml.includes('property="og:title"'), 'Home page is missing og:title metadata.')
  assert(homeHtml.includes('property="og:description"'), 'Home page is missing og:description metadata.')
  assert(homeHtml.includes('property="og:image"'), 'Home page is missing og:image metadata.')
  assert(homeHtml.includes('name="twitter:card"'), 'Home page is missing Twitter card metadata.')
  assert(homeHtml.includes('rel="canonical"'), 'Home page is missing a canonical URL.')
  assert(homeHtml.includes('rel="stylesheet"'), 'Home page is missing a standard stylesheet link.')
  assert(!homeHtml.includes('rel="preload stylesheet"'), 'Home page uses preload stylesheet links that are not stable in static screenshot tools.')
  assert(!homeHtml.includes('as="style"'), 'Home page stylesheet links should not retain preload-only as="style" attributes.')
  assert(homeHtml.includes('class="stack-art"'), 'Home page is missing the HLP integration visual.')
  assert(homeHtml.includes('HLPHost'), 'Home page is missing the HLPHost SDK entry point.')
  assert(homeHtml.includes('AgentAdapter'), 'Home page is missing the AgentAdapter boundary.')
  assert(!homeHtml.includes('&lt;rect'), 'Home page appears to render an SVG as escaped code.')

  const protocolMapHtmlPath = join(distDir, 'protocol-map.html')
  if (existsSync(protocolMapHtmlPath)) {
    const protocolMapHtml = readText(protocolMapHtmlPath)
    assert(protocolMapHtml.includes('Integration Contracts'), 'Protocol map is missing the integration contracts section.')
    assert(protocolMapHtml.includes('CapabilityRef'), 'Protocol map is missing the CapabilityRef contract.')
    assert(protocolMapHtml.includes('TaskID'), 'Protocol map is missing the TaskID correlation contract.')
  }

  const robotsPath = join(distDir, 'robots.txt')
  assert(existsSync(robotsPath), 'robots.txt is missing from the built site.')
  if (existsSync(robotsPath)) {
    const robots = readText(robotsPath)
    assert(robots.includes('Sitemap:'), 'robots.txt is missing a Sitemap directive.')
  }

  const sitemapPath = join(distDir, 'sitemap.xml')
  assert(existsSync(sitemapPath), 'sitemap.xml is missing from the built site.')
  if (existsSync(sitemapPath)) {
    const sitemap = readText(sitemapPath)
    const sitemapRoutes = expectedRoutes.filter((r) => r !== '404.html')
    for (const route of sitemapRoutes) {
      assert(sitemap.includes(expectedSitemapPath(route)), `sitemap.xml is missing route: ${route}`)
    }
  }
}

if (failures.length > 0) {
  console.error('Site verification failed:')
  for (const failure of failures) {
    console.error(`- ${failure}`)
  }
  process.exit(1)
}

console.log('Site verification passed.')

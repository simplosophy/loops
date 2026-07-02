import { defineConfig } from 'vitepress'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'

const base = process.env.BASE_PATH || '/'
const normalizedBase = base.endsWith('/') ? base : `${base}/`
const siteUrl = (process.env.SITE_URL || 'https://loops-protocol.dev').replace(/\/$/, '')
const siteBaseUrl = new URL(normalizedBase, `${siteUrl}/`)

function absoluteSiteUrl(path = '') {
  return new URL(path.replace(/^\//, ''), siteBaseUrl).toString()
}

function pagePath(page: string) {
  const route = page.replace(/(^|\/)index\.md$/, '$1').replace(/\.md$/, '')
  return route.replace(/^\//, '')
}

export default defineConfig({
  base,
  lang: 'en-US',
  title: 'Human Loop Protocol',
  description:
    'An SDK and protocol for wrapping existing agent harnesses with accountable human interaction.',
  cleanUrls: true,
  srcDir: './',
  ignoreDeadLinks: false,

  head: [
    ['meta', { name: 'theme-color', content: '#101014' }],
    [
      'meta',
      {
        name: 'keywords',
        content:
          'Human Loop Protocol,HLP,agent harness,human interaction control plane,human loop,A2A,MCP,Agent Skills',
      },
    ],
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' }],
    ['link', { rel: 'apple-touch-icon', href: '/favicon.svg' }],
    ['link', { rel: 'mask-icon', href: '/favicon.svg', color: '#8B5CF6' }],
  ],

  sitemap: {
    hostname: absoluteSiteUrl(),
  },

  transformHead({ page, title, description }) {
    const canonical = absoluteSiteUrl(pagePath(page))
    const image = absoluteSiteUrl('og.svg')

    return [
      ['link', { rel: 'canonical', href: canonical }],
      ['meta', { property: 'og:title', content: title }],
      ['meta', { property: 'og:description', content: description }],
      ['meta', { property: 'og:type', content: 'website' }],
      ['meta', { property: 'og:url', content: canonical }],
      ['meta', { property: 'og:image', content: image }],
      ['meta', { property: 'og:image:type', content: 'image/svg+xml' }],
      ['meta', { name: 'twitter:card', content: 'summary_large_image' }],
      ['meta', { name: 'twitter:title', content: title }],
      ['meta', { name: 'twitter:description', content: description }],
      ['meta', { name: 'twitter:image', content: image }],
    ]
  },

  buildEnd(siteConfig) {
    writeFileSync(
      join(siteConfig.outDir, 'robots.txt'),
      `User-agent: *\nAllow: ${normalizedBase}\nSitemap: ${absoluteSiteUrl('sitemap.xml')}\n`,
    )
  },

  transformHtml(code) {
    return code
      .replace(/rel="preload stylesheet"/g, 'rel="stylesheet"')
      .replace(/(<link rel="stylesheet" href="[^"]+") as="style"/g, '$1')
  },

  search: {
    provider: 'local',
    options: {
      translations: {
        button: { buttonText: 'Search', buttonAriaLabel: 'Search' },
        modal: {
          noResultsText: 'No results found',
          resetButtonTitle: 'Reset search',
          footer: {
            selectText: 'to select',
            navigateText: 'to navigate',
            closeText: 'to close',
          },
        },
      },
    },
  },

  themeConfig: {
    siteTitle: 'HLP',
    logo: {
      light: '/logo.svg',
      dark: '/logo.svg',
    },

    nav: [
      { text: 'Overview', link: '/overview' },
      { text: 'HLP Spec', link: '/specs/hlp' },
      {
        text: 'Implement',
        items: [
          { text: 'Implementation Guide', link: '/reading-routes' },
          { text: 'HLP Conformance', link: '/conformance' },
          { text: 'Integration Contracts', link: '/specs/contracts' },
          { text: 'Integration Map', link: '/protocol-map' },
        ],
      },
      {
        text: 'Ecosystem Routes',
        items: [
          { text: 'L1 · Agent Protocols', link: '/specs/aap' },
          { text: 'L0 · Capability Protocols', link: '/specs/cap' },
        ],
      },
    ],

    sidebar: {
      '/': [
        {
          text: 'Start Here',
          collapsed: false,
          items: [
            { text: 'Overview', link: '/overview' },
            { text: 'HLP Specification', link: '/specs/hlp' },
            { text: 'Implementation Guide', link: '/reading-routes' },
            { text: 'HLP Conformance', link: '/conformance' },
          ],
        },
        {
          text: 'Integration',
          collapsed: false,
          items: [
            { text: 'Integration Map', link: '/protocol-map' },
            { text: 'Integration Contracts', link: '/specs/contracts' },
            { text: 'L1 · Agent Protocols', link: '/specs/aap' },
            { text: 'L0 · Capability Protocols', link: '/specs/cap' },
          ],
        },
      ],
    },

    footer: {
      message: 'Human Loop Protocol · HLP wraps existing harnesses with accountable human interaction',
      copyright: 'Draft protocol documentation. Version 0.2.0-draft.',
    },

    outline: {
      level: [2, 3],
      label: 'On this page',
    },

    docFooter: {
      prev: 'Previous',
      next: 'Next',
    },

    darkModeSwitchLabel: false,
    socialLinks: [
      { icon: 'github', link: 'https://github.com/simplosophy/loops' },
    ],

    sidebarMenuLabel: 'Menu',
    returnToTopLabel: 'Return to top',
    lastUpdated: {
      text: 'Last updated',
    },
  },

  lastUpdated: true,

  appearance: false,
})

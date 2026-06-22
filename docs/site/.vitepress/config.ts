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
  title: 'Loops Protocol Stack',
  description:
    'A three-layer protocol stack for human-loop work, agent delegation, and capability invocation.',
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
          'Loops Protocol Stack,HLP,AAP,CAP,human loop protocol,agent protocol,capability protocol',
      },
    ],
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
    siteTitle: 'Loops',
    logo: {
      light: '/logo.svg',
      dark: '/logo.svg',
    },

    nav: [
      { text: 'Overview', link: '/overview' },
      { text: 'Protocol Map', link: '/protocol-map' },
      {
        text: 'Implement',
        items: [
          { text: 'Implementation Guide', link: '/reading-routes' },
          { text: 'Conformance', link: '/conformance' },
          { text: 'Inter-layer Contracts', link: '/specs/contracts' },
        ],
      },
      {
        text: 'Specifications',
        items: [
          { text: 'HLP · Human Loop Protocol', link: '/specs/hlp' },
          { text: 'AAP · Agent-Agent Profile', link: '/specs/aap' },
          { text: 'CAP · Capability Profile', link: '/specs/cap' },
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
            { text: 'Protocol Map', link: '/protocol-map' },
            { text: 'Implementation Guide', link: '/reading-routes' },
            { text: 'Conformance', link: '/conformance' },
          ],
        },
        {
          text: 'Specifications',
          collapsed: false,
          items: [
            { text: 'L2 · HLP', link: '/specs/hlp' },
            { text: 'L1 · AAP', link: '/specs/aap' },
            { text: 'L0 · CAP', link: '/specs/cap' },
            { text: 'Inter-layer Contracts', link: '/specs/contracts' },
          ],
        },
      ],
    },

    footer: {
      message: 'Loops Protocol Stack · loop0 owns execution · loop1 owns interaction · loop2 owns coordination',
      copyright: 'Draft protocol documentation. Version 0.1.0-draft.',
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
      { icon: 'github', link: 'https://github.com/simplosophy/loop0' },
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

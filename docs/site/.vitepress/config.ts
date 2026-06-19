import { defineConfig } from 'vitepress'

const base = process.env.BASE_PATH || '/'

export default defineConfig({
  base,
  lang: 'en-US',
  title: 'Loops Protocol Stack',
  description:
    'A three-layer protocol stack for human-agent collaboration, agent delegation, and capability invocation.',
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
          'Loops Protocol Stack,HACP,AAP,CAP,human-agent collaboration,agent protocol,capability protocol',
      },
    ],
    ['meta', { property: 'og:title', content: 'Loops Protocol Stack' }],
    [
      'meta',
      {
        property: 'og:description',
        content:
          'The coordination layer for AI systems: HACP for human-agent work, AAP for agent delegation, and CAP for capabilities.',
      },
    ],
    ['meta', { property: 'og:type', content: 'website' }],
  ],

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
          { text: 'HACP · Human-Agent Collaboration', link: '/specs/hacp' },
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
            { text: 'Implementation Guide', link: '/reading-routes' },
            { text: 'Conformance', link: '/conformance' },
          ],
        },
        {
          text: 'Specifications',
          collapsed: false,
          items: [
            { text: 'L2 · HACP', link: '/specs/hacp' },
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

    darkModeSwitchLabel: 'Appearance',
    sidebarMenuLabel: 'Menu',
    returnToTopLabel: 'Return to top',
    lastUpdated: {
      text: 'Last updated',
    },
  },

  lastUpdated: true,
})

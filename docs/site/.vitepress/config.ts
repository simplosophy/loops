import { defineConfig } from 'vitepress'

// Loops Protocol Stack — VitePress configuration
// 风格延续 docs/intro.html：深色主题 + L0/L1/L2 三色 token

export default defineConfig({
  title: 'Loops Protocol Stack',
  description: 'AI 协作的 OSI 模型 — 三层协议、每层只解一个维度、层间靠显式契约咬合',

  // 干净 URL，无 .html 后缀
  cleanUrls: true,

  // 站点根目录（相对于 docs/site/）
  srcDir: './',

  // 原 spec 里的相对链接指向仓库内非站点文件（../plans/ ../architecture/），
  // 从 VitePress 视角是断链。忽略这类死链——它们在源 spec 里是正确的。
  ignoreDeadLinks: true,

  // 内置本地搜索
  search: {
    provider: 'local',
    options: {
      translations: {
        button: { buttonText: '搜索', buttonAriaLabel: '搜索' },
        modal: {
          noResultsText: '无法找到结果',
          resetButtonTitle: '清除查询',
          footer: { selectText: '选择', navigateText: '切换', closeText: '关闭' }
        }
      }
    }
  },

  themeConfig: {
    // 默认深色
    darkModeSwitchLabel: '主题',
    sidebarMenuLabel: '菜单',
    returnToTopLabel: '回到顶部',

    // 站点 logo / 标题
    siteTitle: 'Loops',

    nav: [
      { text: '指南', items: [
        { text: '为什么是协议栈', link: '/overview' },
        { text: '实现者阅读路线', link: '/reading-routes' },
      ]},
      { text: '协议规范', items: [
        { text: 'L2 · HACP', link: '/specs/hacp' },
        { text: 'L1 · AAP', link: '/specs/aap' },
        { text: 'L0 · CAP', link: '/specs/cap' },
      ]},
      { text: '参考', items: [
        { text: '层间契约速查', link: '/specs/contracts' },
      ]},
    ],

    sidebar: {
      '/': [
        {
          text: '指南',
          collapsed: false,
          items: [
            { text: '为什么是协议栈', link: '/overview' },
            { text: '实现者阅读路线', link: '/reading-routes' },
          ]
        },
        {
          text: '协议规范（按层）',
          collapsed: false,
          items: [
            {
              text: 'L2 · HACP — 人机协作',
              link: '/specs/hacp',
              // 侧边栏标记用主题色（HACP=紫）
            },
            {
              text: 'L1 · AAP — agent 间',
              link: '/specs/aap',
            },
            {
              text: 'L0 · CAP — 能力',
              link: '/specs/cap',
            },
          ]
        },
        {
          text: '参考',
          collapsed: false,
          items: [
            { text: '层间契约速查', link: '/specs/contracts' },
          ]
        },
      ]
    },

    socialLinks: [
      // 预留：github 等
    ],

    footer: {
      message: 'Loops Protocol Stack · loop0 owns execution / loop1 owns interaction / loop2 owns coordination'
    },

    outline: {
      level: [2, 3],
      label: '本页目录'
    },

    docFooter: {
      prev: '上一页',
      next: '下一页'
    },

    lastUpdated: {
      text: '最后更新'
    }
  },

  // 标记为对外发布的草稿
  lastUpdated: true,
})

import type { Theme } from 'vitepress'
import DefaultTheme from 'vitepress/theme'
import { h } from 'vue'
import NotFound from './NotFound.vue'
import './custom.css'

export default {
  extends: DefaultTheme,
  Layout: () => {
    // Inject our branded 404 into the default layout's not-found slot.
    return h(DefaultTheme.Layout, null, {
      'not-found': () => h(NotFound),
    })
  },
} satisfies Theme

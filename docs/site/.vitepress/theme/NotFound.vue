<script setup lang="ts">
import { onMounted, ref } from 'vue'

const redirectIn = ref(5)
let timer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  timer = setInterval(() => {
    redirectIn.value -= 1
    if (redirectIn.value <= 0) {
      if (timer) clearInterval(timer)
      window.location.href = '/'
    }
  }, 1000)
})
</script>

<template>
  <div class="not-found">
    <p class="code">404</p>
    <h1 class="title">Page not found</h1>
    <p class="desc">This URL does not match any Loops Protocol Stack page.</p>
    <p class="redirect">
      Redirecting to the
      <a href="/">home page</a>
      in {{ redirectIn }}s&hellip;
    </p>
  </div>
</template>

<style scoped>
.not-found {
  text-align: center;
  padding: 96px 24px;
  max-width: 640px;
  margin: 0 auto;
}
.code {
  font-size: 96px;
  font-weight: 800;
  background: var(--loops-grad);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  line-height: 1;
  margin: 0 0 16px;
  font-family: var(--vp-font-family-mono);
}
.title {
  font-size: 28px;
  margin: 0 0 12px;
  border-top: none !important;
  padding-top: 0 !important;
  letter-spacing: 0;
}
.desc {
  color: var(--vp-c-text-2);
  max-width: 480px;
  margin: 0 auto;
  line-height: 1.6;
}
.redirect {
  margin-top: 24px;
  font-size: 14px;
  color: var(--vp-c-text-2);
}
.redirect a {
  font-weight: 700;
  color: var(--link);
}
</style>

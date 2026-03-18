<script setup>
import { ref } from 'vue'
import UploadPanel from './components/UploadPanel.vue'
import ResultDashboard from './components/ResultDashboard.vue'
import { inferVideo } from './services/api'

const loading = ref(false)
const error = ref('')
const result = ref(null)

async function onSubmit(file) {
  loading.value = true
  error.value = ''

  try {
    result.value = await inferVideo(file)
  } catch (err) {
    if (err?.message === 'Network Error') {
      error.value = '网络连接失败：请确认后端服务已启动，并可访问 http://127.0.0.1:8000/health'
    } else if (err?.code === 'ECONNABORTED') {
      error.value = '请求超时：视频可能过大或推理耗时过长，请尝试更短视频后重试'
    } else {
      const message = err?.response?.data?.detail || err?.message || '识别失败'
      error.value = String(message)
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="app-bg">
    <main class="container">
      <header class="hero">
        <h1>微动作识别系统</h1>
        <p>前后端分离集成版本 · 离线视频识别 · 时序概率曲线 · 热力图</p>
      </header>

      <UploadPanel @submit="onSubmit" />

      <section v-if="loading" class="state-card">正在推理与生成可视化，请稍候...</section>
      <section v-else-if="error" class="state-card error">{{ error }}</section>
      <ResultDashboard v-else-if="result" :result="result" />
    </main>
  </div>
</template>

<style scoped>
.app-bg {
  min-height: 100vh;
  background:
    radial-gradient(circle at 20% 20%, rgba(255, 122, 89, 0.23), transparent 50%),
    radial-gradient(circle at 80% 0%, rgba(111, 214, 255, 0.2), transparent 45%),
    linear-gradient(180deg, #09121c 0%, #0d1723 48%, #101824 100%);
  padding: 24px 12px 40px;
}

.container {
  width: min(1040px, 100%);
  margin: 0 auto;
  display: grid;
  gap: 16px;
}

.hero {
  padding: 6px 2px;
}

h1 {
  margin: 0;
  font-size: clamp(1.8rem, 4vw, 2.8rem);
  letter-spacing: 0.03em;
}

p {
  color: var(--muted);
}

.state-card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 14px;
}

.state-card.error {
  border-color: rgba(255, 120, 120, 0.6);
  color: #ffd7d7;
}
</style>

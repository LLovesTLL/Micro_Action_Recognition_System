<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import UploadPanel from './components/UploadPanel.vue'
import ResultDashboard from './components/ResultDashboard.vue'
import { inferVideo, renderExpertVideo } from './services/api'

const loading = ref(false)
const exporting = ref(false)
const error = ref('')
const result = ref(null)
const uploadedFile = ref(null)

async function onSubmit(file) {
  loading.value = true
  error.value = ''
  uploadedFile.value = file

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

async function onExportExpertVideo() {
  if (!uploadedFile.value) {
    error.value = '缺少原始视频文件，请重新上传后再导出。'
    return
  }

  exporting.value = true
  error.value = ''
  try {
    const data = await renderExpertVideo(uploadedFile.value)
    if (!data?.local_download_url) {
      throw new Error('导出成功但未返回下载地址')
    }
    window.open(data.local_download_url, '_blank')
  } catch (err) {
    const message = err?.response?.data?.detail || err?.message || '导出失败'
    error.value = String(message)
  } finally {
    exporting.value = false
  }
}

function cleanupTempOnExit() {
  const url = '/api/v1/cleanup-temp'

  if (navigator.sendBeacon) {
    const blob = new Blob(['{}'], { type: 'application/json' })
    navigator.sendBeacon(url, blob)
    return
  }

  fetch(url, {
    method: 'POST',
    keepalive: true,
    headers: { 'Content-Type': 'application/json' },
    body: '{}'
  }).catch(() => {
    // Best-effort cleanup on exit.
  })
}

onMounted(() => {
  window.addEventListener('beforeunload', cleanupTempOnExit)
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', cleanupTempOnExit)
  cleanupTempOnExit()
})
</script>

<template>
  <div class="app-bg">
    <main class="container">
      <header class="hero">
        <h1>微动作识别系统</h1>
      </header>

      <section v-if="result" class="workspace split">
        <aside class="left-pane">
          <UploadPanel :initial-file="uploadedFile" @submit="onSubmit" />
        </aside>
        <section class="right-pane">
          <ResultDashboard
            :result="result"
            :exporting="exporting"
            @export-expert-video="onExportExpertVideo"
          />
        </section>
      </section>

      <section v-else class="workspace centered">
        <UploadPanel :initial-file="uploadedFile" @submit="onSubmit" />
      </section>

      <section v-if="loading" class="state-card">正在推理与生成可视化，请稍候...</section>
      <section v-else-if="error" class="state-card error">{{ error }}</section>
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
  width: min(1560px, 100%);
  margin: 0 auto;
  display: grid;
  gap: 12px;
}

.workspace {
  width: 100%;
}

.workspace.centered {
  display: grid;
  justify-items: center;
}

.workspace.centered > :first-child {
  width: min(920px, 100%);
}

.workspace.split {
  display: grid;
  gap: 12px;
  grid-template-columns: minmax(360px, 0.95fr) minmax(780px, 1.6fr);
  align-items: stretch;
}

.left-pane,
.right-pane {
  min-width: 0;
}

.left-pane {
  display: flex;
}

.left-pane :deep(.upload-panel) {
  width: 100%;
  height: 100%;
}

@media (max-width: 980px) {
  .workspace.split {
    grid-template-columns: 1fr;
  }
}

.hero {
  padding: 2px 2px;
  text-align: center;
}

h1 {
  margin: 0;
  font-size: clamp(1.8rem, 4vw, 2.8rem);
  letter-spacing: 0.03em;
}

.state-card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 14px;
  width: 100%;
  box-sizing: border-box;
}

.state-card.error {
  border-color: rgba(255, 120, 120, 0.6);
  color: #ffd7d7;
}
</style>

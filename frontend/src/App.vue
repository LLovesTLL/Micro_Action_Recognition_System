<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import UploadPanel from './components/UploadPanel.vue'
import ResultDashboard from './components/ResultDashboard.vue'
import {
  clearRenderJobs,
  createRenderExpertJob,
  deleteRenderJob,
  inferVideoChunked,
  listRenderJobs,
  pollRenderJobUntilDone
} from './services/api'

const loading = ref(false)
const exporting = ref(false)
const error = ref('')
const result = ref(null)
const uploadedFile = ref(null)
const uploadProgress = ref(0)
const loadingMessage = ref('')
const renderJobs = ref([])
const jobsLoading = ref(false)
const jobsClassFilter = ref('')
const jobsClearing = ref(false)

function upsertRenderJob(job) {
  if (!job?.job_id) return
  const idx = renderJobs.value.findIndex((j) => j.job_id === job.job_id)
  if (idx >= 0) {
    renderJobs.value[idx] = { ...renderJobs.value[idx], ...job }
  } else {
    renderJobs.value.unshift(job)
  }
}

async function refreshRenderJobs() {
  jobsLoading.value = true
  try {
    const data = await listRenderJobs({
      limit: 100,
      class_label: jobsClassFilter.value || undefined
    })
    renderJobs.value = Array.isArray(data?.items) ? data.items : []
  } catch {
    // no-op; avoid noisy errors for polling-style refresh
  } finally {
    jobsLoading.value = false
  }
}

async function onSubmit(file) {
  loading.value = true
  uploadProgress.value = 0
  loadingMessage.value = '正在分片上传视频...'
  error.value = ''
  uploadedFile.value = file

  try {
    result.value = await inferVideoChunked(file, (p) => {
      uploadProgress.value = p
      if (p < 1) {
        loadingMessage.value = `正在上传视频... ${(p * 100).toFixed(1)}%`
      } else {
        loadingMessage.value = '上传完成，正在执行推理...'
      }
    })
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
    uploadProgress.value = 0
    loadingMessage.value = ''
    loading.value = false
  }
}

async function onExportExpertVideo() {
  if (!uploadedFile.value) {
    error.value = '缺少原始视频文件，请重新上传后再导出。'
    return
  }
  await startExportJob(uploadedFile.value)
}

async function startExportJob(file) {
  if (!file) {
    error.value = '缺少原始视频文件，请重新上传后再导出。'
    return
  }

  exporting.value = true
  error.value = ''
  try {
    const created = await createRenderExpertJob(file)
    const jobId = created?.job_id
    if (!jobId) {
      throw new Error('导出任务创建失败，未返回 job_id')
    }
    upsertRenderJob({
      job_id: jobId,
      status: created?.job_status || 'queued',
      created_at: created?.created_at,
      progress: 0
    })

    const finalJob = await pollRenderJobUntilDone(jobId, {
      onProgress: (job) => {
        upsertRenderJob(job)
      }
    })
    const data = finalJob?.result
    if (!data?.local_download_url) {
      throw new Error('导出完成但未返回下载地址')
    }

    upsertRenderJob(finalJob)
    window.open(data.local_download_url, '_blank')
    await refreshRenderJobs()
  } catch (err) {
    const message = err?.response?.data?.detail || err?.message || '导出失败'
    error.value = String(message)
    await refreshRenderJobs()
  } finally {
    exporting.value = false
  }
}

async function retryRenderJob() {
  if (!uploadedFile.value) {
    error.value = '无法重试：当前会话缺少原始视频，请重新上传后再导出。'
    return
  }
  await startExportJob(uploadedFile.value)
}

function downloadFromJob(job) {
  const url = job?.result?.local_download_url
  if (!url) return
  window.open(url, '_blank')
}

function formatTimeLocal(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return d.toLocaleString('zh-CN', { hour12: false })
}

function formatDurationSec(startIso, endIso) {
  if (!startIso || !endIso) return '-'
  const s = new Date(startIso).getTime()
  const e = new Date(endIso).getTime()
  if (Number.isNaN(s) || Number.isNaN(e) || e < s) return '-'
  return `${((e - s) / 1000).toFixed(2)}s`
}

async function removeJob(job) {
  if (!job?.job_id) return

  try {
    await deleteRenderJob(job.job_id, { force: false })
    renderJobs.value = renderJobs.value.filter((j) => j.job_id !== job.job_id)
  } catch (err) {
    const detail = err?.response?.data?.detail || ''
    if (String(detail).includes('active job')) {
      const forceDelete = window.confirm('该任务正在排队/执行中。是否强制删除？')
      if (!forceDelete) return
      try {
        await deleteRenderJob(job.job_id, { force: true })
        renderJobs.value = renderJobs.value.filter((j) => j.job_id !== job.job_id)
      } catch (err2) {
        error.value = String(err2?.response?.data?.detail || err2?.message || '删除任务失败')
      }
      return
    }

    error.value = String(detail || err?.message || '删除任务失败')
  }
}

async function clearJobsHistory() {
  const confirmed = window.confirm('确定清空历史任务吗？默认会保留正在排队/执行中的任务。')
  if (!confirmed) return

  jobsClearing.value = true
  try {
    await clearRenderJobs({ force: false })
    await refreshRenderJobs()
  } catch (err) {
    error.value = String(err?.response?.data?.detail || err?.message || '清空历史失败')
  } finally {
    jobsClearing.value = false
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
  refreshRenderJobs()
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
          <UploadPanel
            :initial-file="uploadedFile"
            :uploading="loading"
            :upload-progress="uploadProgress"
            @submit="onSubmit"
          />
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
        <UploadPanel
          :initial-file="uploadedFile"
          :uploading="loading"
          :upload-progress="uploadProgress"
          @submit="onSubmit"
        />
      </section>

      <section v-if="loading" class="state-card">{{ loadingMessage || '正在推理与生成可视化，请稍候...' }}</section>
      <section v-else-if="error" class="state-card error">{{ error }}</section>

      <section class="jobs-card">
        <header class="jobs-head">
          <h2>导出任务</h2>
          <div class="jobs-actions">
            <input
              v-model.trim="jobsClassFilter"
              class="jobs-filter"
              placeholder="按类别筛选，例如 nodding"
              @keyup.enter="refreshRenderJobs"
            />
            <button class="jobs-btn" :disabled="jobsLoading" @click="refreshRenderJobs">刷新任务</button>
            <button class="jobs-btn" :disabled="exporting" @click="retryRenderJob">重试导出</button>
            <button class="jobs-btn danger" :disabled="jobsClearing" @click="clearJobsHistory">
              {{ jobsClearing ? '清理中...' : '清空历史' }}
            </button>
          </div>
        </header>

        <p v-if="jobsLoading" class="jobs-meta">正在加载任务列表...</p>
        <p v-else class="jobs-meta">最近 {{ renderJobs.length }} 条任务</p>

        <div class="jobs-table-wrap">
          <table class="jobs-table">
            <thead>
              <tr>
                <th>任务ID</th>
                <th>状态</th>
                <th>类别</th>
                <th>开始时间</th>
                <th>结束时间</th>
                <th>耗时</th>
                <th>错误</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="job in renderJobs" :key="job.job_id">
                <td class="mono">{{ job.job_id }}</td>
                <td>
                  <span class="status-pill" :class="`s-${job.status || 'queued'}`">
                    {{ job.status || 'queued' }}
                  </span>
                </td>
                <td>{{ job.class_label || '-' }}</td>
                <td>{{ formatTimeLocal(job.started_at) }}</td>
                <td>{{ formatTimeLocal(job.finished_at) }}</td>
                <td>{{ formatDurationSec(job.started_at, job.finished_at) }}</td>
                <td class="err-col">{{ job.error || '-' }}</td>
                <td>
                  <button class="jobs-btn" :disabled="!job.result?.local_download_url" @click="downloadFromJob(job)">下载</button>
                  <button class="jobs-btn danger" @click="removeJob(job)">删除</button>
                </td>
              </tr>
              <tr v-if="!renderJobs.length">
                <td colspan="8">暂无导出任务</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
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

.jobs-card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 12px;
}

.jobs-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.jobs-head h2 {
  margin: 0;
  font-size: 1.06rem;
}

.jobs-actions {
  display: flex;
  gap: 8px;
}

.jobs-filter {
  min-width: 220px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: rgba(7, 16, 26, 0.8);
  color: #deedff;
  border-radius: 8px;
  padding: 4px 8px;
}

.jobs-btn {
  border: 1px solid rgba(255, 255, 255, 0.18);
  background: rgba(255, 255, 255, 0.06);
  color: #e8f4ff;
  border-radius: 8px;
  padding: 4px 10px;
  cursor: pointer;
}

.jobs-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.jobs-btn.danger {
  border-color: rgba(255, 122, 89, 0.45);
  background: rgba(255, 122, 89, 0.16);
  color: #ffd8ce;
}

.jobs-meta {
  margin: 10px 0 6px;
  color: #cbd9e8;
}

.jobs-table-wrap {
  overflow: auto;
}

.jobs-table {
  width: 100%;
  min-width: 820px;
  border-collapse: collapse;
}

.jobs-table th,
.jobs-table td {
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  padding: 8px 6px;
  text-align: left;
  font-size: 0.84rem;
  vertical-align: top;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
}

.status-pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.74rem;
  text-transform: uppercase;
  border: 1px solid transparent;
}

.s-queued {
  background: rgba(148, 163, 184, 0.18);
  border-color: rgba(148, 163, 184, 0.32);
}

.s-running {
  background: rgba(111, 214, 255, 0.2);
  border-color: rgba(111, 214, 255, 0.45);
}

.s-success {
  background: rgba(140, 255, 201, 0.2);
  border-color: rgba(140, 255, 201, 0.45);
}

.s-error {
  background: rgba(255, 122, 89, 0.2);
  border-color: rgba(255, 122, 89, 0.45);
}

.err-col {
  max-width: 380px;
  white-space: pre-wrap;
}
</style>

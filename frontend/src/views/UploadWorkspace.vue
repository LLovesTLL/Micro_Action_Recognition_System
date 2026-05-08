<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import UploadPanel from '../components/UploadPanel.vue'
import ResultDashboard from '../components/ResultDashboard.vue'
import {
  createRenderExpertJob,
  inferVideoChunked,
  pollRenderJobUntilDone
} from '../services/api'

const loading = ref(false)
const exporting = ref(false)
const error = ref('')
const result = ref(null)
const historyResult = ref(null)
const activeHistoryRecord = ref(null)
const uploadedFile = ref(null)
const uploadProgress = ref(0)
const historyRecords = ref([])
const historyLoading = ref(false)
const historyKeyword = ref('')
const historyClearing = ref(false)
const resultPaneRef = ref(null)

const displayedResult = computed(() => historyResult.value || result.value)
const HISTORY_STORAGE_KEY = 'micro_action_inference_history'
const HISTORY_FILE_DB = 'micro_action_history_files'
const HISTORY_FILE_STORE = 'files'
const HISTORY_TOKEN_KEY = 'micro_action_tab_token'
const historyFileCache = new Map()

const existingToken = sessionStorage.getItem(HISTORY_TOKEN_KEY)
const historyTabToken = existingToken || `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
if (!existingToken) {
  sessionStorage.setItem(HISTORY_TOKEN_KEY, historyTabToken)
}

let historyFileDbPromise = null

function openHistoryFileDb() {
  if (historyFileDbPromise) return historyFileDbPromise
  historyFileDbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open(HISTORY_FILE_DB, 1)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(HISTORY_FILE_STORE)) {
        db.createObjectStore(HISTORY_FILE_STORE, { keyPath: 'key' })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
  return historyFileDbPromise
}

async function cleanupHistoryFilesIfNewSession() {
  if (existingToken) return
  try {
    const db = await openHistoryFileDb()
    const tx = db.transaction(HISTORY_FILE_STORE, 'readwrite')
    const store = tx.objectStore(HISTORY_FILE_STORE)
    const request = store.openCursor()
    request.onsuccess = (event) => {
      const cursor = event.target.result
      if (!cursor) return
      const value = cursor.value
      if (value?.token && value.token !== historyTabToken) {
        cursor.delete()
      }
      cursor.continue()
    }
  } catch {
    // Best-effort cleanup.
  }
}

async function saveHistoryFile(recordId, file) {
  if (!recordId || !file) return
  try {
    const db = await openHistoryFileDb()
    const tx = db.transaction(HISTORY_FILE_STORE, 'readwrite')
    tx.objectStore(HISTORY_FILE_STORE).put({
      key: `${historyTabToken}:${recordId}`,
      token: historyTabToken,
      record_id: recordId,
      name: file.name,
      type: file.type,
      size: file.size,
      blob: file
    })
  } catch {
    // Best-effort cache.
  }
}

async function loadHistoryFile(recordId) {
  if (!recordId) return null
  try {
    const db = await openHistoryFileDb()
    const tx = db.transaction(HISTORY_FILE_STORE, 'readonly')
    const store = tx.objectStore(HISTORY_FILE_STORE)
    const req = store.get(`${historyTabToken}:${recordId}`)
    return await new Promise((resolve) => {
      req.onsuccess = () => resolve(req.result?.blob || null)
      req.onerror = () => resolve(null)
    })
  } catch {
    return null
  }
}

async function removeHistoryFile(recordId) {
  if (!recordId) return
  try {
    const db = await openHistoryFileDb()
    const tx = db.transaction(HISTORY_FILE_STORE, 'readwrite')
    tx.objectStore(HISTORY_FILE_STORE).delete(`${historyTabToken}:${recordId}`)
  } catch {
    // Best-effort removal.
  }
}

async function clearHistoryFiles() {
  try {
    const db = await openHistoryFileDb()
    const tx = db.transaction(HISTORY_FILE_STORE, 'readwrite')
    const store = tx.objectStore(HISTORY_FILE_STORE)
    const request = store.openCursor()
    request.onsuccess = (event) => {
      const cursor = event.target.result
      if (!cursor) return
      const value = cursor.value
      if (value?.token === historyTabToken) {
        cursor.delete()
      }
      cursor.continue()
    }
  } catch {
    // Best-effort removal.
  }
}

function toLocalISOString(date) {
  const d = date instanceof Date ? date : new Date(date)
  if (Number.isNaN(d.getTime())) return null
  return d.toISOString()
}

function loadHistoryRecords() {
  try {
    const raw = sessionStorage.getItem(HISTORY_STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function persistHistoryRecords(items) {
  try {
    sessionStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(items))
  } catch {
    // Best-effort persistence.
  }
}

function refreshHistoryRecords() {
  historyLoading.value = true
  const items = loadHistoryRecords()
  const keyword = historyKeyword.value.trim().toLowerCase()
  const filtered = keyword
    ? items.filter((item) => {
        const name = String(item.video_name || '').toLowerCase()
        const label = String(item.class_label || '').toLowerCase()
        return name.includes(keyword) || label.includes(keyword)
      })
    : items
  historyRecords.value = filtered
  historyLoading.value = false
}

function addHistoryRecord({
  videoName,
  status,
  startedAt,
  finishedAt,
  resultPayload,
  errorMessage,
  sourceFile
}) {
  const record = {
    record_id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    video_name: videoName,
    status,
    class_label: resultPayload?.top_class || null,
    started_at: toLocalISOString(startedAt),
    finished_at: toLocalISOString(finishedAt),
    result: resultPayload || null,
    error: errorMessage || null,
    export_result: null,
    has_source_file: Boolean(sourceFile)
  }

  const next = [record, ...loadHistoryRecords()]
  persistHistoryRecords(next)
  refreshHistoryRecords()
  if (sourceFile) {
    historyFileCache.set(record.record_id, sourceFile)
    saveHistoryFile(record.record_id, sourceFile)
  }
  return record
}

function updateHistoryRecord(recordId, updater) {
  const items = loadHistoryRecords()
  const idx = items.findIndex((item) => item.record_id === recordId)
  if (idx < 0) return null
  const current = items[idx]
  const nextItem = typeof updater === 'function' ? updater(current) : { ...current, ...updater }
  if (current.has_source_file) {
    nextItem.has_source_file = true
  }
  items[idx] = nextItem
  persistHistoryRecords(items)
  refreshHistoryRecords()
  if (activeHistoryRecord.value?.record_id === recordId) {
    activeHistoryRecord.value = nextItem
  }
  return nextItem
}

function resolveVideoName(record) {
  return (
    record?.video_name ||
    record?.result?.filename ||
    record?.result?.inference?.filename ||
    record?.class_label ||
    record?.record_id ||
    '-'
  )
}

function resolveHistoryResult(record) {
  if (record?.result && typeof record.result === 'object') {
    return record.result
  }
  return null
}

async function viewHistoryDetail(record) {
  const detail = resolveHistoryResult(record)
  if (!detail) {
    error.value = '该记录暂无可查看的识别结果'
    return
  }

  activeHistoryRecord.value = record
  historyResult.value = detail
  uploadedFile.value = null
  await nextTick()
  resultPaneRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function clearHistoryDetail() {
  activeHistoryRecord.value = null
  historyResult.value = null
  await nextTick()
}

async function onSubmit(file) {
  loading.value = true
  uploadProgress.value = 0
  error.value = ''
  uploadedFile.value = file
  historyResult.value = null
  activeHistoryRecord.value = null
  const startedAt = new Date()

  try {
    result.value = await inferVideoChunked(file, (p) => {
      uploadProgress.value = p
    })
    const finishedAt = new Date()
    addHistoryRecord({
      videoName: file?.name || result.value?.filename || 'unknown',
      status: 'success',
      startedAt,
      finishedAt,
      resultPayload: result.value,
      errorMessage: null,
      sourceFile: file
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

    const finishedAt = new Date()
    addHistoryRecord({
      videoName: file?.name || 'unknown',
      status: 'error',
      startedAt,
      finishedAt,
      resultPayload: null,
      errorMessage: error.value,
      sourceFile: file
    })
  } finally {
    uploadProgress.value = 0
    loading.value = false
  }
}

async function onExportExpertVideo() {
  const historyId = activeHistoryRecord.value?.record_id
  if (historyId) {
    let cachedFile = historyFileCache.get(historyId)
    if (!cachedFile) {
      cachedFile = await loadHistoryFile(historyId)
      if (cachedFile) {
        historyFileCache.set(historyId, cachedFile)
      }
    }
    if (!cachedFile) {
      error.value = '历史记录缺少原始视频文件，无法导出。请重新上传该视频后再导出。'
      return
    }
    await startExportJob(cachedFile, historyId)
    return
  }

  if (!uploadedFile.value) {
    error.value = '缺少原始视频文件，请重新上传后再导出。'
    return
  }
  await startExportJob(uploadedFile.value, null)
}

async function startExportJob(file, historyRecordId) {
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

    const finalJob = await pollRenderJobUntilDone(jobId)
    const data = finalJob?.result
    if (!data?.local_download_url) {
      throw new Error('导出完成但未返回下载地址')
    }

    window.open(data.local_download_url, '_blank')
    if (historyRecordId) {
      updateHistoryRecord(historyRecordId, (current) => ({
        ...current,
        export_result: data
      }))
    }
  } catch (err) {
    const message = err?.response?.data?.detail || err?.message || '导出失败'
    error.value = String(message)
  } finally {
    exporting.value = false
  }
}

function canDownloadRecord(record) {
  if (!record?.record_id) return false
  return Boolean(record?.export_result?.local_download_url || record?.has_source_file)
}

async function downloadFromRecord(record) {
  const url = record?.export_result?.local_download_url
  if (url) {
    window.open(url, '_blank')
    return
  }

  const recordId = record?.record_id
  let cachedFile = recordId ? historyFileCache.get(recordId) : null
  if (!cachedFile && recordId) {
    cachedFile = await loadHistoryFile(recordId)
    if (cachedFile) {
      historyFileCache.set(recordId, cachedFile)
    }
  }
  if (!cachedFile) {
    error.value = '该历史记录缺少原始视频文件，无法导出下载。'
    return
  }

  await startExportJob(cachedFile, recordId)
}

function formatTimeLocal(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return d.toLocaleString('zh-CN', {
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

function formatDurationSec(startIso, endIso) {
  if (!startIso || !endIso) return '-'
  const s = new Date(startIso).getTime()
  const e = new Date(endIso).getTime()
  if (Number.isNaN(s) || Number.isNaN(e) || e < s) return '-'
  return `${((e - s) / 1000).toFixed(2)}s`
}

function removeHistoryRecord(record) {
  if (!record?.record_id) return
  const next = loadHistoryRecords().filter((item) => item.record_id !== record.record_id)
  persistHistoryRecords(next)
  historyFileCache.delete(record.record_id)
  removeHistoryFile(record.record_id)
  refreshHistoryRecords()
  if (activeHistoryRecord.value?.record_id === record.record_id) {
    clearHistoryDetail()
  }
}

function clearHistoryRecords() {
  const confirmed = window.confirm('确定清空历史推理记录吗？刷新页面不会清空，关闭页面才会自动释放。')
  if (!confirmed) return
  historyClearing.value = true
  persistHistoryRecords([])
  historyFileCache.clear()
  clearHistoryFiles()
  refreshHistoryRecords()
  historyClearing.value = false
  clearHistoryDetail()
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
  cleanupHistoryFilesIfNewSession()
  refreshHistoryRecords()
})

onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', cleanupTempOnExit)
})
</script>

<template>
  <main class="container">
    <header class="hero">
      <h1>微动作识别系统 · 视频上传</h1>
    </header>

    <section v-if="displayedResult" class="workspace split">
      <aside class="left-pane">
        <UploadPanel
          :initial-file="historyResult ? null : uploadedFile"
          :uploading="loading"
          :upload-progress="uploadProgress"
          @submit="onSubmit"
        />
      </aside>
      <section ref="resultPaneRef" class="right-pane">
        <div v-if="historyResult" class="history-banner">
          <div>
            <strong>正在查看历史推理结果</strong>
            <span> · {{ resolveVideoName(activeHistoryRecord) }}</span>
          </div>
          <button class="jobs-btn" @click="clearHistoryDetail">返回当前结果</button>
        </div>
        <ResultDashboard
          :result="displayedResult"
          :exporting="exporting"
          :show-export-action="true"
          @export-expert-video="onExportExpertVideo"
        />
      </section>
    </section>

    <section v-else class="workspace centered">
      <UploadPanel
        :initial-file="historyResult ? null : uploadedFile"
        :uploading="loading"
        :upload-progress="uploadProgress"
        @submit="onSubmit"
      />
    </section>

    <section v-if="error" class="state-card error">{{ error }}</section>

    <section class="jobs-card">
      <header class="jobs-head">
        <h2>历史推理记录</h2>
        <div class="jobs-actions">
          <input
            v-model.trim="historyKeyword"
            class="jobs-filter"
            placeholder="按视频名或类别筛选"
            @keyup.enter="refreshHistoryRecords"
          />
          <button class="jobs-btn" :disabled="historyLoading" @click="refreshHistoryRecords">刷新记录</button>
          <button class="jobs-btn danger" :disabled="historyClearing" @click="clearHistoryRecords">
            {{ historyClearing ? '清理中...' : '清空历史' }}
          </button>
        </div>
      </header>

      <p v-if="historyLoading" class="jobs-meta">正在加载记录列表...</p>
      <p v-else class="jobs-meta">最近 {{ historyRecords.length }} 条记录</p>

      <div class="jobs-table-wrap">
        <table class="jobs-table">
          <thead>
            <tr>
              <th>视频名称</th>
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
            <tr v-for="record in historyRecords" :key="record.record_id">
              <td class="mono">{{ resolveVideoName(record) }}</td>
              <td>
                <span class="status-pill" :class="`s-${record.status || 'success'}`">
                  {{ record.status || 'success' }}
                </span>
              </td>
              <td>{{ record.class_label || '-' }}</td>
              <td>{{ formatTimeLocal(record.started_at) }}</td>
              <td>{{ formatTimeLocal(record.finished_at) }}</td>
              <td>{{ formatDurationSec(record.started_at, record.finished_at) }}</td>
              <td class="err-col">{{ record.error || '-' }}</td>
              <td>
                <button class="jobs-btn" :disabled="!resolveHistoryResult(record)" @click="viewHistoryDetail(record)">
                  查看详细结果
                </button>
                <button
                  class="jobs-btn"
                  :disabled="!canDownloadRecord(record)"
                  @click="downloadFromRecord(record)"
                >
                  下载
                </button>
                <button class="jobs-btn danger" @click="removeHistoryRecord(record)">删除</button>
              </td>
            </tr>
            <tr v-if="!historyRecords.length">
              <td colspan="8">暂无历史推理记录</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </main>
</template>

<style scoped>
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
  font-size: clamp(1.8rem, 4vw, 2.6rem);
  letter-spacing: 0.03em;
}

.state-card {
  background: var(--panel);
  border: 1px solid rgba(15, 23, 42, 0.12);
  border-radius: 14px;
  padding: 14px;
  width: 100%;
  box-sizing: border-box;
  box-shadow: var(--shadow);
}

.state-card.error {
  border-color: rgba(239, 68, 68, 0.28);
  color: #991b1b;
}

.history-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid rgba(2, 132, 199, 0.18);
  background: linear-gradient(135deg, rgba(224, 242, 254, 0.9), rgba(255, 247, 237, 0.9));
  color: #0f172a;
}

.jobs-card {
  background: var(--panel);
  border: 1px solid rgba(15, 23, 42, 0.12);
  border-radius: 14px;
  padding: 12px;
  box-shadow: var(--shadow);
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
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: rgba(255, 255, 255, 0.92);
  color: var(--text-strong);
  border-radius: 8px;
  padding: 4px 8px;
}

.jobs-btn {
  border: 1px solid rgba(2, 132, 199, 0.28);
  background: linear-gradient(180deg, rgba(255, 255, 255, 1), rgba(235, 244, 253, 0.98));
  color: var(--text-strong);
  border-radius: 8px;
  padding: 4px 10px;
  cursor: pointer;
  box-shadow: 0 10px 20px rgba(15, 23, 42, 0.08);
}

.jobs-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.jobs-btn.danger {
  border-color: rgba(239, 68, 68, 0.34);
  background: linear-gradient(180deg, rgba(255, 255, 255, 1), rgba(254, 242, 242, 0.98));
  color: #b91c1c;
}

.jobs-meta {
  margin: 10px 0 6px;
  color: var(--muted);
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
  border-bottom: 1px solid rgba(148, 163, 184, 0.16);
  padding: 8px 6px;
  text-align: left;
  font-size: 0.84rem;
  vertical-align: top;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace;
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

<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import {
  getRealtimeHealth,
  sendRealtimeFrame,
  startRealtimeSession,
  stopRealtimeSession
} from '../services/api'

const videoRef = ref(null)
const canvasRef = ref(null)

const mode = ref('fast')
const cameraReady = ref(false)
const running = ref(false)
const busy = ref(false)
const error = ref('')
const statusText = ref('未启动')

const mediaStream = ref(null)
const timer = ref(null)
const sessionId = ref('')
const lastResult = ref(null)

const noActionLabel = 'no obvious action'
// If we haven't seen enough motion recently, don't keep showing an old action label.
const motionKeepMs = 500
const motionScoreThresh = 0.05
const lastMotionAtMs = ref(0)

const requestCount = ref(0)
const successCount = ref(0)
const avgLatencyMs = ref(0)
const latencyHistory = ref([])
const confidenceHistory = ref([])

const avgClientEncodeMs = ref(0)
const avgClientPostEncodeMs = ref(0)
const avgClientFrameBytes = ref(0)

// With current end-to-end latency ~140ms, 450ms sampling adds avoidable staleness.
// Keep it conservative to avoid overloading weaker networks/machines.
const snapshotIntervalMs = 150

const displayResult = computed(() => {
  const base = lastResult.value
  if (!base) return null

  const age = lastMotionAtMs.value > 0 ? Date.now() - lastMotionAtMs.value : Number.POSITIVE_INFINITY
  if (running.value && age > motionKeepMs) {
    return {
      ...base,
      top_class: noActionLabel,
      top_confidence: 0,
      topk: [],
      hotspot: null
    }
  }

  return base
})

function formatErrorMessage(err, fallback) {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      if (typeof item === 'string') return item
      if (item && typeof item === 'object') {
        const loc = Array.isArray(item.loc) ? item.loc.join('.') : ''
        const msg = String(item.msg || '')
        return loc ? `${loc}: ${msg}` : msg
      }
      return String(item)
    }).join(' | ')
  }
  if (detail && typeof detail === 'object') {
    return JSON.stringify(detail)
  }

  const msg = err?.message
  if (typeof msg === 'string' && msg.trim()) return msg
  return fallback
}

const topLabel = computed(() => {
  if (!displayResult.value) return '-'
  const c = Number(displayResult.value.top_confidence || 0)
  return `${displayResult.value.top_class || 'unknown'} (${(c * 100).toFixed(1)}%)`
})

const topk = computed(() => {
  return Array.isArray(displayResult.value?.topk) ? displayResult.value.topk : []
})

const top1Label = computed(() => {
  const label = displayResult.value?.top_class
  if (!label) return '-'
  if (label === noActionLabel) return '无明显动作'
  return label
})

const top1Confidence = computed(() => Math.max(0, Math.min(1, Number(displayResult.value?.top_confidence || 0))))

const successRate = computed(() => {
  if (!requestCount.value) return 0
  return Math.max(0, Math.min(1, successCount.value / requestCount.value))
})

const latencyRing = computed(() => {
  const value = Math.max(0, Number(avgLatencyMs.value || 0))
  const max = Math.max(1200, value)
  return Math.max(0.05, Math.min(1, value / max))
})

const avgLatencyLabel = computed(() => (avgLatencyMs.value > 0 ? `${avgLatencyMs.value.toFixed(1)}ms` : '-'))

const avgEncodeLabel = computed(() => (avgClientEncodeMs.value > 0 ? `${avgClientEncodeMs.value.toFixed(1)}ms` : '-'))
const avgPostEncodeLabel = computed(() =>
  avgClientPostEncodeMs.value > 0 ? `${avgClientPostEncodeMs.value.toFixed(1)}ms` : '-'
)
const avgFrameSizeLabel = computed(() => {
  const bytes = Number(avgClientFrameBytes.value || 0)
  if (bytes <= 0) return '-'
  if (bytes < 1024) return `${bytes.toFixed(0)}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)}MB`
})

const confidenceSparkline = computed(() => {
  return sparklinePath(confidenceHistory.value, 0, 1)
})

const latencySparkline = computed(() => {
  const max = Math.max(300, ...latencyHistory.value, 1)
  return sparklinePath(latencyHistory.value, 0, max)
})

function sparklinePath(values, min, max) {
  const data = Array.isArray(values) ? values.slice(-16) : []
  if (!data.length) return ''
  const width = 120
  const height = 40
  const step = data.length > 1 ? width / (data.length - 1) : width
  const span = Math.max(max - min, 1e-6)
  return data
    .map((value, index) => {
      const x = index * step
      const y = height - ((Math.max(min, Math.min(max, value)) - min) / span) * height
      return `${x},${y.toFixed(2)}`
    })
    .join(' ')
}

function pushHistory(listRef, value, limit = 16) {
  if (!Number.isFinite(value)) return
  listRef.value = [...listRef.value.slice(-(limit - 1)), value]
}

function smoothUpdate(targetRef, value, alpha = 0.15) {
  if (!Number.isFinite(value) || value <= 0) return
  if (targetRef.value <= 0) {
    targetRef.value = value
    return
  }
  targetRef.value = targetRef.value * (1 - alpha) + value * alpha
}

const timingText = computed(() => {
  const t = lastResult.value?.timing
  if (!t) return '-'
  const total = Number(t.total_ms || 0).toFixed(1)
  const remote = Number(t.remote_infer_ms || 0).toFixed(1)
  const rtt = Number(t.roundtrip_ms || 0).toFixed(1)
  return `total ${total}ms | remote ${remote}ms | rtt ${rtt}ms`
})

const serverTimingText = computed(() => {
  const t = lastResult.value?.timing
  if (!t) return '-'
  const upload = Number(t.upload_ms || 0)
  const serverTotal = Number(t.server_total_ms || 0)
  if (upload <= 0 && serverTotal <= 0) return '-'
  return `server_total ${serverTotal.toFixed(1)}ms | server_read ${upload.toFixed(1)}ms`
})

const transportText = computed(() => {
  const raw = String(lastResult.value?.transport || '').trim()
  if (!raw) return '-'
  if (raw === 'ws') return 'WebSocket'
  if (raw === 'http_raw') return 'HTTP RAW'
  if (raw === 'http_multipart') return 'HTTP multipart'
  return raw
})

const remoteBreakdownText = computed(() => {
  const t = lastResult.value?.timing
  if (!t) return '-'

  const decode = Number(t.decode_ms || 0)
  const hotspot = Number(t.hotspot_ms || 0)
  const buildInput = Number(t.build_input_ms || 0)
  const post = Number(t.postprocess_ms || 0)
  const nonInfer = Number(t.non_infer_ms || 0)

  if (decode <= 0 && hotspot <= 0 && buildInput <= 0 && post <= 0 && nonInfer <= 0) return '-'
  return `non_infer ${nonInfer.toFixed(1)}ms | decode ${decode.toFixed(1)}ms | hotspot ${hotspot.toFixed(1)}ms | build ${buildInput.toFixed(
    1
  )}ms | post ${post.toFixed(1)}ms`
})

const hotspot = computed(() => {
  if (!running.value) return null
  if (!displayResult.value) return null

  const hs = displayResult.value?.hotspot
  if (!hs || typeof hs !== 'object') return null

  const x1 = Math.max(0, Math.min(1, Number(hs.x1) || 0))
  const y1 = Math.max(0, Math.min(1, Number(hs.y1) || 0))
  const x2 = Math.max(0, Math.min(1, Number(hs.x2) || 0))
  const y2 = Math.max(0, Math.min(1, Number(hs.y2) || 0))

  if (x2 <= x1 || y2 <= y1) return null
  return {
    x1,
    y1,
    x2,
    y2,
    score: Number(hs.score || 0),
    source: hs.source || 'motion_diff'
  }
})

const hotspotStyle = computed(() => {
  const hs = hotspot.value
  if (!hs) return null
  return {
    left: `${hs.x1 * 100}%`,
    top: `${hs.y1 * 100}%`,
    width: `${(hs.x2 - hs.x1) * 100}%`,
    height: `${(hs.y2 - hs.y1) * 100}%`
  }
})

async function ensureCamera() {
  if (cameraReady.value) return
  error.value = ''

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: {
        width: { ideal: 960 },
        height: { ideal: 540 },
        facingMode: 'user'
      },
      audio: false
    })

    mediaStream.value = stream
    if (videoRef.value) {
      videoRef.value.srcObject = stream
      await videoRef.value.play()
    }
    cameraReady.value = true
    statusText.value = '摄像头已就绪'
  } catch (err) {
    error.value = `摄像头打开失败: ${String(err?.message || err)}`
    statusText.value = '摄像头失败'
  }
}

function stopCameraOnly() {
  if (mediaStream.value) {
    for (const track of mediaStream.value.getTracks()) {
      track.stop()
    }
    mediaStream.value = null
  }
  if (videoRef.value) {
    videoRef.value.srcObject = null
  }
  cameraReady.value = false
}

function toBlob(canvas) {
  return new Promise((resolve) => {
    canvas.toBlob((blob) => resolve(blob), 'image/jpeg', 0.78)
  })
}

async function captureAndInfer() {
  if (!running.value || busy.value) return
  if (!videoRef.value || !canvasRef.value || !sessionId.value) return

  busy.value = true
  requestCount.value += 1
  try {
    const t0 = performance.now()
    const video = videoRef.value
    const canvas = canvasRef.value
    const ctx = canvas.getContext('2d')

    const width = video.videoWidth || 640
    const height = video.videoHeight || 360
    canvas.width = width
    canvas.height = height
    ctx.drawImage(video, 0, 0, width, height)

    const frameBlob = await toBlob(canvas)
    if (!frameBlob) throw new Error('帧编码失败')

    const tEncoded = performance.now()
    const encodeMs = tEncoded - t0
    smoothUpdate(avgClientEncodeMs, encodeMs)
    smoothUpdate(avgClientFrameBytes, frameBlob.size, 0.12)

    const ts = Date.now()
    const resp = await sendRealtimeFrame({
      sessionId: sessionId.value,
      frameBlob,
      tsClientMs: ts,
      mode: mode.value
    })

    const tDone = performance.now()
    const postEncodeMs = tDone - tEncoded
    smoothUpdate(avgClientPostEncodeMs, postEncodeMs)

    lastResult.value = {
      ...(resp || {}),
      client_timing: {
        encode_ms: encodeMs,
        post_encode_ms: postEncodeMs,
        frame_bytes: frameBlob.size
      }
    }

    const hsScore = Number(resp?.hotspot?.score || 0)
    if (hsScore >= motionScoreThresh) {
      lastMotionAtMs.value = Date.now()
    }
    successCount.value += 1

    const latency = Number(resp?.timing?.total_ms || 0)
    if (latency > 0) {
      if (avgLatencyMs.value <= 0) {
        avgLatencyMs.value = latency
      } else {
        avgLatencyMs.value = avgLatencyMs.value * 0.85 + latency * 0.15
      }
      pushHistory(latencyHistory, latency)
    }

    pushHistory(confidenceHistory, top1Confidence.value)

    statusText.value = resp?.warming_up ? '模型预热中...' : '实时推理中'
  } catch (err) {
    error.value = formatErrorMessage(err, '实时推理失败')
    statusText.value = '推理异常'
  } finally {
    busy.value = false
  }
}

async function startRealtime() {
  error.value = ''
  await ensureCamera()
  if (!cameraReady.value) return

  try {
    const health = await getRealtimeHealth()
    if (health?.remote_realtime?.reachable === false) {
      throw new Error('远端实时服务不可达，请先启动远端 realtime server')
    }
  } catch (err) {
    error.value = formatErrorMessage(err, '实时服务健康检查失败')
    return
  }

  try {
    const started = await startRealtimeSession(mode.value)
    sessionId.value = started.session_id
    running.value = true
    statusText.value = '实时推理中'
    lastMotionAtMs.value = Date.now()

    if (timer.value) {
      clearTimeout(timer.value)
      timer.value = null
    }

    const loop = async () => {
      if (!running.value) return
      const startedAt = performance.now()
      await captureAndInfer()
      const elapsed = performance.now() - startedAt
      const delay = Math.max(0, snapshotIntervalMs - elapsed)
      timer.value = setTimeout(loop, delay)
    }

    loop()
  } catch (err) {
    error.value = formatErrorMessage(err, '实时会话创建失败')
    statusText.value = '会话创建失败'
  }
}

function pauseRealtime() {
  running.value = false
  if (timer.value) {
    clearTimeout(timer.value)
    timer.value = null
  }
  lastMotionAtMs.value = 0
  statusText.value = '已暂停'
}

async function stopRealtimeAll() {
  pauseRealtime()
  const sid = sessionId.value
  sessionId.value = ''
  lastResult.value = null
  lastMotionAtMs.value = 0
  if (sid) {
    try {
      await stopRealtimeSession(sid)
    } catch {
      // no-op
    }
  }
  stopCameraOnly()
  statusText.value = '已停止'
}

onBeforeUnmount(() => {
  lastMotionAtMs.value = 0
  stopRealtimeAll()
})
</script>

<template>
  <main class="rt-wrap">
    <header class="rt-head">
      <h1>微动作识别系统 · 实时推理</h1>
      <p>本地采集摄像头帧并转发到远端 GPU 推理，当前为 {{ mode }} 模式。</p>
    </header>

    <section class="rt-grid">
      <article class="camera-panel">
        <div class="camera-toolbar">
          <label>
            推理模式
            <select v-model="mode" :disabled="running">
              <option value="fast">fast</option>
              <option value="full">full</option>
            </select>
          </label>
          <div class="btn-row">
            <button class="btn" @click="ensureCamera" :disabled="cameraReady">开启摄像头</button>
            <button class="btn primary" @click="startRealtime" :disabled="running">开始实时推理</button>
            <button class="btn" @click="pauseRealtime" :disabled="!running">暂停</button>
            <button class="btn danger" @click="stopRealtimeAll">停止并关闭</button>
          </div>
        </div>

        <div class="camera-frame">
          <video ref="videoRef" autoplay muted playsinline></video>
          <div v-if="hotspotStyle" class="hotspot-box" :style="hotspotStyle"></div>
          <canvas ref="canvasRef" class="hidden-canvas"></canvas>
        </div>

        <p class="status">状态: {{ statusText }}</p>
        <p v-if="hotspot" class="hotspot-meta">
          热点区域: {{ hotspot.source }} | score {{ hotspot.score.toFixed(3) }}
        </p>
        <p v-if="error" class="error">{{ error }}</p>
      </article>

      <article class="result-panel">
        <div class="panel-head">
          <div>
            <h2>实时结果</h2>
            <p>当前会话的识别状态与运行指标</p>
          </div>
          <div class="live-pill">{{ sessionId || 'no-session' }}</div>
        </div>

        <section class="top1-card">
          <div class="top1-label">Top-1</div>
          <h3>{{ top1Label }}</h3>
          <div class="top1-row">
            <div class="top1-score">
              <svg viewBox="0 0 120 120" class="ring-chart" aria-hidden="true">
                <circle cx="60" cy="60" r="42" class="ring-track"></circle>
                <circle
                  cx="60"
                  cy="60"
                  r="42"
                  class="ring-progress confidence"
                  :stroke-dasharray="2 * Math.PI * 42"
                  :stroke-dashoffset="(2 * Math.PI * 42) * (1 - top1Confidence)"
                ></circle>
                <text x="60" y="56" text-anchor="middle" class="ring-value">{{ (top1Confidence * 100).toFixed(0) }}%</text>
                <text x="60" y="72" text-anchor="middle" class="ring-label">置信度</text>
              </svg>
            </div>
            <div class="top1-meta">
              <!-- <p><strong>通道:</strong> {{ transportText }}</p> -->
              <p><strong>时延:</strong> {{ timingText }}</p>
              <!-- <p><strong>远端拆分:</strong> {{ remoteBreakdownText }}</p>
              <p><strong>后端拆分:</strong> {{ serverTimingText }}</p> -->
              <p><strong>平均时延:</strong> {{ avgLatencyLabel }}</p>
              <!-- <p><strong>本地编码(toBlob):</strong> {{ avgEncodeLabel }}</p> -->
              <!-- <p><strong>编码后往返(含上传+推理):</strong> {{ avgPostEncodeLabel }}</p>
              <p><strong>帧大小(均值):</strong> {{ avgFrameSizeLabel }}</p> -->
              <p><strong>请求成功率:</strong> {{ (successRate * 100).toFixed(1) }}%</p>
            </div>
          </div>
        </section>

        <section class="metric-grid">
          <div class="metric-card warm">
            <span>成功率</span>
            <strong>{{ successCount }}/{{ requestCount }}</strong>
            <div class="bar-track"><span class="bar-fill success" :style="{ width: `${successRate * 100}%` }"></span></div>
          </div>
          <div class="metric-card cool">
            <span>平均时延</span>
            <strong>{{ avgLatencyLabel }}</strong>
            <svg viewBox="0 0 120 40" class="sparkline" aria-hidden="true">
              <polyline v-if="latencySparkline" :points="latencySparkline" class="sparkline-line latency"></polyline>
            </svg>
          </div>
          <div class="metric-card cool">
            <span>Top-1 趋势</span>
            <strong>{{ (top1Confidence * 100).toFixed(1) }}%</strong>
            <svg viewBox="0 0 120 40" class="sparkline" aria-hidden="true">
              <polyline v-if="confidenceSparkline" :points="confidenceSparkline" class="sparkline-line confidence"></polyline>
            </svg>
          </div>
        </section>

        <div class="topk-box" v-if="topk.length">
          <h3>TopK</h3>
          <ul>
            <li v-for="item in topk" :key="`${item.label_id}-${item.label}`">
              <span>{{ item.label }}</span>
              <strong>{{ (Number(item.confidence || 0) * 100).toFixed(1) }}%</strong>
            </li>
          </ul>
        </div>
      </article>
    </section>
  </main>
</template>

<style scoped>
.rt-wrap {
  width: min(1480px, 100%);
  margin: 0 auto;
  display: grid;
  gap: 14px;
}

.rt-head h1 {
  margin: 0;
  font-size: clamp(1.6rem, 3.4vw, 2.4rem);
}

.rt-head p {
  margin: 6px 0 0;
  color: var(--muted);
}

.rt-grid {
  display: grid;
  grid-template-columns: 1.6fr 1fr;
  gap: 14px;
}

@media (max-width: 980px) {
  .rt-grid {
    grid-template-columns: 1fr;
  }
}

.camera-panel,
.result-panel {
  background: var(--panel);
  border: 1px solid rgba(15, 23, 42, 0.14);
  border-radius: 16px;
  padding: 16px;
  box-shadow: 0 22px 52px rgba(15, 23, 42, 0.1);
}

.panel-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: flex-start;
}

.panel-head h2 {
  margin: 0;
  font-size: 1.2rem;
}

.panel-head p {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 0.92rem;
}

.live-pill {
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(224, 242, 254, 0.9);
  border: 1px solid rgba(2, 132, 199, 0.18);
  color: #075985;
  font-size: 0.82rem;
}

.top1-card {
  margin-top: 12px;
  padding: 14px;
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(255, 255, 255, 1), rgba(241, 245, 249, 0.98));
  border: 1px solid rgba(15, 23, 42, 0.14);
  box-shadow: 0 18px 44px rgba(15, 23, 42, 0.08);
}

.top1-label {
  color: #b45309;
  font-size: 1.0rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.top1-card h3 {
  margin: 6px 0 0;
  font-size: clamp(1.6rem, 3vw, 2.2rem);
}

.top1-row {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: 14px;
  align-items: center;
  margin-top: 8px;
}

@media (max-width: 560px) {
  .top1-row {
    grid-template-columns: 1fr;
    justify-items: center;
  }
}

.top1-meta {
  display: grid;
  gap: 6px;
}

.top1-meta p {
  margin: 0;
  color: var(--text-strong);
}

.ring-chart {
  width: 120px;
  height: 120px;
  transform: rotate(-90deg);
}

.ring-track,
.ring-progress {
  fill: none;
  stroke-width: 10;
}

.ring-track {
  stroke: rgba(148, 163, 184, 0.28);
}

.ring-progress.confidence {
  stroke: #8cffc9;
  stroke-linecap: round;
}

.ring-value,
.ring-label {
  transform: rotate(90deg);
  fill: var(--text-strong);
}

.ring-value {
  font-size: 24px;
  font-weight: 800;
}

.ring-label {
  font-size: 11px;
  fill: var(--muted);
}

.metric-grid {
  margin-top: 12px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

@media (max-width: 760px) {
  .metric-grid {
    grid-template-columns: 1fr;
  }
}

.metric-card {
  border-radius: 14px;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.98);
  border: 1px solid rgba(15, 23, 42, 0.1);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
}

.metric-card span {
  display: block;
  color: var(--muted);
  font-size: 0.82rem;
}

.metric-card strong {
  display: block;
  margin-top: 4px;
  font-size: 1rem;
}

.metric-card.warm {
  background: linear-gradient(135deg, rgba(255, 247, 237, 1), rgba(254, 215, 170, 0.28));
  border-color: rgba(245, 158, 11, 0.22);
}

.metric-card.cool {
  background: linear-gradient(135deg, rgba(239, 246, 255, 1), rgba(224, 242, 254, 0.9));
  border-color: rgba(2, 132, 199, 0.22);
}

.bar-track {
  margin-top: 8px;
  height: 8px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.24);
  overflow: hidden;
}

.bar-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
}

.bar-fill.success {
  background: linear-gradient(90deg, #6fd6ff, #8cffc9);
}

.sparkline {
  width: 100%;
  height: 46px;
  margin-top: 6px;
}

.sparkline-line {
  fill: none;
  stroke-width: 2.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.sparkline-line.latency {
  stroke: #ea580c;
}

.sparkline-line.confidence {
  stroke: #059669;
}

.camera-toolbar {
  display: grid;
  gap: 8px;
}

.camera-toolbar select {
  margin-left: 8px;
  border-radius: 8px;
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: rgba(255, 255, 255, 0.92);
  color: var(--text-strong);
  padding: 3px 8px;
}

.btn-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.btn {
  border: 1px solid rgba(2, 132, 199, 0.28);
  background: linear-gradient(180deg, rgba(255, 255, 255, 1), rgba(235, 245, 255, 0.98));
  color: var(--text-strong);
  border-radius: 10px;
  padding: 7px 12px;
  cursor: pointer;
  box-shadow: 0 10px 20px rgba(15, 23, 42, 0.08);
}

.btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.btn.primary {
  border-color: rgba(2, 143, 199, 0.5);
  background: linear-gradient(130deg, rgba(14, 165, 233, 1), rgba(2, 132, 199, 1));
  color: #ffffff;
  box-shadow: 0 12px 24px rgba(2, 132, 199, 0.22);
}

.btn.danger {
  border-color: rgba(239, 68, 68, 0.34);
  background: linear-gradient(180deg, rgba(255, 255, 255, 1), rgba(254, 242, 242, 0.98));
  color: #b91c1c;
}

.camera-frame {
  margin-top: 10px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 12px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.92);
  position: relative;
  min-height: 360px;
}

.camera-frame video {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  object-fit: cover;
}

.hidden-canvas {
  display: none;
}

.hotspot-box {
  position: absolute;
  border: 2px solid rgba(255, 80, 80, 0.95);
  box-shadow: 0 0 0 9999px rgba(255, 0, 0, 0.08) inset;
  border-radius: 6px;
  pointer-events: none;
}

.status {
  margin: 10px 0 0;
  color: var(--text);
}

.error {
  color: #b91c1c;
}

.hotspot-meta {
  margin: 6px 0 0;
  color: #b91c1c;
  font-size: 0.9rem;
}

.topk-box {
  margin-top: 8px;
  border-top: 1px solid rgba(148, 163, 184, 0.18);
  padding-top: 8px;
}

.topk-box ul {
  margin: 0;
  padding-left: 0;
  list-style: none;
  display: grid;
  gap: 8px;
}

.topk-box li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  padding: 8px 10px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.06);
}
</style>

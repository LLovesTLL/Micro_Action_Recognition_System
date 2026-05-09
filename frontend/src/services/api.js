import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 120000
})

const CHUNK_SIZE = 8 * 1024 * 1024
const SESSION_KEY_PREFIX = 'micro_action_upload_session:'

function fileResumeKey(file) {
  return `${SESSION_KEY_PREFIX}${file.name}:${file.size}:${file.lastModified}`
}

function toSet(arr) {
  if (!Array.isArray(arr)) return new Set()
  return new Set(arr.map((v) => Number(v)).filter((v) => Number.isInteger(v) && v >= 0))
}

async function createUploadSession(file) {
  const totalChunks = Math.ceil(file.size / CHUNK_SIZE)
  const payload = {
    filename: file.name,
    total_size: file.size,
    chunk_size: CHUNK_SIZE,
    total_chunks: totalChunks
  }
  const { data } = await api.post('/upload-sessions', payload)
  return data
}

async function getUploadSession(sessionId) {
  const { data } = await api.get(`/upload-sessions/${encodeURIComponent(sessionId)}`)
  return data
}

async function uploadChunk(sessionId, chunkIndex, blob, onChunkProgress) {
  const formData = new FormData()
  formData.append('chunk', blob, `chunk-${chunkIndex}.part`)

  const { data } = await api.put(`/upload-sessions/${encodeURIComponent(sessionId)}/chunks/${chunkIndex}`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data'
    },
    onUploadProgress: (evt) => {
      if (typeof onChunkProgress === 'function') {
        const total = evt.total || blob.size || 1
        onChunkProgress(Math.min(1, evt.loaded / total))
      }
    }
  })
  return data
}

async function ensureUploadSession(file) {
  const key = fileResumeKey(file)
  const storedId = localStorage.getItem(key)

  if (storedId) {
    try {
      const status = await getUploadSession(storedId)
      const sameFile =
        Number(status?.total_size) === Number(file.size) &&
        String(status?.filename || '') === String(file.name || '') &&
        Number(status?.chunk_size) === CHUNK_SIZE

      if (sameFile) {
        return { key, status }
      }
    } catch {
      // fallback to creating a new session
    }
  }

  const status = await createUploadSession(file)
  if (status?.session_id) {
    localStorage.setItem(key, String(status.session_id))
  }
  return { key, status }
}

async function uploadFileByChunks(file, onProgress) {
  const { key, status } = await ensureUploadSession(file)
  const sessionId = status?.session_id
  if (!sessionId) {
    throw new Error('创建上传会话失败')
  }

  const totalChunks = Number(status.total_chunks || Math.ceil(file.size / CHUNK_SIZE))
  const uploaded = toSet(status.uploaded_chunks)

  let uploadedBytes = 0
  for (let i = 0; i < totalChunks; i += 1) {
    const start = i * CHUNK_SIZE
    const end = Math.min(file.size, (i + 1) * CHUNK_SIZE)
    if (uploaded.has(i)) {
      uploadedBytes += (end - start)
    }
  }

  if (typeof onProgress === 'function') {
    onProgress(Math.min(0.99, file.size > 0 ? uploadedBytes / file.size : 0))
  }

  for (let i = 0; i < totalChunks; i += 1) {
    if (uploaded.has(i)) continue

    const start = i * CHUNK_SIZE
    const end = Math.min(file.size, (i + 1) * CHUNK_SIZE)
    const blob = file.slice(start, end)

    await uploadChunk(sessionId, i, blob, (chunkP) => {
      if (typeof onProgress === 'function') {
        const current = uploadedBytes + blob.size * chunkP
        onProgress(Math.min(0.99, file.size > 0 ? current / file.size : 0))
      }
    })

    uploadedBytes += blob.size
    if (typeof onProgress === 'function') {
      onProgress(Math.min(0.99, file.size > 0 ? uploadedBytes / file.size : 0))
    }
  }

  return {
    sessionId,
    clear: () => localStorage.removeItem(key)
  }
}

export async function inferVideo(file) {
  const formData = new FormData()
  formData.append('file', file)

  const { data } = await api.post('/infer', formData, {
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  })

  return data
}

export async function inferVideoChunked(file, onProgress) {
  const uploaded = await uploadFileByChunks(file, onProgress)
  try {
    const { data } = await api.post(`/upload-sessions/${encodeURIComponent(uploaded.sessionId)}/infer`)
    if (typeof onProgress === 'function') onProgress(1)
    uploaded.clear()
    return data
  } catch (err) {
    throw err
  }
}

export async function createRenderExpertJob(file, onProgress, callbackUrl = null) {
  const uploaded = await uploadFileByChunks(file, onProgress)
  try {
    const { data } = await api.post(
      `/upload-sessions/${encodeURIComponent(uploaded.sessionId)}/render-expert-async`,
      { callback_url: callbackUrl }
    )
    if (typeof onProgress === 'function') onProgress(1)
    uploaded.clear()
    return data
  } catch (err) {
    throw err
  }
}

export async function getRenderJob(jobId) {
  const { data } = await api.get(`/render-jobs/${encodeURIComponent(jobId)}`)
  return data
}

export async function listRenderJobs(params = {}) {
  const { data } = await api.get('/render-jobs', { params })
  return data
}

export async function deleteRenderJob(jobId, options = {}) {
  const params = {
    force: Boolean(options.force)
  }
  const { data } = await api.delete(`/render-jobs/${encodeURIComponent(jobId)}`, { params })
  return data
}

export async function clearRenderJobs(options = {}) {
  const params = {
    force: Boolean(options.force),
    status: options.status || undefined
  }
  const { data } = await api.delete('/render-jobs', { params })
  return data
}

export async function pollRenderJobUntilDone(jobId, options = {}) {
  const intervalMs = Number(options.intervalMs || 1500)
  const timeoutMs = Number(options.timeoutMs || 20 * 60 * 1000)
  const onProgress = options.onProgress

  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    const job = await getRenderJob(jobId)
    if (typeof onProgress === 'function') {
      onProgress(job)
    }

    if (job.status === 'success') return job
    if (job.status === 'error') {
      const msg = job.error || '导出任务失败'
      throw new Error(msg)
    }

    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }

  throw new Error('导出任务超时，请稍后在服务端继续查询。')
}

export async function getRealtimeHealth() {
  const { data } = await api.get('/realtime/health')
  return data
}

export async function exportInferenceReport(result) {
  const { data } = await api.post('/export-report', result, {
    responseType: 'blob',
    headers: { 'Content-Type': 'application/json' },
    timeout: 120000
  })
  return data
}

export async function startRealtimeSession(mode = 'fast') {
  const { data } = await api.post('/realtime/session/start', { mode })
  return data
}

export async function stopRealtimeSession(sessionId) {
  const { data } = await api.post('/realtime/session/stop', { session_id: sessionId })
  return data
}

export async function sendRealtimeFrame({ sessionId, frameBlob, tsClientMs, mode = 'fast' }) {
  const form = new FormData()
  form.append('session_id', sessionId)
  form.append('mode', mode)
  form.append('ts_client_ms', String(tsClientMs || Date.now()))
  form.append('frame', frameBlob, `frame-${Date.now()}.jpg`)

  const { data } = await api.post('/realtime/frame', form, {
    headers: {
      'Content-Type': 'multipart/form-data'
    },
    timeout: 30000
  })

  return data
}

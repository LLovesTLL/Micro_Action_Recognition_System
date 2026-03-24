import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 120000
})

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

export async function renderExpertVideo(file) {
  const formData = new FormData()
  formData.append('file', file)

  const { data } = await api.post('/render-expert', formData, {
    headers: {
      'Content-Type': 'multipart/form-data'
    },
    timeout: 300000
  })

  return data
}

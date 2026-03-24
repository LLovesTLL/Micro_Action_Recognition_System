<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'

const emit = defineEmits(['submit'])
const props = defineProps({
  initialFile: {
    type: Object,
    default: null
  }
})

const selectedFile = ref(null)
const dragActive = ref(false)
const previewUrl = ref('')

watch(
  () => props.initialFile,
  (file) => {
    if (file && file !== selectedFile.value) {
      selectedFile.value = file
    }
  },
  { immediate: true }
)

watch(selectedFile, (file, prevFile) => {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
  }
  if (file) {
    previewUrl.value = URL.createObjectURL(file)
  }
})

onBeforeUnmount(() => {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
  }
})

function onSelect(event) {
  const file = event.target.files?.[0]
  selectedFile.value = file || null
}

function onDrop(event) {
  event.preventDefault()
  dragActive.value = false
  const file = event.dataTransfer?.files?.[0]
  selectedFile.value = file || null
}

function onDragOver(event) {
  event.preventDefault()
  dragActive.value = true
}

function onDragLeave() {
  dragActive.value = false
}

function submit() {
  if (!selectedFile.value) {
    return
  }
  emit('submit', selectedFile.value)
}
</script>

<template>
  <section class="upload-panel">
    <h2>上传微动作视频</h2>
    <p>支持 MP4 / AVI / MOV / MKV，首版默认离线识别。</p>

    <div
      class="drop-zone"
      :class="{ active: dragActive }"
      @drop="onDrop"
      @dragover="onDragOver"
      @dragleave="onDragLeave"
    >
      <template v-if="!selectedFile">
        <p>拖拽视频到这里，或点击下方按钮选择文件</p>
      </template>
      <template v-else>
        <video class="video-cover" :src="previewUrl" muted playsinline preload="metadata" controls></video>
        <p>已选择: {{ selectedFile.name }}</p>
      </template>
    </div>

    <input type="file" accept="video/*" @change="onSelect" />
    <button class="submit-btn" :disabled="!selectedFile" @click="submit">开始识别</button>
  </section>
</template>

<style scoped>
.upload-panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 16px;
  display: flex;
  flex-direction: column;
}

h2 {
  margin: 0;
  font-size: 1.2rem;
}

p {
  color: var(--muted);
}

.drop-zone {
  border: 1px dashed var(--line);
  border-radius: 14px;
  min-height: 120px;
  display: grid;
  place-items: center;
  margin: 10px 0;
  padding: 10px;
  transition: all 0.25s ease;
  flex: 1;
}

.video-cover {
  width: min(100%, 440px);
  max-height: 260px;
  border-radius: 10px;
  object-fit: cover;
  margin-bottom: 8px;
  border: 1px solid rgba(255, 255, 255, 0.15);
}

.drop-zone.active {
  border-color: var(--accent);
  box-shadow: 0 0 0 4px rgba(255, 179, 102, 0.18);
}

input[type='file'] {
  width: 100%;
  margin-bottom: 10px;
}

.submit-btn {
  width: 100%;
  border: 0;
  border-radius: 10px;
  background: linear-gradient(130deg, #ffb366, #ff7a59);
  color: #28170a;
  font-weight: 700;
  padding: 10px 14px;
  cursor: pointer;
}

.submit-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>

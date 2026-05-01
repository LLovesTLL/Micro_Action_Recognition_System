<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'

const emit = defineEmits(['submit'])
const props = defineProps({
  initialFile: {
    type: Object,
    default: null
  },
  uploading: {
    type: Boolean,
    default: false
  },
  uploadProgress: {
    type: Number,
    default: 0
  }
})

const selectedFile = ref(null)
const dragActive = ref(false)
const previewUrl = ref('')

const stages = [
  { id: 1, name: '视频准备', hint: '校验文件并建立任务' },
  { id: 2, name: '分片上传', hint: '视频切片上传到后端' },
  { id: 3, name: '模型推理', hint: '远端 GPU 执行识别' },
  { id: 4, name: '结果整理', hint: '生成可视化并返回结果' }
]

const uploadProgressValue = computed(() => Math.max(0, Math.min(1, Number(props.uploadProgress) || 0)))

const activeStageIndex = computed(() => {
  if (!props.uploading) return -1
  const progress = uploadProgressValue.value
  if (progress < 0.25) return 0
  if (progress < 0.5) return 1
  if (progress < 0.85) return 2
  return 3
})

const currentStage = computed(() => {
  if (!props.uploading) {
    return { name: '等待开始识别', hint: '选择视频后点击开始识别' }
  }
  return stages[Math.max(0, Math.min(stages.length - 1, activeStageIndex.value))] || stages[0]
})

const stageRailWidth = computed(() => {
  if (!props.uploading) return '0%'
  const progress = uploadProgressValue.value
  if (progress < 0.25) return `${(progress / 0.25) * 18}%`
  if (progress < 0.5) return `${18 + ((progress - 0.25) / 0.25) * 27}%`
  if (progress < 0.85) return `${45 + ((progress - 0.5) / 0.35) * 30}%`
  return `${75 + ((progress - 0.85) / 0.15) * 25}%`
})

function isStageCompleted(index) {
  return props.uploading && index < activeStageIndex.value
}

function isStageActive(index) {
  return props.uploading && index === activeStageIndex.value
}

function stageClass(index) {
  if (!props.uploading) return index === 0 ? 'idle' : 'pending'
  if (isStageCompleted(index)) return 'done'
  if (isStageActive(index)) return 'active'
  return 'pending'
}

watch(
  () => props.initialFile,
  (file) => {
    if (file !== selectedFile.value) {
      selectedFile.value = file || null
    }
  },
  { immediate: true }
)

watch(selectedFile, (file) => {
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
    <p>支持 MP4 / AVI / MOV / MKV</p>

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

    <div class="file-picker">
      <label
        class="file-btn"
        :class="{ disabled: uploading }"
        for="upload-video-input"
        :aria-disabled="uploading"
      >
        选择文件
      </label>
      <span class="file-name">{{ selectedFile ? selectedFile.name : '未选择文件' }}</span>
    </div>
    <input
      id="upload-video-input"
      class="file-input-native"
      type="file"
      accept="video/*"
      :disabled="uploading"
      @change="onSelect"
    />

    <div v-if="uploading" class="progress-wrap">
      <div class="stage-rail" aria-hidden="true">
        <span class="stage-rail-track"></span>
        <span class="stage-rail-fill" :style="{ width: stageRailWidth }"></span>
      </div>

      <div class="stage-grid">
        <div
          v-for="(stage, index) in stages"
          :key="stage.id"
          class="stage-item"
          :class="stageClass(index)"
        >
          <div class="stage-circle">
            <span>{{ stage.id }}</span>
          </div>
          <div class="stage-copy">
            <strong>{{ stage.name }}</strong>
            <span>{{ stage.hint }}</span>
          </div>
        </div>
      </div>

      <div class="stage-current">
        <span class="stage-current-label">当前阶段</span>
        <strong>{{ currentStage.name }}</strong>
        <span>{{ currentStage.hint }}</span>
      </div>
    </div>

    <button class="submit-btn" :disabled="!selectedFile || uploading" @click="submit">
      {{ uploading ? '上传中...' : '开始识别' }}
    </button>
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

.file-picker {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  min-width: 0;
}

.file-input-native {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  border: 0;
  padding: 0;
  clip: rect(0 0 0 0);
  overflow: hidden;
}

.file-btn {
  flex: 0 0 auto;
  border-radius: 10px;
  border: 1px solid rgba(111, 214, 255, 0.48);
  background: linear-gradient(145deg, rgba(20, 46, 76, 0.92), rgba(11, 27, 47, 0.92));
  color: #dff1ff;
  font-weight: 700;
  font-size: 0.92rem;
  padding: 8px 14px;
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.22s ease, border-color 0.22s ease;
  box-shadow: 0 8px 20px rgba(7, 18, 34, 0.35), inset 0 0 0 1px rgba(255, 255, 255, 0.06);
}

.file-btn:hover {
  transform: translateY(-1px);
  border-color: rgba(111, 214, 255, 0.8);
  box-shadow: 0 12px 24px rgba(11, 34, 58, 0.45), 0 0 0 4px rgba(111, 214, 255, 0.14);
}

.file-btn.disabled {
  opacity: 0.45;
  cursor: not-allowed;
  pointer-events: none;
  transform: none;
  box-shadow: none;
}

.file-name {
  min-width: 0;
  flex: 1;
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(5, 14, 24, 0.48);
  color: #b7cce0;
  font-size: 0.86rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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

.progress-wrap {
  margin: 2px 0 10px;
  display: grid;
  gap: 10px;
}

.stage-rail {
  position: relative;
  height: 6px;
  border-radius: 999px;
  overflow: hidden;
}

.stage-rail-track,
.stage-rail-fill {
  position: absolute;
  inset: 0;
  border-radius: inherit;
}

.stage-rail-track {
  background: rgba(255, 255, 255, 0.1);
}

.stage-rail-fill {
  width: 0;
  background: linear-gradient(90deg, #ff7a59 0%, #ffb366 35%, #6fd6ff 70%, #8cffc9 100%);
  transition: width 0.25s ease;
}

.stage-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

@media (max-width: 920px) {
  .stage-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.stage-item {
  display: grid;
  justify-items: center;
  gap: 8px;
  text-align: center;
  padding: 8px 4px 4px;
}

.stage-circle {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  border: 2px solid rgba(255, 255, 255, 0.14);
  background: rgba(255, 255, 255, 0.04);
  color: #8ea4ba;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.04);
  transition: all 0.25s ease;
}

.stage-circle span {
  font-size: 1.05rem;
  font-weight: 800;
}

.stage-copy {
  display: grid;
  gap: 2px;
}

.stage-copy strong {
  font-size: 0.92rem;
  color: #eaf3fb;
}

.stage-copy span {
  font-size: 0.8rem;
  color: #9eb3c8;
}

.stage-item.active .stage-circle {
  border-color: rgba(111, 214, 255, 0.95);
  color: #dff8ff;
  box-shadow: 0 0 0 4px rgba(111, 214, 255, 0.16), 0 10px 26px rgba(111, 214, 255, 0.16);
  background: linear-gradient(135deg, rgba(111, 214, 255, 0.24), rgba(140, 255, 201, 0.16));
}

.stage-item.done .stage-circle {
  border-color: rgba(140, 255, 201, 0.95);
  color: #163124;
  background: linear-gradient(135deg, #8cffc9, #6fd6ff);
  box-shadow: 0 0 0 4px rgba(140, 255, 201, 0.12);
}

.stage-item.pending .stage-circle {
  opacity: 0.72;
}

.stage-item.idle .stage-circle {
  border-color: rgba(255, 179, 102, 0.55);
  color: #ffd7a8;
}

.stage-current {
  border-radius: 14px;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  display: grid;
  gap: 2px;
}

.stage-current-label {
  font-size: 0.78rem;
  color: #9eb3c8;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.stage-current strong {
  font-size: 0.98rem;
  color: #edf5ff;
}

.stage-current span:last-child {
  font-size: 0.82rem;
  color: #c5d8eb;
}
</style>

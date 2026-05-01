<script setup>
import { computed } from 'vue'

const emit = defineEmits(['export-expert-video'])

const props = defineProps({
  result: {
    type: Object,
    required: true
  },
  exporting: {
    type: Boolean,
    default: false
  },
  showExportAction: {
    type: Boolean,
    default: true
  }
})

const classNames = computed(() => {
  if (Array.isArray(props.result.topk) && props.result.topk.length) {
    return props.result.topk.map((item) => item.label)
  }
  const first = props.result.temporal_probs?.[0]
  if (!first) return []
  return Object.entries(first.probs)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .map(([name]) => name)
})

const CHART_LEFT = 44
const CHART_RIGHT = 690
const CHART_TOP = 20
const CHART_BOTTOM = 180

function yFor(prob) {
  const p = Math.max(0, Math.min(1, Number(prob) || 0))
  return CHART_BOTTOM - p * (CHART_BOTTOM - CHART_TOP)
}

const timeBounds = computed(() => {
  const points = props.result.temporal_probs || []
  if (!points.length) {
    return { min: 0, max: 1 }
  }
  const times = points.map((p) => Number(p.t) || 0)
  const min = Math.min(...times)
  const max = Math.max(...times)
  return { min, max: max > min ? max : min + 1e-6 }
})

function xForTime(t) {
  const min = timeBounds.value.min
  const max = timeBounds.value.max
  return CHART_LEFT + ((Number(t) - min) / (max - min)) * (CHART_RIGHT - CHART_LEFT)
}

function linePathForClass(className) {
  const points = props.result.temporal_probs || []
  return points
    .map((p) => `${xForTime(p.t)},${yFor(p.probs[className] || 0)}`)
    .join(' ')
}

const curveAnnotations = computed(() => {
  const points = props.result.temporal_probs || []
  if (!points.length || !classNames.value.length) return []

  const candidates = classNames.value.map((name, idx) => {
    let peakProb = -1
    let peakPoint = null
    for (const p of points) {
      const prob = Number(p.probs[name] || 0)
      if (prob > peakProb) {
        peakProb = prob
        peakPoint = p
      }
    }

    const x = peakPoint ? xForTime(peakPoint.t) : 10
    const y = yFor(Math.max(0, peakProb))
    return {
      name,
      color: palette[idx % palette.length],
      peakProb,
      x,
      y
    }
  })

  // 只标注峰值明显的曲线，且最多显示 3 个标签。
  const significant = candidates
    .filter((item) => item.peakProb >= 0.2)
    .sort((a, b) => b.peakProb - a.peakProb)
    .slice(0, 3)

  const placed = []
  for (const item of significant) {
    const crowded = placed.some((p) => Math.abs(p.x - item.x) < 72 && Math.abs(p.y - item.y) < 24)
    if (!crowded) {
      placed.push(item)
    }
  }

  return placed
})

const palette = ['#ff7a59', '#ffb366', '#ffe08a', '#6fd6ff', '#8cffc9', '#ff9ecb']

const yTicks = [0, 0.25, 0.5, 0.75, 1]

const xTicks = computed(() => {
  const min = timeBounds.value.min
  const max = timeBounds.value.max
  const count = 5
  return Array.from({ length: count }, (_, i) => {
    const ratio = count <= 1 ? 0 : i / (count - 1)
    const t = min + (max - min) * ratio
    return {
      t,
      x: xForTime(t),
      label: `${t.toFixed(2)}s`
    }
  })
})

const timingText = computed(() => {
  const total = props.result.total_time_ms
  const infer = props.result.inference_time_ms
  if (total == null && infer == null) return ''
  const totalPart = total != null ? `总耗时 ${Number(total).toFixed(1)}ms` : ''
  const inferPart = infer != null ? `推理 ${Number(infer).toFixed(1)}ms` : ''
  return [totalPart, inferPart].filter(Boolean).join(' | ')
})

function hotspotBoxStyle(hs) {
  if (!hs) return null
  const x1 = Math.max(0, Math.min(1, Number(hs.x1) || 0))
  const y1 = Math.max(0, Math.min(1, Number(hs.y1) || 0))
  const x2 = Math.max(0, Math.min(1, Number(hs.x2) || 0))
  const y2 = Math.max(0, Math.min(1, Number(hs.y2) || 0))
  return {
    left: `${x1 * 100}%`,
    top: `${y1 * 100}%`,
    width: `${Math.max(1, (x2 - x1) * 100)}%`,
    height: `${Math.max(1, (y2 - y1) * 100)}%`
  }
}
</script>

<template>
  <section class="result-wrap">
    <header class="summary">
      <h2>识别结果</h2>
      <div class="tag">Top-1: {{ result.top_class }} ({{ (result.top_confidence * 100).toFixed(1) }}%)</div>
      <button
        v-if="showExportAction"
        class="export-btn"
        :disabled="exporting"
        @click="emit('export-expert-video')"
      >
        {{ exporting ? '正在导出专家视频...' : '导出专家视频' }}
      </button>
      <p>视频时长: {{ result.duration_sec.toFixed(2) }}s</p>
      <p v-if="result.remote_device">远端设备: {{ result.remote_device }}</p>
      <p v-if="result.attention_source">注意力来源: {{ result.attention_source }}</p>
      <p v-if="result.attention_hook_mode">注意力挂钩模式: {{ result.attention_hook_mode }}</p>
      <p v-if="result.attention_normalization_mode">注意力归一化: {{ result.attention_normalization_mode }}</p>
      <p v-if="result.attention_hotspot_threshold != null">热点阈值: {{ Number(result.attention_hotspot_threshold).toFixed(2) }}</p>
      <p v-if="result.temporal_source">时序来源: {{ result.temporal_source }}</p>
      <p v-if="timingText">性能: {{ timingText }}</p>
      <p class="note">{{ result.backend_note }}</p>

      <p v-if="result.temporal_source === 'static_fallback'" class="warn">
        时序回退: 当前曲线为静态回退结果，建议检查远端 temporal_probs 生成日志。
      </p>

      <div v-if="result.topk?.length" class="topk-list">
        <span
          v-for="item in result.topk"
          :key="item.label_id"
          class="topk-item"
        >
          {{ item.label }}: {{ (item.confidence * 100).toFixed(1) }}%
        </span>
      </div>
    </header>

    <section class="viz-row">
      <article class="chart-card" v-if="result.temporal_probs?.length">
        <h3>时序概率曲线（Top-K）</h3>
        <svg viewBox="0 0 700 200" preserveAspectRatio="none">
        <line
          v-for="tick in yTicks"
          :key="`y-grid-${tick}`"
          :x1="CHART_LEFT"
          :y1="yFor(tick)"
          :x2="CHART_RIGHT"
          :y2="yFor(tick)"
          stroke="rgba(95, 106, 119, 0.28)"
          stroke-width="1"
        />

        <line
          v-for="tick in xTicks"
          :key="`x-grid-${tick.label}`"
          :x1="tick.x"
          :y1="CHART_TOP"
          :x2="tick.x"
          :y2="CHART_BOTTOM"
          stroke="rgba(95, 106, 119, 0.18)"
          stroke-width="1"
        />

        <line :x1="CHART_LEFT" :y1="CHART_BOTTOM" :x2="CHART_RIGHT" :y2="CHART_BOTTOM" stroke="#5f6a77" stroke-width="1.2" />
        <line :x1="CHART_LEFT" :y1="CHART_TOP" :x2="CHART_LEFT" :y2="CHART_BOTTOM" stroke="#5f6a77" stroke-width="1.2" />

        <text
          v-for="tick in yTicks"
          :key="`y-label-${tick}`"
          x="38"
          :y="yFor(tick) + 4"
          text-anchor="end"
          class="axis-tick"
        >
          {{ tick.toFixed(2) }}
        </text>

        <text
          v-for="tick in xTicks"
          :key="`x-label-${tick.label}`"
          :x="tick.x"
          y="194"
          text-anchor="middle"
          class="axis-tick"
        >
          {{ tick.label }}
        </text>

        <text x="6" y="14" class="axis-title">概率</text>
        <text :x="CHART_RIGHT - 2" y="194" text-anchor="end" class="axis-title">时间</text>

        <polyline
          v-for="(name, idx) in classNames"
          :key="name"
          :points="linePathForClass(name)"
          fill="none"
          :stroke="palette[idx % palette.length]"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        />

        <g v-for="item in curveAnnotations" :key="`anno-${item.name}`" class="curve-anno">
          <circle :cx="item.x" :cy="item.y" r="2.8" :fill="item.color" />
          <text
            :x="Math.min(680, item.x + 8)"
            :y="Math.max(18, item.y - 8)"
            :fill="item.color"
            class="curve-anno-text"
          >
            {{ item.name }}
          </text>
        </g>
        </svg>

        <div class="legend">
          <span v-for="(name, idx) in classNames" :key="name" :style="{ color: palette[idx % palette.length] }">
            {{ name }}
          </span>
        </div>

        <p class="chart-note">
          说明：Top-1 来自整段 16 帧联合推理；上图来自 temporal_probs（逐帧时序分析），用于解释时间变化趋势，二者数值不必严格一致。
        </p>
      </article>

      <article class="heatmap-card" v-if="result.heatmaps?.length">
        <h3>Attention 热力图（远程回传）</h3>
        <div class="heatmap-grid">
          <figure v-for="item in result.heatmaps" :key="item.heatmap_path">
            <img :src="item.heatmap_path" :alt="`heatmap-${item.t}`" />
            <div v-if="item.hotspot" class="hotspot-box" :style="hotspotBoxStyle(item.hotspot)"></div>
            <figcaption>{{ item.t.toFixed(2) }}s</figcaption>
          </figure>
        </div>
      </article>
    </section>
  </section>
</template>

<style scoped>
.result-wrap {
  display: grid;
  gap: 12px;
}

.summary,
.chart-card,
.heatmap-card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 14px;
}

.viz-row {
  display: grid;
  gap: 12px;
  grid-template-columns: 1fr;
  align-items: stretch;
}

@media (max-width: 1260px) {
  .viz-row {
    grid-template-columns: 1fr;
  }
}

.summary h2,
.chart-card h3,
.heatmap-card h3 {
  margin: 0 0 8px;
}

.tag {
  display: inline-block;
  background: rgba(111, 214, 255, 0.16);
  color: #bfefff;
  border: 1px solid rgba(111, 214, 255, 0.45);
  border-radius: 999px;
  font-weight: 700;
  padding: 6px 12px;
}

.export-btn {
  margin-left: 10px;
  border: 0;
  border-radius: 10px;
  background: linear-gradient(130deg, #8cffc9, #6fd6ff);
  color: #0b2233;
  font-weight: 700;
  padding: 6px 12px;
  cursor: pointer;
}

.export-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.note {
  color: #ffb366;
}

.warn {
  margin-top: 8px;
  color: #ffd7a8;
  background: rgba(255, 122, 89, 0.2);
  border: 1px solid rgba(255, 122, 89, 0.45);
  border-radius: 10px;
  padding: 8px 10px;
}

.topk-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.topk-item {
  border: 1px solid rgba(255, 255, 255, 0.22);
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 0.9rem;
}

svg {
  width: 100%;
  height: 190px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0));
  border-radius: 10px;
}

.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 8px;
  font-weight: 600;
}

.axis-tick {
  fill: #8ea4ba;
  font-size: 10px;
}

.axis-title {
  fill: #b8cbe0;
  font-size: 11px;
  font-weight: 700;
}

.chart-note {
  margin: 10px 0 0;
  color: #9eb3c8;
  font-size: 0.9rem;
}

.heatmap-grid {
  display: flex;
  flex-wrap: nowrap;
  gap: 10px;
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 4px;
}

figure {
  margin: 0;
  position: relative;
  flex: 0 0 138px;
}

img {
  width: 100%;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.12);
}

figcaption {
  margin-top: 4px;
  font-size: 0.8rem;
  color: #b8cbe0;
}

.hotspot-box {
  position: absolute;
  border: 2px solid rgba(255, 80, 80, 0.96);
  border-radius: 8px;
  box-shadow: 0 0 0 1px rgba(255, 80, 80, 0.4), 0 0 0 9999px rgba(255, 80, 80, 0.06) inset;
  pointer-events: none;
}
</style>

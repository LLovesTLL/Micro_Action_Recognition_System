<script setup>
import { computed } from 'vue'

const props = defineProps({
  result: {
    type: Object,
    required: true
  }
})

const classNames = computed(() => {
  const first = props.result.temporal_probs?.[0]
  return first ? Object.keys(first.probs) : []
})

const maxProb = computed(() => {
  const values = props.result.temporal_probs?.flatMap((point) => Object.values(point.probs)) || []
  if (!values.length) return 1
  return Math.max(...values)
})

function yFor(prob) {
  return 180 - (prob / maxProb.value) * 160
}

function xFor(index, total) {
  if (total <= 1) return 10
  return 10 + (index / (total - 1)) * 680
}

function linePathForClass(className) {
  const points = props.result.temporal_probs || []
  return points
    .map((p, i) => `${xFor(i, points.length)},${yFor(p.probs[className] || 0)}`)
    .join(' ')
}

const palette = ['#ff7a59', '#ffb366', '#ffe08a', '#6fd6ff', '#8cffc9', '#ff9ecb']
</script>

<template>
  <section class="result-wrap">
    <header class="summary">
      <h2>识别结果</h2>
      <div class="tag">Top-1: {{ result.top_class }} ({{ (result.top_confidence * 100).toFixed(1) }}%)</div>
      <p>视频时长: {{ result.duration_sec.toFixed(2) }}s</p>
      <p class="note">{{ result.backend_note }}</p>
    </header>

    <article class="chart-card" v-if="result.temporal_probs?.length">
      <h3>时序概率曲线</h3>
      <svg viewBox="0 0 700 200" preserveAspectRatio="none">
        <line x1="10" y1="180" x2="690" y2="180" stroke="#5f6a77" stroke-width="1" />
        <line x1="10" y1="20" x2="10" y2="180" stroke="#5f6a77" stroke-width="1" />

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
      </svg>

      <div class="legend">
        <span v-for="(name, idx) in classNames" :key="name" :style="{ color: palette[idx % palette.length] }">
          {{ name }}
        </span>
      </div>
    </article>

    <article class="heatmap-card" v-if="result.heatmaps?.length">
      <h3>Grad-CAM 热力图（集成阶段）</h3>
      <div class="heatmap-grid">
        <figure v-for="item in result.heatmaps" :key="item.heatmap_path">
          <img :src="item.heatmap_path" :alt="`heatmap-${item.t}`" />
          <figcaption>{{ item.t.toFixed(2) }}s</figcaption>
        </figure>
      </div>
    </article>
  </section>
</template>

<style scoped>
.result-wrap {
  display: grid;
  gap: 16px;
}

.summary,
.chart-card,
.heatmap-card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 18px;
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

.note {
  color: #ffb366;
}

svg {
  width: 100%;
  height: 220px;
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

.heatmap-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
}

figure {
  margin: 0;
}

img {
  width: 100%;
  height: 100px;
  object-fit: cover;
  border-radius: 8px;
}

figcaption {
  margin-top: 6px;
  color: var(--muted);
  font-size: 0.9rem;
}
</style>

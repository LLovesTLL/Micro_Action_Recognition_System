<script setup>
const emit = defineEmits(['enter-upload', 'enter-realtime'])
</script>

<template>
  <main class="home-wrap">
    <header class="home-head">
      <h1>微动作识别系统</h1>
      <p>请选择识别模式</p>
    </header>

    <section class="entry-grid">
      <button class="entry-card upload" @click="emit('enter-upload')">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M4 6.8A2.8 2.8 0 0 1 6.8 4h10.4A2.8 2.8 0 0 1 20 6.8v10.4A2.8 2.8 0 0 1 17.2 20H6.8A2.8 2.8 0 0 1 4 17.2V6.8zm2 .2v10h12V7H6zm2.8 2.8 2.7 3.2 1.9-2.3 2.8 3.3H7.8l1-1.2zm7.7-.6a1.1 1.1 0 1 1 0-2.2 1.1 1.1 0 0 1 0 2.2z"/>
        </svg>
        <h2>视频上传</h2>
        <p>上传本地视频，使用现有推理与导出流程。</p>
      </button>

      <button class="entry-card realtime" @click="emit('enter-realtime')">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M7 4.8A2.8 2.8 0 0 1 9.8 2h4.4A2.8 2.8 0 0 1 17 4.8V6h1.2A2.8 2.8 0 0 1 21 8.8v8.4a2.8 2.8 0 0 1-2.8 2.8H5.8A2.8 2.8 0 0 1 3 17.2V8.8A2.8 2.8 0 0 1 5.8 6H7V4.8zm2-.3V6h6V4.5a.8.8 0 0 0-.8-.8H9.8a.8.8 0 0 0-.8.8zm3 4.3a4.2 4.2 0 1 1 0 8.4 4.2 4.2 0 0 1 0-8.4zm0 2a2.2 2.2 0 1 0 0 4.4 2.2 2.2 0 0 0 0-4.4z"/>
        </svg>
        <h2>实时推理</h2>
        <p>连接摄像头，持续发送帧并实时显示分类结果。</p>
      </button>
    </section>
  </main>
</template>

<style scoped>
.home-wrap {
  width: min(1120px, 100%);
  margin: 0 auto;
  display: grid;
  gap: 20px;
}

.home-head {
  text-align: center;
}

.home-head h1 {
  margin: 0;
  font-size: clamp(2rem, 4.6vw, 3rem);
  letter-spacing: 0.04em;
}

.home-head p {
  margin: 8px 0 0;
  color: var(--muted);
}

.entry-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(260px, 1fr));
  gap: 18px;
}

@media (max-width: 880px) {
  .entry-grid {
    grid-template-columns: 1fr;
  }
}

.entry-card {
  text-align: left;
  border: 1px solid rgba(2, 132, 199, 0.18);
  border-radius: 18px;
  padding: 22px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 1), rgba(248, 251, 255, 0.98));
  color: var(--text-strong);
  cursor: pointer;
  box-shadow: 0 24px 54px rgba(15, 23, 42, 0.12);
  transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}

.entry-card:hover {
  transform: translateY(-3px);
}

.entry-card svg {
  width: 36px;
  height: 36px;
  fill: currentColor;
}

.entry-card h2 {
  margin: 12px 0 8px;
  font-size: 1.5rem;
}

.entry-card p {
  margin: 0;
  color: var(--muted);
  line-height: 1.5;
}

.entry-card.upload:hover {
  border-color: rgba(245, 158, 11, 0.56);
  box-shadow: 0 16px 30px rgba(245, 158, 11, 0.16);
}

.entry-card.realtime:hover {
  border-color: rgba(2, 132, 199, 0.56);
  box-shadow: 0 16px 30px rgba(2, 132, 199, 0.16);
}
</style>

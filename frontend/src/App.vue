<script setup>
import { ref } from 'vue'
import HomeEntryPanel from './components/HomeEntryPanel.vue'
import RealtimeWorkspace from './views/RealtimeWorkspace.vue'
import UploadWorkspace from './views/UploadWorkspace.vue'

const currentView = ref('home')

function goHome() {
  currentView.value = 'home'
}

function goUpload() {
  currentView.value = 'upload'
}

function goRealtime() {
  currentView.value = 'realtime'
}
</script>

<template>
  <div class="app-bg">
    <header class="top-nav" v-if="currentView !== 'home'">
      <button class="nav-btn" @click="goHome">返回主页</button>
      <div class="nav-right">
        <button class="nav-btn" :class="{ active: currentView === 'upload' }" @click="goUpload">视频上传</button>
        <button class="nav-btn" :class="{ active: currentView === 'realtime' }" @click="goRealtime">实时推理</button>
      </div>
    </header>

    <HomeEntryPanel
      v-if="currentView === 'home'"
      @enter-upload="goUpload"
      @enter-realtime="goRealtime"
    />

    <UploadWorkspace v-else-if="currentView === 'upload'" />
    <RealtimeWorkspace v-else />
  </div>
</template>

<style scoped>
.app-bg {
  min-height: 100vh;
  background:
    radial-gradient(circle at 20% 18%, rgba(245, 158, 11, 0.12), transparent 42%),
    radial-gradient(circle at 82% 0%, rgba(2, 132, 199, 0.14), transparent 38%),
    linear-gradient(180deg, #f9fbff 0%, #ebf1f8 42%, #e1e8f1 100%);
  padding: 22px 12px 38px;
  display: grid;
  align-content: start;
  gap: 14px;
}

.top-nav {
  width: min(1360px, 100%);
  margin: 0 auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.nav-right {
  display: flex;
  gap: 8px;
}

.nav-btn {
  border: 1px solid rgba(2, 132, 199, 0.28);
  background: linear-gradient(180deg, rgba(255, 255, 255, 1), rgba(236, 246, 255, 0.98));
  color: var(--text-strong);
  border-radius: 999px;
  padding: 7px 14px;
  cursor: pointer;
  box-shadow: 0 12px 26px rgba(15, 23, 42, 0.1);
}

.nav-btn.active {
  border-color: rgba(2, 132, 199, 0.56);
  background: linear-gradient(135deg, rgba(219, 234, 254, 1), rgba(224, 242, 254, 1));
  box-shadow: 0 0 0 2px rgba(2, 132, 199, 0.14) inset, 0 12px 26px rgba(2, 132, 199, 0.08);
}
</style>

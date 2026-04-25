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
    radial-gradient(circle at 20% 20%, rgba(255, 122, 89, 0.23), transparent 50%),
    radial-gradient(circle at 80% 0%, rgba(111, 214, 255, 0.2), transparent 45%),
    linear-gradient(180deg, #09121c 0%, #0d1723 48%, #101824 100%);
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
  border: 1px solid rgba(255, 255, 255, 0.18);
  background: rgba(255, 255, 255, 0.07);
  color: #e8f4ff;
  border-radius: 999px;
  padding: 7px 14px;
  cursor: pointer;
}

.nav-btn.active {
  border-color: rgba(111, 214, 255, 0.58);
  box-shadow: 0 0 0 2px rgba(111, 214, 255, 0.16) inset;
}
</style>

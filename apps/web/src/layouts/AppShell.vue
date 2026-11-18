<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { Cpu, DataBoard, Link as LinkIcon, Moon, Reading, Setting, Sunny } from '@element-plus/icons-vue'

import { useSystemStore } from '@/stores/system'
import { useThemeStore } from '@/stores/theme'

const route = useRoute()
const system = useSystemStore()
const theme = useThemeStore()

const navGroups = [
  {
    label: '工作台',
    items: [
      { name: 'dashboard', label: '概览', icon: DataBoard, to: { name: 'dashboard' } },
      { name: 'courses', label: '课程中心', icon: Reading, to: { name: 'courses' } },
    ],
  },
  {
    label: '配置',
    items: [
      { name: 'models', label: '模型配置', icon: Cpu, to: { name: 'models' } },
      { name: 'settings', label: '设置', icon: Setting, to: { name: 'settings' } },
    ],
  },
]

const pageTitle = computed(() => (typeof route.meta.title === 'string' ? route.meta.title : 'Mastery Lab'))

const activeName = computed(() => {
  const name = String(route.name ?? '')
  if (name.startsWith('course')) return 'courses'
  return name
})
const version = computed(() => system.health?.version ?? '0.1.0')

let timer: number | undefined

onMounted(() => {
  void system.refresh()
  timer = window.setInterval(() => void system.refresh(), 30_000)
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})

function toggleTheme(): void {
  theme.setMode(theme.isDark ? 'light' : 'dark')
}
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none">
            <path d="M4 19V6.5L12 15l8-8.5V19" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </span>
        <span class="brand-text">
          <strong>Mastery Lab</strong>
          <small>本地 AI 技术课堂</small>
        </span>
      </div>

      <nav class="nav">
        <div v-for="group in navGroups" :key="group.label" class="nav-group">
          <p class="nav-label">{{ group.label }}</p>
          <RouterLink
            v-for="item in group.items"
            :key="item.name"
            :to="item.to"
            class="nav-item"
            :class="['nav-item', { 'is-active': activeName === item.name }]"
            :aria-current="activeName === item.name ? 'page' : undefined"
          >
            <el-icon :size="16"><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </RouterLink>
        </div>
      </nav>

      <div class="sidebar-foot">
        <div class="status">
          <span class="status-dot" :class="{ ok: system.online, error: !system.online && !system.loading }" />
          <span class="status-text">{{ system.statusLabel }}</span>
          <span class="status-version">v{{ version }}</span>
        </div>
        <p class="foot-note">数据与密钥只保存在本机</p>
      </div>
    </aside>

    <div class="shell-main">
      <header class="topbar">
        <div class="topbar-left">
          <h1 class="topbar-title">{{ pageTitle }}</h1>
          <span class="topbar-divider" />
          <span class="topbar-hint">127.0.0.1 · 本地运行</span>
        </div>
        <div class="topbar-right">
          <a class="icon-link" href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer">
            <el-icon :size="15"><LinkIcon /></el-icon>
            <span>API 文档</span>
          </a>
          <button class="icon-button" type="button" :title="theme.isDark ? '切换到浅色主题' : '切换到深色主题'" @click="toggleTheme">
            <el-icon :size="15"><Moon v-if="!theme.isDark" /><Sunny v-else /></el-icon>
          </button>
        </div>
      </header>

      <main class="content">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  min-height: 100vh;
  background: var(--ml-bg);
}

/* ---------- 侧边栏 ---------- */
.sidebar {
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  width: 248px;
  flex: 0 0 248px;
  height: 100vh;
  padding: 20px 14px 16px;
  background: var(--ml-bg-soft);
  border-right: 1px solid var(--ml-border);
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 2px 8px 22px;
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  color: var(--ml-accent);
  background: var(--ml-accent-weak);
  border: 1px solid var(--ml-border-strong);
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
}

.brand-text strong {
  font-size: 14px;
  letter-spacing: -0.01em;
}

.brand-text small {
  font-size: 11.5px;
  color: var(--ml-text-3);
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 18px;
  flex: 1;
}

.nav-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-label {
  padding: 0 10px 6px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ml-text-3);
}

.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--ml-radius-sm);
  color: var(--ml-text-2);
  font-size: 13.5px;
  transition: background-color 0.12s ease, color 0.12s ease;
}

.nav-item:hover {
  background: var(--ml-surface);
  color: var(--ml-text);
}

.nav-item.is-active {
  background: var(--ml-surface-2);
  color: var(--ml-text);
  font-weight: 500;
}

.nav-item.is-active::before {
  content: '';
  position: absolute;
  left: -14px;
  top: 50%;
  width: 2px;
  height: 16px;
  transform: translateY(-50%);
  background: var(--ml-accent);
  border-radius: 0 2px 2px 0;
}

.sidebar-foot {
  border-top: 1px solid var(--ml-border);
  padding: 14px 8px 0;
}

.status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--ml-text-2);
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ml-text-3);
}

.status-dot.ok {
  background: var(--ml-success);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--ml-success) 18%, transparent);
}

.status-dot.error {
  background: var(--ml-danger);
}

.status-version {
  margin-left: auto;
  font-family: var(--ml-font-mono);
  font-size: 11.5px;
  color: var(--ml-text-3);
}

.foot-note {
  margin-top: 6px;
  font-size: 11.5px;
  color: var(--ml-text-3);
}

/* ---------- 主区 ---------- */
.shell-main {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 52px;
  padding: 0 40px;
  background: color-mix(in srgb, var(--ml-bg) 88%, transparent);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--ml-border);
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.topbar-title {
  font-size: 14px;
  font-weight: 600;
}

.topbar-divider {
  width: 1px;
  height: 14px;
  background: var(--ml-border-strong);
}

.topbar-hint {
  font-size: 12px;
  color: var(--ml-text-3);
  font-family: var(--ml-font-mono);
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

.icon-link,
.icon-button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 10px;
  border-radius: var(--ml-radius-sm);
  border: 1px solid transparent;
  background: transparent;
  color: var(--ml-text-2);
  font-size: 12.5px;
  font-family: inherit;
  cursor: pointer;
  transition: background-color 0.12s ease, color 0.12s ease, border-color 0.12s ease;
}

.icon-link:hover,
.icon-button:hover {
  background: var(--ml-surface-2);
  border-color: var(--ml-border);
  color: var(--ml-text);
}

.content {
  flex: 1;
  overflow-x: hidden;
}
</style>

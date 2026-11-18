<script setup lang="ts">
import { computed } from 'vue'
import { Monitor, Moon, Refresh, Sunny, TopRight } from '@element-plus/icons-vue'

import { useSystemStore } from '@/stores/system'
import { useThemeStore, type ThemeMode } from '@/stores/theme'

const theme = useThemeStore()
const system = useSystemStore()

const themeOptions: { value: ThemeMode; label: string; icon: typeof Moon }[] = [
  { value: 'dark', label: '深色', icon: Moon },
  { value: 'light', label: '浅色', icon: Sunny },
  { value: 'system', label: '跟随系统', icon: Monitor },
]

const schemeText = computed(() => {
  const scheme = system.health?.security.secretScheme
  if (scheme === 'windows-dpapi') return 'Windows DPAPI（绑定当前 Windows 用户）'
  if (scheme === 'fernet-local-key') return '本地主密钥文件（data/secrets/master.key）'
  return '—'
})

const rows = computed(() => [
  { label: '数据目录', value: system.health?.paths.dataDir ?? '—' },
  { label: '数据库文件', value: system.health?.database.path ?? '—' },
  { label: '上传目录', value: system.health?.paths.uploadsDir ?? '—' },
  { label: '密钥保护方式', value: schemeText.value },
])

function openDocs(): void {
  window.open('http://127.0.0.1:8000/docs', '_blank', 'noreferrer')
}
</script>

<template>
  <div class="ml-page">
    <div class="ml-page-head">
      <div>
        <h2 class="ml-page-title">设置</h2>
        <p class="ml-page-desc">
          这里只放本机层面的偏好与信息。所有数据留在你自己的磁盘上，不会上传到任何服务器；
          模型请求发往你在「模型配置」里填写的那个接口地址。
        </p>
      </div>
      <el-button :icon="Refresh" :loading="system.loading" @click="system.refresh()">重新检测</el-button>
    </div>

    <section class="ml-section">
      <div class="ml-section-head">
        <h3 class="ml-section-title">外观</h3>
        <span class="ml-section-note">默认深色，浅色主题已就绪</span>
      </div>
      <div class="theme-picker">
        <button
          v-for="option in themeOptions"
          :key="option.value"
          type="button"
          class="theme-option"
          :class="{ active: theme.mode === option.value }"
          @click="theme.setMode(option.value)"
        >
          <el-icon :size="16"><component :is="option.icon" /></el-icon>
          <span>{{ option.label }}</span>
        </button>
      </div>
    </section>

    <section class="ml-section">
      <div class="ml-section-head">
        <h3 class="ml-section-title">本地数据</h3>
        <span class="ml-section-note">来自 /api/v1/health</span>
      </div>
      <dl class="kv">
        <div v-for="row in rows" :key="row.label" class="kv-row">
          <dt>{{ row.label }}</dt>
          <dd class="ml-mono">{{ row.value }}</dd>
        </div>
      </dl>
      <p class="hint">
        API Key 加密后写入 SQLite，解密只发生在后端进程内；浏览器只显示固定掩码，不显示密钥字符。
        换一台机器或换一个 Windows 用户，旧密文将无法解开，需要重新填写。
      </p>
    </section>

    <section class="ml-section">
      <div class="ml-section-head">
        <h3 class="ml-section-title">服务</h3>
        <span class="ml-section-note">本地进程，仅监听 127.0.0.1</span>
      </div>
      <dl class="kv">
        <div class="kv-row">
          <dt>后端状态</dt>
          <dd>{{ system.statusLabel }}<span v-if="system.error" class="error-text"> · {{ system.error }}</span></dd>
        </div>
        <div class="kv-row">
          <dt>API 地址</dt>
          <dd class="ml-mono">http://127.0.0.1:8000/api/v1</dd>
        </div>
        <div class="kv-row">
          <dt>前端地址</dt>
          <dd class="ml-mono">http://127.0.0.1:5173</dd>
        </div>
        <div class="kv-row">
          <dt>接口文档</dt>
          <dd>
            <el-button link type="primary" :icon="TopRight" @click="openDocs">打开 Swagger UI</el-button>
          </dd>
        </div>
      </dl>
    </section>

    <section class="ml-section">
      <div class="ml-section-head">
        <h3 class="ml-section-title">关于</h3>
      </div>
      <dl class="kv">
        <div class="kv-row">
          <dt>版本</dt>
          <dd>{{ system.health?.app ?? 'Mastery Lab API' }} v{{ system.health?.version ?? '0.1.0' }}</dd>
        </div>
        <div class="kv-row">
          <dt>当前阶段</dt>
          <dd>P1.3 · AI 学习教室（教学状态机在 P1.4，代码执行在 P2）</dd>
        </div>
        <div class="kv-row">
          <dt>技术栈</dt>
          <dd>Vue 3 + Vite + Element Plus / FastAPI + SQLAlchemy + SQLite</dd>
        </div>
        <div class="kv-row">
          <dt>运行环境</dt>
          <dd>Python {{ system.health?.runtime.python ?? '—' }} · {{ system.health?.runtime.platform ?? '—' }}</dd>
        </div>
      </dl>
    </section>
  </div>
</template>

<style scoped>
.theme-picker {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.theme-option {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 120px;
  padding: 10px 14px;
  border-radius: var(--ml-radius);
  border: 1px solid var(--ml-border);
  background: var(--ml-bg-soft);
  color: var(--ml-text-2);
  font-family: inherit;
  font-size: 13px;
  cursor: pointer;
  transition: border-color 0.12s ease, color 0.12s ease, background-color 0.12s ease;
}

.theme-option:hover {
  border-color: var(--ml-border-strong);
  color: var(--ml-text);
}

.theme-option.active {
  border-color: color-mix(in srgb, var(--ml-accent) 60%, var(--ml-border));
  background: var(--ml-accent-weak);
  color: var(--ml-text);
}

.kv {
  margin: 0;
  display: grid;
  grid-template-columns: 160px minmax(0, 1fr);
  row-gap: 10px;
  column-gap: 20px;
}

.kv-row {
  display: contents;
}

.kv dt {
  font-size: 12.5px;
  color: var(--ml-text-3);
}

.kv dd {
  margin: 0;
  font-size: 12.5px;
  color: var(--ml-text-2);
  word-break: break-all;
}

.hint {
  margin-top: 14px;
  font-size: 12.5px;
  color: var(--ml-text-3);
  max-width: 72ch;
  line-height: 1.7;
}

.error-text {
  color: var(--ml-danger);
}
</style>

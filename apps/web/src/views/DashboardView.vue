<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Notebook, Refresh } from '@element-plus/icons-vue'

import { learningApi } from '@/api'
import type { ArchiveOverview, ResumeInfo } from '@/api/types'
import { useModelStore } from '@/stores/models'
import { useSystemStore } from '@/stores/system'

const system = useSystemStore()
const models = useModelStore()
const router = useRouter()
const learningOverview = ref<ArchiveOverview | null>(null)
const resume = ref<ResumeInfo | null>(null)

onMounted(() => {
  void models.load()
  if (!system.health) void system.refresh()
  void learningApi.overview().then((data) => (learningOverview.value = data)).catch(() => undefined)
  void learningApi.resume().then((data) => (resume.value = data)).catch(() => undefined)
})

function formatDuration(seconds: number): string {
  const value = Math.max(0, Math.round(seconds || 0))
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  if (hours) return `${hours} 小时 ${minutes} 分`
  if (minutes) return `${minutes} 分钟`
  return `${value} 秒`
}

const learningStats = computed(() => {
  const data = learningOverview.value
  if (!data) return []
  return [
    { label: '累计有效学习', value: formatDuration(data.effectiveSeconds), note: `${data.activityCount} 次学习活动` },
    { label: '已完成知识点', value: String(data.completedPoints), note: `共 ${data.totalPoints} 个` },
    { label: '待复习', value: String(data.needsReviewPoints), note: '来自验证失败或反复出错' },
    { label: '本周学习', value: formatDuration(data.week.effectiveSeconds), note: `完成 ${data.week.completedPoints} 个知识点` },
  ]
})

const stageText: Record<string, string> = {
  TEACH: '讲解',
  DEMO: '演示',
  CHECK: '理解检查',
  PAIR: '陪练',
  VERIFY: '独立验证',
  NEXT: '已完成',
}

function stageLabel(stage: string): string {
  return stageText[stage] ?? stage
}

function goResume(): void {
  if (!resume.value) {
    void router.push({ name: 'learning' })
    return
  }
  void router.push({
    name: 'classroom',
    params: { id: resume.value.courseId },
    query: { point: String(resume.value.knowledgePointId), resume: '1' },
  })
}

const stats = computed(() => [
  { label: '模型配置', value: String(models.count), note: models.count ? '已保存到本机数据库' : '尚未添加' },
  {
    label: '默认模型',
    value: models.defaultConfig?.modelName ?? '未设置',
    note: models.defaultConfig?.name ?? '在模型配置里指定',
  },
  { label: '后端服务', value: system.statusLabel, note: system.error ? system.error : 'http://127.0.0.1:8000' },
])

const workflow = [
  { step: '01', title: '导入教材', desc: 'Markdown / PDF 教材进入本地库，原文不改写', stage: 'P1.1 · 已完成' },
  { step: '02', title: '拆解知识点', desc: '按章节生成学习目录，可自行维护与标记学习状态', stage: 'P1.2 · 已完成' },
  { step: '03', title: '讲解与演示', desc: '老师先讲清概念，再给出最小可运行案例', stage: 'P1.3 · 已完成' },
  { step: '04', title: '教学陪练', desc: '两个小步带着用户完成，提示逐步减少', stage: 'P1.4 · 已完成' },
  { step: '05', title: '掌握验证与档案', desc: '独立验证通过后更新掌握状态、错题与学习档案', stage: 'P1.5 · 已完成' },
  { step: '06', title: '代码编辑与运行', desc: '内置编辑器、终端与隔离执行沙箱', stage: 'P2' },
]

const milestones = computed(() => [
  { title: '前端骨架', detail: 'Vue 3 + Vite + Element Plus + Pinia + Router', done: true },
  { title: '后端 API', detail: 'FastAPI 分层路由、统一响应、Swagger 文档', done: system.health !== null },
  { title: '本地数据库', detail: 'SQLite + SQLAlchemy，数据落在 data/', done: system.health?.database.ok === true },
  { title: '模型配置', detail: '多配置管理、密钥加密、真实连接测试', done: models.count > 0 },
  { title: '启动脚本', detail: 'scripts/ 下的一键启动、停止与端口检查', done: true },
  { title: '教材导入与解析', detail: 'Markdown / PDF 解析、结构预览、课程创建（P1.1）', done: true },
  { title: '课程与知识点管理', detail: '目录维护、学习状态、加权进度（P1.2）', done: true },
  { title: 'AI 教学对话', detail: '主动讲解、真实流式输出、会话恢复（P1.3）', done: true },
  { title: '教学状态机', detail: '讲解 → 演示 → 检查 → 陪练 → 独立验证（P1.4）', done: true },
  { title: '学习档案与断点续学', detail: '有效时长、掌握档案、错题本与断点恢复（P1.5）', done: true },
])

const environment = computed(() => [
  { label: 'API 地址', value: 'http://127.0.0.1:8000', mono: true },
  { label: 'API 前缀', value: '/api/v1', mono: true },
  { label: '数据库文件', value: system.health?.database.path ?? '—', mono: true },
  { label: '密钥保护', value: system.health?.security.secretScheme === 'windows-dpapi' ? 'Windows DPAPI（当前用户）' : system.health?.security.secretScheme ?? '—', mono: false },
  { label: 'Python', value: system.health?.runtime.python ?? '—', mono: true },
  { label: '平台', value: system.health?.runtime.platform ?? '—', mono: false },
])
</script>

<template>
  <div class="ml-page">
    <div class="ml-page-head">
      <div>
        <h2 class="ml-page-title">概览</h2>
        <p class="ml-page-desc">
          本机运行的技术学习工作台。教材导入、课程管理、AI 学习教室、教学状态机与学习档案
          已经可用；内置代码编辑、终端与运行沙箱会在 P2 开放。
        </p>
      </div>
      <div class="head-actions">
        <el-button :icon="Refresh" :loading="system.loading" @click="system.refresh()">刷新状态</el-button>
        <el-button type="primary" @click="router.push({ name: 'models' })">
          配置模型
          <el-icon class="el-icon--right"><ArrowRight /></el-icon>
        </el-button>
      </div>
    </div>

    <div class="stats">
      <div v-for="item in stats" :key="item.label" class="stat">
        <p class="stat-label">{{ item.label }}</p>
        <p class="stat-value" :title="item.value">{{ item.value }}</p>
        <p class="stat-note">{{ item.note }}</p>
      </div>
    </div>

    <section class="ml-section">
      <div class="ml-section-head">
        <h3 class="ml-section-title">继续学习</h3>
        <button type="button" class="link-button" @click="router.push({ name: 'learning' })">
          查看学习档案
        </button>
      </div>
      <div v-if="resume" class="resume-card">
        <div class="resume-copy">
          <span class="resume-kicker">上次停在这里</span>
          <strong>{{ resume.courseTitle }} · {{ resume.knowledgePointTitle }}</strong>
          <span class="resume-note">
            {{ resume.chapterTitle || '未分章' }} · {{ stageLabel(resume.currentStage) }}
            <template v-if="resume.hasDraft"> · 有未提交草稿</template>
          </span>
        </div>
        <el-button type="primary" :icon="ArrowRight" @click="goResume">回到教室</el-button>
      </div>
      <div v-if="learningStats.length" class="learning-strip">
        <div v-for="item in learningStats" :key="item.label" class="learning-cell">
          <p class="stat-label">{{ item.label }}</p>
          <p class="stat-value">{{ item.value }}</p>
          <p class="stat-note">{{ item.note }}</p>
        </div>
      </div>
      <div v-else class="learning-empty">
        <span class="ml-muted">还没有学习记录。导入课程并进入学习教室后，这里会显示真实的时长与掌握情况。</span>
        <el-button size="small" :icon="Notebook" @click="router.push({ name: 'courses' })">去课程中心</el-button>
      </div>
    </section>

    <section class="ml-section">
      <div class="ml-section-head">
        <h3 class="ml-section-title">学习流程</h3>
        <span class="ml-section-note">灰色步骤尚未实现，不会出现可点但无响应的入口</span>
      </div>
      <ol class="workflow">
        <li v-for="item in workflow" :key="item.step" class="workflow-item">
          <span class="workflow-step">{{ item.step }}</span>
          <div class="workflow-body">
            <div class="workflow-title">
              {{ item.title }}
              <el-tag size="small" type="info" effect="plain">{{ item.stage }}</el-tag>
            </div>
            <p class="workflow-desc">{{ item.desc }}</p>
          </div>
        </li>
      </ol>
    </section>

    <section class="ml-section">
      <div class="ml-section-head">
        <h3 class="ml-section-title">运行环境</h3>
        <span class="ml-section-note">数据来自后端 /api/v1/health</span>
      </div>
      <dl class="kv">
        <div v-for="row in environment" :key="row.label" class="kv-row">
          <dt>{{ row.label }}</dt>
          <dd :class="{ 'ml-mono': row.mono }">{{ row.value }}</dd>
        </div>
      </dl>
    </section>

    <section class="ml-section">
      <div class="ml-section-head">
        <h3 class="ml-section-title">交付状态</h3>
        <span class="ml-section-note">勾选表示已在本机实际验证</span>
      </div>
      <ul class="milestones">
        <li v-for="item in milestones" :key="item.title" class="milestone">
          <span class="milestone-mark" :class="{ done: item.done }">{{ item.done ? '✓' : '·' }}</span>
          <div>
            <p class="milestone-title">{{ item.title }}</p>
            <p class="milestone-detail">{{ item.detail }}</p>
          </div>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.head-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.stats,
.learning-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border: 1px solid var(--ml-border);
  border-radius: var(--ml-radius-lg);
  background: var(--ml-bg-soft);
  overflow: hidden;
}

.learning-strip {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.learning-cell {
  padding: 14px 18px;
  border-left: 1px solid var(--ml-border);
  min-width: 0;
}

.learning-cell:first-child {
  border-left: none;
}

.resume-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  margin-bottom: 12px;
  border: 1px solid color-mix(in srgb, var(--ml-accent) 30%, transparent);
  border-radius: var(--ml-radius-lg);
  background: color-mix(in srgb, var(--ml-accent) 7%, transparent);
}

.resume-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.resume-kicker {
  font-size: 11px;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: var(--ml-text-3);
}

.resume-copy strong {
  font-size: 13.5px;
}

.resume-note {
  font-size: 12px;
  color: var(--ml-text-3);
}

.learning-empty {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 0 4px;
  font-size: 12.5px;
}

.link-button {
  padding: 0;
  border: none;
  background: none;
  color: var(--ml-accent);
  font: inherit;
  cursor: pointer;
}

.stat {
  padding: 18px 20px;
  border-left: 1px solid var(--ml-border);
  min-width: 0;
}

.stat:first-child {
  border-left: none;
}

.stat-label {
  font-size: 12px;
  color: var(--ml-text-3);
  letter-spacing: 0.02em;
}

.stat-value {
  margin-top: 6px;
  font-size: 19px;
  font-weight: 600;
  color: var(--ml-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stat-note {
  margin-top: 4px;
  font-size: 12px;
  color: var(--ml-text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.workflow {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 2px;
}

.workflow-item {
  display: flex;
  gap: 14px;
  padding: 12px 14px;
  border-radius: var(--ml-radius);
  transition: background-color 0.12s ease;
}

.workflow-item:hover {
  background: var(--ml-surface);
}

.workflow-step {
  font-family: var(--ml-font-mono);
  font-size: 12px;
  color: var(--ml-text-3);
  padding-top: 2px;
}

.workflow-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13.5px;
  font-weight: 500;
}

.workflow-desc {
  margin-top: 2px;
  font-size: 12.5px;
  color: var(--ml-text-3);
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

.milestones {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 24px;
}

.milestone {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.milestone-mark {
  display: grid;
  place-items: center;
  width: 16px;
  height: 16px;
  margin-top: 3px;
  border-radius: 4px;
  border: 1px solid var(--ml-border-strong);
  font-size: 10px;
  color: var(--ml-text-3);
  flex-shrink: 0;
}

.milestone-mark.done {
  border-color: color-mix(in srgb, var(--ml-success) 50%, transparent);
  color: var(--ml-success);
  background: color-mix(in srgb, var(--ml-success) 12%, transparent);
}

.milestone-title {
  font-size: 13px;
  color: var(--ml-text);
}

.milestone-detail {
  font-size: 12px;
  color: var(--ml-text-3);
}
</style>

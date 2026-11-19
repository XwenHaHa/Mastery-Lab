<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, Refresh, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { courseApi, learningApi } from '@/api'
import type { CourseSummary, MistakeDetail, MistakePage, MistakeRecord } from '@/api/types'

const router = useRouter()
const loading = ref(true)
const detailLoading = ref(false)
const data = ref<MistakePage>({ total: 0, items: [] })
const courses = ref<CourseSummary[]>([])
const courseId = ref<number | undefined>(undefined)
const errorType = ref<string | undefined>(undefined)
const status = ref<string | undefined>(undefined)
const page = ref(1)
const detailOpen = ref(false)
const detail = ref<MistakeDetail | null>(null)

const stageLabels: Record<string, string> = {
  CHECK: '理解检查',
  PAIR: '陪练',
  VERIFY: '独立验证',
}

const verdictLabels: Record<string, string> = {
  CORRECT: '正确',
  INCORRECT: '错误',
  PARTIAL: '部分正确',
  PASSED: '通过',
  FAILED: '未通过',
  NEEDS_REVIEW: '需要复习',
  UNCLEAR: '证据不足',
}

const hasFilters = computed(() => Boolean(courseId.value || errorType.value || status.value))
const rangeLabel = computed(() => {
  if (!data.value.total) return '暂无记录'
  const start = (page.value - 1) * 10 + 1
  return `第 ${start}-${Math.min(start + 9, data.value.total)} 条 / 共 ${data.value.total} 条`
})

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

async function load(): Promise<void> {
  loading.value = true
  try {
    data.value = await learningApi.mistakes({
      courseId: courseId.value,
      errorType: errorType.value,
      status: status.value,
      limit: 10,
      offset: (page.value - 1) * 10,
    })
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '错题加载失败')
  } finally {
    loading.value = false
  }
}

async function openDetail(id: number): Promise<void> {
  detailOpen.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await learningApi.mistake(id)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '错题详情加载失败')
  } finally {
    detailLoading.value = false
  }
}

async function mark(item: MistakeRecord, next: 'open' | 'understood'): Promise<void> {
  try {
    const updated = await learningApi.updateMistake(item.id, next)
    ElMessage.success(next === 'understood' ? '已标记为理解' : '已重新打开')
    if (detail.value?.id === updated.id) detail.value = { ...detail.value, ...updated }
    await load()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '更新失败')
  }
}

function onPageChange(value: number): void {
  page.value = value
  void load()
}

async function practice(item: MistakeRecord): Promise<void> {
  try {
    const target = await learningApi.practiceMistake(item.id)
    void router.push(target.route)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '无法进入练习')
  }
}

function resetFilters(): void {
  courseId.value = undefined
  errorType.value = undefined
  status.value = undefined
  page.value = 1
  void load()
}

watch([courseId, errorType, status], () => {
  page.value = 1
  void load()
})

onMounted(async () => {
  try {
    courses.value = await courseApi.list()
  } catch {
    courses.value = []
  }
  await load()
})
</script>

<template>
  <div class="ml-page mistakes-page">
    <div class="ml-page-head">
      <div>
        <h2 class="ml-page-title">错题与薄弱点</h2>
        <p class="ml-page-desc">
          只记录 CHECK / PAIR / VERIFY 中真实的错误或验证失败。相同错误会归并，发生次数与每次上下文都保留。
        </p>
      </div>
      <div class="head-actions">
        <el-button :icon="ArrowLeft" @click="router.push({ name: 'learning' })">返回学习档案</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <div class="filter-bar">
      <el-select v-model="courseId" clearable size="small" placeholder="全部课程" class="filter-course">
        <el-option v-for="course in courses" :key="course.id" :label="course.title" :value="course.id" />
      </el-select>
      <el-select v-model="errorType" clearable size="small" placeholder="全部错误类型" class="filter-type">
        <el-option label="概念理解" value="concept" />
        <el-option label="实践操作" value="practice" />
        <el-option label="独立验证" value="verification" />
      </el-select>
      <el-select v-model="status" clearable size="small" placeholder="全部状态" class="filter-status">
        <el-option label="待处理" value="open" />
        <el-option label="已理解" value="understood" />
      </el-select>
      <button v-if="hasFilters" type="button" class="link-button" @click="resetFilters">清除筛选</button>
      <span class="filter-spacer" />
      <span class="ml-muted">{{ rangeLabel }}</span>
    </div>

    <div v-loading="loading" class="mistake-list">
      <div v-if="data.items.length" class="mistake-table">
        <div class="mistake-head">
          <span>知识点 / 来源</span>
          <span>错误原因</span>
          <span>次数</span>
          <span>最近发生</span>
          <span>状态</span>
          <span />
        </div>
        <div
          v-for="item in data.items"
          :key="item.id"
          class="mistake-row"
          :class="{ 'is-understood': item.status === 'understood' }"
          @click="openDetail(item.id)"
        >
          <div class="mistake-main">
            <strong>{{ item.pointTitle }}</strong>
            <span class="mistake-meta">
              {{ item.courseTitle }} · {{ item.chapterTitle }} ·
              {{ stageLabels[item.stage] || item.stage }} · {{ item.errorTypeLabel }}
            </span>
            <span class="mistake-question">{{ item.question || '（题目记录缺失）' }}</span>
          </div>
          <div class="mistake-reason">
            {{ item.errorReason || item.correction || '未记录原因' }}
          </div>
          <div class="mistake-count">×{{ item.occurrenceCount }}</div>
          <div class="mistake-time">{{ formatDateTime(item.lastSeenAt) }}</div>
          <div>
            <span class="status-pill" :class="`is-${item.status}`">
              {{ item.status === 'open' ? '待处理' : '已理解' }}
            </span>
          </div>
          <div class="mistake-actions" @click.stop>
            <el-button size="small" text type="primary" @click="practice(item)">重新练习</el-button>
            <el-button
              v-if="item.status === 'open'"
              size="small"
              text
              @click="mark(item, 'understood')"
            >
              已理解
            </el-button>
            <el-button v-else size="small" text @click="mark(item, 'open')">重新打开</el-button>
          </div>
        </div>
      </div>
      <div v-else-if="!loading" class="ml-empty">
        <h3>这张错题本还是空的</h3>
        <p>
          进入学习教室后，只有在理解检查答错、陪练出错或独立验证未通过时才会生成错题。
          自由提问不会计入错题。
        </p>
        <el-button type="primary" @click="router.push({ name: 'learning' })">查看学习档案</el-button>
      </div>
    </div>

    <div v-if="data.total > 10" class="mistake-foot">
      <el-pagination
        layout="prev, pager, next"
        :current-page="page"
        :page-size="10"
        :total="data.total"
        @current-change="onPageChange"
      />
    </div>

    <el-drawer v-model="detailOpen" size="600px" title="错题详情">
      <div v-loading="detailLoading" class="detail-body">
        <template v-if="detail">
          <div class="detail-head">
            <div>
              <h3>{{ detail.pointTitle }}</h3>
              <p class="ml-muted">
                {{ detail.courseTitle }} · {{ detail.chapterTitle }} ·
                {{ stageLabels[detail.stage] || detail.stage }} · {{ detail.errorTypeLabel }}
              </p>
            </div>
            <span class="status-pill" :class="`is-${detail.status}`">
              {{ detail.status === 'open' ? '待处理' : '已理解' }}
            </span>
          </div>

          <div class="detail-actions">
            <el-button size="small" type="primary" :icon="VideoPlay" @click="practice(detail)">重新练习</el-button>
            <el-button
              v-if="detail.status === 'open'"
              size="small"
              @click="mark(detail, 'understood')"
            >
              标记为已理解
            </el-button>
            <el-button v-else size="small" @click="mark(detail, 'open')">重新打开</el-button>
          </div>

          <div class="qa-block">
            <h4>原始问题</h4>
            <p>{{ detail.question || '（未记录题目）' }}</p>
          </div>
          <div class="qa-block">
            <h4>你的回答</h4>
            <p>{{ detail.userAnswer || '（未记录回答）' }}</p>
          </div>
          <div class="qa-block">
            <h4>错误原因</h4>
            <p>{{ detail.errorReason || '未记录' }}</p>
          </div>
          <div class="qa-block">
            <h4>纠正讲解</h4>
            <p>{{ detail.correction || detail.correctAnswer || '未记录' }}</p>
          </div>
          <div v-if="detail.misconceptions.length" class="qa-block">
            <h4>识别到的理解偏差</h4>
            <ul class="misconceptions">
              <li v-for="item in detail.misconceptions" :key="item">{{ item }}</li>
            </ul>
          </div>

          <div class="occurrences">
            <div class="detail-block-head">
              <h4>发生历史</h4>
              <span class="ml-muted">共 {{ detail.occurrenceCount }} 次</span>
            </div>
            <div v-for="item in detail.occurrences" :key="item.id" class="occurrence">
              <div class="occurrence-head">
                <span>{{ stageLabels[item.stage] || item.stage }} · {{ verdictLabels[item.verdict] || item.verdict }}</span>
                <span class="ml-muted">{{ formatDateTime(item.createdAt) }}</span>
              </div>
              <p class="occurrence-answer">回答：{{ item.userAnswer || '（空）' }}</p>
              <p v-if="item.feedback" class="occurrence-feedback">{{ item.feedback }}</p>
            </div>
          </div>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}

.filter-course {
  width: 200px;
}
.filter-type,
.filter-status {
  width: 150px;
}

.filter-spacer {
  flex: 1;
}

.link-button {
  padding: 0;
  border: none;
  background: none;
  color: var(--ml-accent);
  font: inherit;
  cursor: pointer;
}

.mistake-list {
  min-height: 200px;
}

.mistake-table {
  border: 1px solid var(--ml-border);
  border-radius: var(--ml-radius-lg);
  overflow: hidden;
  background: var(--ml-surface);
}

.mistake-head,
.mistake-row {
  display: grid;
  grid-template-columns: minmax(260px, 1.6fr) minmax(160px, 1.1fr) 54px 96px 74px 190px;
  gap: 14px;
  align-items: center;
  padding: 10px 16px;
}

.mistake-head {
  font-size: 11.5px;
  color: var(--ml-text-3);
  background: var(--ml-surface-2);
  border-bottom: 1px solid var(--ml-border);
}

.mistake-row {
  border-top: 1px solid var(--ml-border);
  cursor: pointer;
  transition: background 0.12s ease;
}

.mistake-row:first-of-type {
  border-top: none;
}

.mistake-row:hover {
  background: var(--ml-surface-2);
}

.mistake-row.is-understood {
  opacity: 0.72;
}

.mistake-main {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.mistake-main strong {
  font-size: 13px;
}

.mistake-meta,
.mistake-question {
  font-size: 11.5px;
  color: var(--ml-text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mistake-reason {
  font-size: 12px;
  color: var(--ml-text-2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.mistake-count {
  font-size: 12.5px;
  color: var(--ml-warning);
  font-variant-numeric: tabular-nums;
}

.mistake-time {
  font-size: 11.5px;
  color: var(--ml-text-3);
}

.mistake-actions {
  display: flex;
  justify-content: flex-end;
  gap: 2px;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid var(--ml-border);
  font-size: 11px;
  color: var(--ml-text-3);
  white-space: nowrap;
}

.status-pill.is-open {
  color: var(--ml-warning);
  border-color: color-mix(in srgb, var(--ml-warning) 38%, transparent);
  background: color-mix(in srgb, var(--ml-warning) 10%, transparent);
}

.status-pill.is-understood {
  color: var(--ml-success);
  border-color: color-mix(in srgb, var(--ml-success) 38%, transparent);
  background: color-mix(in srgb, var(--ml-success) 10%, transparent);
}

.mistake-foot {
  margin-top: 14px;
  display: flex;
  justify-content: flex-end;
}

.detail-body {
  min-height: 180px;
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--ml-border);
}

.detail-actions {
  display: flex;
  gap: 8px;
  padding: 12px 0;
  border-bottom: 1px solid var(--ml-border);
}

.qa-block {
  margin-top: 16px;
}

.qa-block h4,
.occurrences h4 {
  font-size: 12px;
  color: var(--ml-text-3);
  font-weight: 600;
  margin-bottom: 4px;
}

.qa-block p {
  padding: 9px 12px;
  border: 1px solid var(--ml-border);
  border-radius: var(--ml-radius);
  background: var(--ml-bg-soft);
  font-size: 12.5px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.misconceptions {
  margin: 0;
  padding-left: 20px;
  font-size: 12.5px;
  color: var(--ml-warning);
}

.detail-block-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 8px;
}

.occurrences {
  margin-top: 22px;
  padding-top: 14px;
  border-top: 1px solid var(--ml-border);
}

.occurrence {
  padding: 9px 0;
  border-bottom: 1px solid var(--ml-border);
}

.occurrence-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  color: var(--ml-text-2);
}

.occurrence-answer {
  margin-top: 3px;
  font-size: 12px;
  color: var(--ml-text-3);
}

.occurrence-feedback {
  margin-top: 3px;
  font-size: 12px;
  color: var(--ml-text-2);
}

@media (max-width: 1200px) {
  .mistake-head {
    display: none;
  }
  .mistake-row {
    grid-template-columns: 1fr 80px;
    gap: 6px 12px;
  }
  .mistake-reason,
  .mistake-time,
  .mistake-actions {
    grid-column: span 2;
  }
  .mistake-actions {
    justify-content: flex-start;
  }
}
</style>

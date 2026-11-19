<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Clock, Collection, EditPen, Refresh, Warning } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { courseApi, learningApi } from '@/api'
import type {
  ArchiveOverview,
  CourseLearningProgress,
  CourseSummary,
  LearningHistoryDetail,
  LearningHistoryPage,
  LearningReport,
  MasteryOverview,
  MasteryState,
  ResumeInfo,
} from '@/api/types'

withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })
const router = useRouter()
const loading = ref(true)
const error = ref('')
const overview = ref<ArchiveOverview | null>(null)
const courses = ref<CourseLearningProgress[]>([])
const mastery = ref<MasteryOverview | null>(null)
const report = ref<LearningReport | null>(null)
const history = ref<LearningHistoryPage>({ total: 0, items: [] })
const resume = ref<ResumeInfo | null>(null)
const courseOptions = ref<CourseSummary[]>([])
const courseFilter = ref<number | undefined>(undefined)
const historyPage = ref(1)
const historyLoading = ref(false)
const detailOpen = ref(false)
const detailLoading = ref(false)
const detail = ref<LearningHistoryDetail | null>(null)

const masteryMap: Record<MasteryState, string> = {
  NOT_STARTED: 'is-not-started',
  INTRODUCED: 'is-introduced',
  UNDERSTANDING: 'is-understanding',
  GUIDED_PRACTICE: 'is-guided',
  INDEPENDENT: 'is-independent',
  NEEDS_REVIEW: 'is-needs-review',
}

const stageLabels: Record<string, string> = {
  TEACH: '讲解',
  DEMO: '演示',
  CHECK: '理解检查',
  PAIR: '陪练',
  VERIFY: '独立验证',
  NEXT: '已通过',
}

const resultLabels: Record<string, string> = {
  completed: '已完成',
  finished: '主动结束',
  interrupted: '中断',
  in_progress: '进行中',
}

const errorTypeLabels: Record<string, string> = {
  concept: '概念理解',
  practice: '实践操作',
  verification: '独立验证',
}

const overviewMetrics = computed(() => {
  const data = overview.value
  if (!data) return []
  return [
    { label: '累计有效学习', value: duration(data.effectiveSeconds), note: `${data.activityCount} 次学习活动` },
    { label: '学习过的课程', value: `${data.studiedCourseCount}`, note: `共 ${data.totalCourseCount} 门课程` },
    { label: '已完成知识点', value: `${data.completedPoints}`, note: `共 ${data.totalPoints} 个知识点` },
    { label: '正在学习', value: `${data.inProgressPoints}`, note: '保持连续学习' },
    { label: '待复习', value: `${data.needsReviewPoints}`, note: '验证失败或反复出错' },
    { label: '最近学习', value: data.lastStudiedAt ? fromNow(data.lastStudiedAt) : '—', note: data.lastStudiedAt ? formatDateTime(data.lastStudiedAt) : '还没有学习记录' },
  ]
})

const masteryTotal = computed(() => mastery.value?.total ?? 0)
const masteryBar = computed(() => {
  const total = masteryTotal.value || 1
  return (mastery.value?.states ?? []).map((item) => ({
    ...item,
    percent: Math.round((item.count / total) * 1000) / 10,
    className: masteryMap[item.state],
  }))
})
const masteryHasData = computed(() => (mastery.value?.states ?? []).some((item) => item.count > 0))

const weakPoints = computed(() => report.value?.weakPoints ?? [])
const recentProgress = computed(() => report.value?.recentProgress ?? [])
const historyFrom = computed(() => (historyPage.value - 1) * 10 + 1)

function formatDuration(seconds: number): string {
  const value = Math.max(0, Math.round(seconds || 0))
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  const secs = value % 60
  if (hours) return `${hours} 小时 ${minutes} 分`
  if (minutes) return `${minutes} 分 ${secs} 秒`
  return `${secs} 秒`
}
const duration = formatDuration

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

function fromNow(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const diff = Date.now() - date.getTime()
  const minutes = Math.floor(diff / 60_000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days} 天前`
  return formatDateTime(value)
}

function masteryClass(state: MasteryState): string {
  return masteryMap[state] ?? 'is-not-started'
}

async function loadAll(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [o, c, m, r, h, rs, allCourses] = await Promise.all([
      learningApi.overview(),
      learningApi.courses(),
      learningApi.mastery({ courseId: courseFilter.value }),
      learningApi.report(courseFilter.value),
      learningApi.history({ courseId: courseFilter.value, limit: 10, offset: 0 }),
      learningApi.resume(),
      courseApi.list(),
    ])
    overview.value = o
    courses.value = c
    mastery.value = m
    report.value = r
    history.value = h
    resume.value = rs
    courseOptions.value = allCourses
    historyPage.value = 1
  } catch (err) {
    error.value = err instanceof Error ? err.message : '学习档案加载失败'
  } finally {
    loading.value = false
  }
}

async function reloadScoped(): Promise<void> {
  loading.value = true
  try {
    const [m, r, h] = await Promise.all([
      learningApi.mastery({ courseId: courseFilter.value }),
      learningApi.report(courseFilter.value),
      learningApi.history({ courseId: courseFilter.value, limit: 10, offset: 0 }),
    ])
    mastery.value = m
    report.value = r
    history.value = h
    historyPage.value = 1
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '筛选失败')
  } finally {
    loading.value = false
  }
}

async function loadHistoryPage(page: number): Promise<void> {
  historyLoading.value = true
  try {
    history.value = await learningApi.history({
      courseId: courseFilter.value,
      limit: 10,
      offset: (page - 1) * 10,
    })
    historyPage.value = page
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '学习历史加载失败')
  } finally {
    historyLoading.value = false
  }
}

function onRowClick(row: { id: number }): void {
  void openDetail(row.id)
}

async function openDetail(rowId: number): Promise<void> {
  detailOpen.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await learningApi.historyDetail(rowId)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '学习详情加载失败')
  } finally {
    detailLoading.value = false
  }
}

function goResume(): void {
  if (!resume.value) return
  void router.push({
    name: 'classroom',
    params: { id: resume.value.courseId },
    query: { point: String(resume.value.knowledgePointId), resume: '1' },
  })
}

function goCourse(courseId: number): void {
  void router.push({ name: 'course-detail', params: { id: courseId } })
}

function continueCourse(course: CourseLearningProgress): void {
  if (!course.currentPosition) {
    goCourse(course.courseId)
    return
  }
  void router.push({
    name: 'classroom',
    params: { id: course.courseId },
    query: { point: String(course.currentPosition.pointId), resume: '1' },
  })
}

watch(courseFilter, () => void reloadScoped())

onMounted(() => void loadAll())
</script>

<template>
  <div class="ml-page p15-page" :class="{ embedded }">
    <div class="ml-page-head">
      <div>
        <h2 class="ml-page-title">学习档案</h2>
        <p class="ml-page-desc">
          有效学习时长来自教室心跳累计，掌握状态与错题都来自真实教学评价，不使用模拟数据。
        </p>
      </div>
      <div class="head-actions">
        <el-button :icon="Refresh" :loading="loading" @click="loadAll">刷新</el-button>
        <el-button :icon="Warning" @click="router.push({ name: 'mistakes' })">错题本</el-button>
        <el-button type="primary" :disabled="!resume" @click="goResume">
          继续学习
          <el-icon class="el-icon--right"><ArrowRight /></el-icon>
        </el-button>
      </div>
    </div>

    <el-alert v-if="error" type="error" :closable="false" show-icon :title="error" class="p15-alert" />

    <div v-if="resume" class="resume-banner">
      <div class="resume-main">
        <span class="resume-kicker">上次停在这里</span>
        <strong>{{ resume.courseTitle }} · {{ resume.knowledgePointTitle }}</strong>
        <span class="resume-meta">
          {{ resume.chapterTitle || '未分章' }} · {{ stageLabels[resume.currentStage] || resume.currentStage }}
          <template v-if="resume.hasDraft"> · 有未提交草稿</template>
          · {{ fromNow(resume.updatedAt) }}
        </span>
      </div>
      <el-button type="primary" plain size="small" @click="goResume">回到教室</el-button>
    </div>

    <section class="ml-section">
      <div class="ml-section-head">
        <h3 class="ml-section-title">总览</h3>
        <span class="ml-section-note">累计有效学习时间已排除空闲与离线时段</span>
      </div>
      <div v-loading="loading" class="overview-grid">
        <div v-for="item in overviewMetrics" :key="item.label" class="overview-cell">
          <p class="overview-label">{{ item.label }}</p>
          <p class="overview-value">{{ item.value }}</p>
          <p class="overview-note">{{ item.note }}</p>
        </div>
        <div v-if="!overviewMetrics.length" class="ml-muted">暂无数据</div>
      </div>
    </section>

    <section class="ml-section">
      <div class="ml-section-head">
        <h3 class="ml-section-title">本周学习报告</h3>
        <span class="ml-section-note">
          统计事实：本周有效学习、涉及与完成的知识点
        </span>
      </div>
      <div class="report-grid">
        <div class="report-stat">
          <span class="report-label">本周学习时间</span>
          <strong>{{ formatDuration(report?.weekSeconds ?? 0) }}</strong>
          <span class="ml-muted">来自本周学习活动</span>
        </div>
        <div class="report-stat">
          <span class="report-label">本周涉及知识点</span>
          <strong>{{ report?.weekStudiedPoints ?? 0 }}</strong>
          <span class="ml-muted">进入过学习教室</span>
        </div>
        <div class="report-stat">
          <span class="report-label">本周完成知识点</span>
          <strong>{{ report?.weekCompletedPoints ?? 0 }}</strong>
          <span class="ml-muted">独立验证通过</span>
        </div>
      </div>

      <div class="report-columns">
        <div class="report-block">
          <div class="report-block-head">
            <h4>当前主要薄弱点</h4>
            <RouterLink :to="{ name: 'mistakes' }" class="ml-muted">去错题本</RouterLink>
          </div>
          <ul v-if="weakPoints.length" class="simple-list">
            <li v-for="item in weakPoints.slice(0, 5)" :key="item.mistakeId" class="simple-row">
              <div class="simple-main">
                <span class="simple-title">{{ item.pointTitle }}</span>
                <span class="simple-note">{{ item.courseTitle }} · {{ item.errorType ? errorTypeLabels[item.errorType] ?? item.errorType : item.stage }}</span>
              </div>
              <span class="simple-count">×{{ item.occurrenceCount }}</span>
            </li>
          </ul>
          <p v-else class="ml-muted">本周没有记录到错误，继续保持。</p>
        </div>

        <div class="report-block">
          <div class="report-block-head">
            <h4>最近取得的学习进展</h4>
            <span class="ml-muted">掌握状态变化</span>
          </div>
          <ul v-if="recentProgress.length" class="simple-list">
            <li v-for="item in recentProgress.slice(0, 5)" :key="`${item.pointId}-${item.createdAt}`" class="simple-row">
              <div class="simple-main">
                <span class="simple-title">{{ item.pointTitle }}</span>
                <span class="simple-note">{{ item.courseTitle }} · {{ fromNow(item.createdAt) }}</span>
              </div>
              <span class="progress-shift">
                <span class="mastery-pill" :class="masteryClass(item.fromState)">{{ item.fromLabel }}</span>
                <span class="ml-muted">→</span>
                <span class="mastery-pill" :class="masteryClass(item.toState)">{{ item.toLabel }}</span>
              </span>
            </li>
          </ul>
          <p v-else class="ml-muted">还没有掌握状态变化记录。</p>
        </div>
      </div>

      <div v-if="report?.courseReport" class="course-report">
        <div class="report-block-head">
          <h4>{{ report.courseReport.title }} · 课程报告</h4>
          <span class="ml-muted">进度 {{ report.courseReport.progress }}%</span>
        </div>
        <div class="course-report-chapters">
          <div v-for="chapter in report.courseReport.chapters" :key="chapter.chapterId" class="chapter-line">
            <span class="chapter-title">{{ chapter.title }}</span>
            <el-progress :percentage="chapter.progress" :stroke-width="5" :show-text="false" class="chapter-progress" />
            <span class="chapter-count">{{ chapter.completedPoints }}/{{ chapter.knowledgePointCount }}</span>
          </div>
        </div>
      </div>
    </section>

    <section class="ml-section">
      <div class="ml-section-head">
        <h3 class="ml-section-title">课程学习进度</h3>
        <el-select v-model="courseFilter" size="small" clearable placeholder="全部课程" class="filter-select">
          <el-option v-for="course in courseOptions" :key="course.id" :label="course.title" :value="course.id" />
        </el-select>
      </div>
      <div v-if="courses.length" class="course-list">
        <button
          v-for="course in courses"
          :key="course.courseId"
          type="button"
          class="course-row"
          @click="goCourse(course.courseId)"
        >
          <span class="course-icon" aria-hidden="true">{{ course.icon || '📘' }}</span>
          <span class="course-body">
            <span class="course-title">{{ course.title }}</span>
            <span class="course-meta">
              {{ course.chapterCount }} 章 · {{ course.knowledgePointCount }} 个知识点 · 已完成
              {{ course.completedPoints }} · 学习中 {{ course.inProgressPoints }} · 待复习
              {{ course.needsReviewPoints }}
            </span>
            <span class="course-position">
              {{
                course.currentPosition
                  ? `当前位置：${course.currentPosition.chapterTitle} / ${course.currentPosition.title}`
                  : '尚未开始'
              }}
              <template v-if="course.lastStudiedAt"> · {{ fromNow(course.lastStudiedAt) }}</template>
            </span>
          </span>
          <span class="course-progress">
            <el-progress :percentage="course.progress" :stroke-width="5" :show-text="false" />
            <span class="course-percent">{{ course.progress }}%</span>
          </span>
          <el-button
            size="small"
            type="primary"
            plain
            @click.stop="continueCourse(course)"
          >
            {{ course.currentPosition ? '继续' : '开始' }}
          </el-button>
        </button>
      </div>
      <p v-else class="ml-muted">还没有课程，先去课程中心导入一份教材。</p>
    </section>

    <section class="ml-section">
      <div class="ml-section-head">
        <h3 class="ml-section-title">知识掌握情况</h3>
        <span class="ml-section-note">仅由讲解、检查、陪练、验证等真实事件推进</span>
      </div>
      <div v-if="masteryHasData" class="mastery-wrap">
        <div class="mastery-bar" role="img" aria-label="掌握状态分布">
          <span
            v-for="item in masteryBar.filter((entry) => entry.count > 0)"
            :key="item.state"
            class="mastery-seg"
            :class="item.className"
            :style="{ width: `${Math.max(item.percent, 2)}%` }"
            :title="`${item.label} ${item.count} 个`"
          />
        </div>
        <div class="mastery-legend">
          <span v-for="item in masteryBar" :key="item.state" class="legend-item">
            <i class="legend-dot" :class="item.className" />
            {{ item.label }}
            <strong>{{ item.count }}</strong>
          </span>
        </div>
      </div>

      <div v-if="mastery?.courses.length" class="mastery-courses">
        <div v-for="course in mastery.courses" :key="course.courseId" class="mastery-course">
          <div class="mastery-course-head">
            <button type="button" class="link-button" @click="goCourse(course.courseId)">
              {{ course.title }}
            </button>
            <span class="ml-muted">{{ course.chapters.length }} 章</span>
          </div>
          <div v-for="chapter in course.chapters" :key="chapter.chapterId" class="mastery-chapter">
            <p class="mastery-chapter-title">{{ chapter.title }}</p>
            <div class="mastery-points">
              <span
                v-for="point in chapter.points"
                :key="point.pointId"
                class="mastery-point"
                :class="masteryClass(point.masteryState)"
                :title="point.lastReason || point.masteryLabel"
              >
                <i class="legend-dot" :class="masteryClass(point.masteryState)" />
                {{ point.title }}
                <em>{{ point.masteryLabel }}</em>
              </span>
            </div>
          </div>
        </div>
      </div>
      <p v-else class="ml-muted">还没有知识点。</p>
    </section>

    <section class="ml-section">
      <div class="ml-section-head">
        <h3 class="ml-section-title">最近学习历史</h3>
        <button type="button" class="link-button" @click="loadHistoryPage(historyPage)">刷新</button>
      </div>
      <el-table
        v-loading="historyLoading"
        :data="history.items"
        size="small"
        class="history-table"
        @row-click="onRowClick"
      >
        <el-table-column label="时间" width="120">
          <template #default="{ row }">{{ formatDateTime(row.startedAt) }}</template>
        </el-table-column>
        <el-table-column label="课程" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.courseTitle }}</template>
        </el-table-column>
        <el-table-column label="知识点" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.pointTitle }}</template>
        </el-table-column>
        <el-table-column label="有效时长" width="100">
          <template #default="{ row }">{{ formatDuration(row.activeSeconds) }}</template>
        </el-table-column>
        <el-table-column label="到达阶段" width="100">
          <template #default="{ row }">{{ stageLabels[row.finalStage] || row.finalStage }}</template>
        </el-table-column>
        <el-table-column label="结果" width="90">
          <template #default="{ row }">
            <span class="result-pill" :class="`is-${row.result}`">{{ resultLabels[row.result] || row.result }}</span>
          </template>
        </el-table-column>
      </el-table>
      <div class="history-foot">
        <el-pagination
          layout="prev, pager, next"
          :current-page="historyPage"
          :page-size="10"
          :total="history.total"
          @current-change="loadHistoryPage"
        />
        <span class="ml-muted">共 {{ history.total }} 次学习活动，从第 {{ historyFrom }} 条开始</span>
      </div>
    </section>

    <el-drawer v-model="detailOpen" size="620px" title="学习过程详情">
      <div v-loading="detailLoading" class="detail-body">
        <template v-if="detail">
          <div class="detail-head">
            <h3>{{ detail.activity.pointTitle }}</h3>
            <p class="ml-muted">
              {{ detail.activity.courseTitle }} · {{ detail.activity.chapterTitle }} ·
              {{ formatDateTime(detail.activity.startedAt) }}
            </p>
            <div class="detail-stats">
              <span><Clock class="detail-icon" />{{ formatDuration(detail.activity.activeSeconds) }}</span>
              <span><Collection class="detail-icon" />{{ detail.activity.completedStages.length }} 个阶段</span>
              <span><EditPen class="detail-icon" />{{ detail.activity.checkAttempts + detail.activity.pairAttempts + detail.activity.verifyAttempts }} 次尝试</span>
            </div>
          </div>

          <el-timeline v-if="detail.events.length" class="detail-timeline">
            <el-timeline-item
              v-for="event in detail.events"
              :key="event.id"
              :timestamp="formatDateTime(event.createdAt)"
              placement="top"
            >
              <strong>{{ event.fromStage }} → {{ event.toStage }}</strong>
              <span class="ml-muted"> · {{ event.type }}</span>
              <p class="detail-event-detail">{{ event.detail }}</p>
            </el-timeline-item>
          </el-timeline>
          <p v-else class="ml-muted">这次活动没有阶段事件。</p>

          <div v-if="detail.evaluations.length" class="detail-block">
            <h4>问答与评价</h4>
            <div v-for="item in detail.evaluations" :key="item.id" class="qa-item">
              <p class="qa-question">{{ item.question || '（无题目记录）' }}</p>
              <p class="qa-answer">你的回答：{{ item.answer || '（未提交）' }}</p>
              <p class="qa-feedback">{{ item.result.feedback || item.result.reason }}</p>
              <span class="verdict-pill" :class="`is-${item.verdict}`">{{ item.verdict }}</span>
            </div>
          </div>

          <div v-if="detail.mistakes.length" class="detail-block">
            <h4>错误与补讲</h4>
            <div v-for="item in detail.mistakes" :key="item.id" class="qa-item">
              <p class="qa-question">{{ item.question }}</p>
              <p class="qa-answer">你的回答：{{ item.userAnswer }}</p>
              <p class="qa-feedback">{{ item.errorReason }}</p>
              <p class="qa-correction">{{ item.correction }}</p>
            </div>
          </div>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.p15-page.embedded {
  max-width: none;
  padding: 0;
}

.p15-alert {
  margin-bottom: 16px;
}

.resume-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 14px 16px;
  margin-bottom: 22px;
  border: 1px solid color-mix(in srgb, var(--ml-accent) 32%, transparent);
  border-radius: var(--ml-radius-lg);
  background: color-mix(in srgb, var(--ml-accent) 8%, transparent);
}

.resume-main {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.resume-kicker {
  font-size: 11.5px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ml-text-3);
}

.resume-main strong {
  font-size: 14px;
}

.resume-meta {
  color: var(--ml-text-3);
  font-size: 12.5px;
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  border: 1px solid var(--ml-border);
  border-radius: var(--ml-radius-lg);
  overflow: hidden;
  background: var(--ml-surface);
}

.overview-cell {
  padding: 16px 16px 14px;
  border-left: 1px solid var(--ml-border);
  min-height: 96px;
}

.overview-cell:first-child {
  border-left: none;
}

.overview-label {
  font-size: 12px;
  color: var(--ml-text-3);
}

.overview-value {
  margin-top: 6px;
  font-size: 20px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.overview-note {
  margin-top: 2px;
  font-size: 11.5px;
  color: var(--ml-text-3);
}

.report-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.report-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 14px 16px;
  border: 1px solid var(--ml-border);
  border-radius: var(--ml-radius);
  background: var(--ml-bg-soft);
}

.report-stat strong {
  font-size: 18px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.report-label {
  font-size: 12px;
  color: var(--ml-text-3);
}

.report-columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px;
  margin-top: 20px;
}

.report-block-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.report-block h4,
.detail-block h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--ml-text-2);
}

.simple-list {
  list-style: none;
  margin: 0;
  padding: 0;
  border-top: 1px solid var(--ml-border);
}

.simple-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 0;
  border-bottom: 1px solid var(--ml-border);
}

.simple-main {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.simple-title {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.simple-note {
  font-size: 11.5px;
  color: var(--ml-text-3);
}

.simple-count {
  font-size: 12px;
  color: var(--ml-warning);
  font-variant-numeric: tabular-nums;
}

.progress-shift {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.course-report {
  margin-top: 20px;
  padding-top: 14px;
  border-top: 1px solid var(--ml-border);
}

.course-report-chapters {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.chapter-line {
  display: grid;
  grid-template-columns: 150px 1fr 54px;
  align-items: center;
  gap: 12px;
  font-size: 12.5px;
}

.chapter-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chapter-count {
  text-align: right;
  color: var(--ml-text-3);
  font-variant-numeric: tabular-nums;
}

.filter-select {
  width: 180px;
}

.course-list {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--ml-border);
  border-radius: var(--ml-radius-lg);
  overflow: hidden;
  background: var(--ml-surface);
}

.course-row {
  display: flex;
  align-items: center;
  gap: 14px;
  width: 100%;
  padding: 13px 16px;
  border: none;
  border-top: 1px solid var(--ml-border);
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  font: inherit;
}

.course-row:first-child {
  border-top: none;
}

.course-row:hover {
  background: var(--ml-surface-2);
}

.course-icon {
  width: 26px;
  text-align: center;
  font-size: 17px;
}

.course-body {
  display: flex;
  flex-direction: column;
  gap: 1px;
  flex: 1;
  min-width: 0;
}

.course-title {
  font-size: 13.5px;
  font-weight: 600;
}

.course-meta,
.course-position {
  font-size: 11.5px;
  color: var(--ml-text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.course-progress {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 180px;
}

.course-progress :deep(.el-progress) {
  flex: 1;
}

.course-percent {
  width: 38px;
  text-align: right;
  font-size: 12px;
  color: var(--ml-text-2);
  font-variant-numeric: tabular-nums;
}

.mastery-wrap {
  padding-bottom: 16px;
}

.mastery-bar {
  display: flex;
  height: 8px;
  border-radius: 999px;
  overflow: hidden;
  background: var(--ml-surface-2);
}

.mastery-seg {
  display: block;
  height: 100%;
}

.mastery-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--ml-text-3);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.legend-item strong {
  color: var(--ml-text);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.legend-dot,
.mastery-seg {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ml-text-3);
}

.mastery-seg {
  border-radius: 0;
  height: 100%;
}

.is-not-started {
  background: var(--ml-text-3);
}
.is-introduced {
  background: #7c8db5;
}
.is-understanding {
  background: var(--ml-accent);
}
.is-guided {
  background: #c58a3c;
}
.is-independent {
  background: var(--ml-success);
}
.is-needs-review {
  background: var(--ml-warning);
}

.mastery-courses {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.mastery-course {
  border-top: 1px solid var(--ml-border);
  padding-top: 14px;
}

.mastery-course-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.link-button {
  padding: 0;
  border: none;
  background: none;
  color: var(--ml-accent);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}

.mastery-chapter {
  margin-top: 9px;
}

.mastery-chapter-title {
  font-size: 11.5px;
  color: var(--ml-text-3);
  margin-bottom: 5px;
}

.mastery-points {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.mastery-point {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border: 1px solid var(--ml-border);
  border-radius: 999px;
  font-size: 12px;
  color: var(--ml-text-2);
  background: var(--ml-bg-soft);
}

.mastery-point .legend-dot {
  width: 6px;
  height: 6px;
}

.mastery-point em {
  font-style: normal;
  font-size: 10.5px;
  color: var(--ml-text-3);
}

.mastery-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 11px;
  color: var(--ml-text-2);
  background: var(--ml-surface-2);
}

.mastery-pill::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.mastery-pill.is-not-started { color: var(--ml-text-3); }
.mastery-pill.is-introduced { color: #8b9cc4; }
.mastery-pill.is-understanding { color: var(--ml-accent); }
.mastery-pill.is-guided { color: #d39a4e; }
.mastery-pill.is-independent { color: var(--ml-success); }
.mastery-pill.is-needs-review { color: var(--ml-warning); }

.history-table {
  cursor: pointer;
}

.history-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 12px;
}

.result-pill,
.verdict-pill {
  display: inline-flex;
  align-items: center;
  padding: 0 7px;
  border-radius: 999px;
  font-size: 11px;
  border: 1px solid var(--ml-border);
  color: var(--ml-text-3);
  white-space: nowrap;
}

.result-pill.is-completed,
.verdict-pill.is-PASSED,
.verdict-pill.is-CORRECT {
  color: var(--ml-success);
  border-color: color-mix(in srgb, var(--ml-success) 38%, transparent);
}

.result-pill.is-interrupted,
.verdict-pill.is-FAILED,
.verdict-pill.is-INCORRECT,
.verdict-pill.is-NEEDS_REVIEW {
  color: var(--ml-warning);
  border-color: color-mix(in srgb, var(--ml-warning) 38%, transparent);
}

.verdict-pill.is-PARTIAL,
.verdict-pill.is-UNCLEAR {
  color: #d39a4e;
  border-color: color-mix(in srgb, #d39a4e 38%, transparent);
}

.detail-body {
  min-height: 160px;
}

.detail-head {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--ml-border);
}

.detail-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--ml-text-3);
}

.detail-stats span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.detail-icon {
  width: 13px;
  height: 13px;
}

.detail-timeline {
  margin-top: 18px;
  padding-left: 2px;
}

.detail-event-detail {
  margin-top: 2px;
  font-size: 12px;
  color: var(--ml-text-3);
}

.detail-block {
  margin-top: 20px;
  padding-top: 14px;
  border-top: 1px solid var(--ml-border);
}

.qa-item {
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid var(--ml-border);
  border-radius: var(--ml-radius);
  background: var(--ml-bg-soft);
  font-size: 12.5px;
}

.qa-question {
  font-weight: 600;
  color: var(--ml-text);
}

.qa-answer {
  margin-top: 4px;
  color: var(--ml-text-2);
}

.qa-feedback {
  margin-top: 4px;
  color: var(--ml-text-3);
}

.qa-correction {
  margin-top: 4px;
  color: var(--ml-success);
}

@media (max-width: 1200px) {
  .overview-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .overview-cell:nth-child(3n + 1) {
    border-left: none;
  }
  .overview-cell:nth-child(n + 4) {
    border-top: 1px solid var(--ml-border);
  }
}

@media (max-width: 900px) {
  .report-columns,
  .report-grid {
    grid-template-columns: 1fr;
  }
  .overview-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .overview-cell:nth-child(2n + 1) {
    border-left: none;
  }
  .overview-cell:nth-child(n + 3) {
    border-top: 1px solid var(--ml-border);
  }
  .course-progress {
    display: none;
  }
}
</style>

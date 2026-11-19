<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Delete,
  Document,
  Edit,
  Plus,
} from '@element-plus/icons-vue'

import { courseLibraryApi } from '@/api'
import { ApiError } from '@/api/client'
import type {
  Chapter,
  CourseDetail,
  CourseProgress,
  KnowledgePoint,
  KnowledgePointDetail,
  LearningStatus,
} from '@/api/types'
import {
  formatBytes,
  formatDateTime,
  formatRelative,
  countOf,
  STATUS_LABELS,
  STATUS_ORDER,
  statusLabel,
} from '@/utils/learning'
import { renderMarkdown } from '@/utils/markdown'

const route = useRoute()
const router = useRouter()

const courseId = computed(() => Number(route.params.id))

const course = ref<CourseDetail | null>(null)
const progress = ref<CourseProgress | null>(null)
const loading = ref(false)
const busy = ref(false)
const errorMessage = ref('')

const collapsed = ref<Set<number>>(new Set())
const selectedPointId = ref<number | null>(null)
const pointDetail = ref<KnowledgePointDetail | null>(null)
const pointLoading = ref(false)

const ICON_CHOICES = ['', '🐍', '🐳', '🦀', '📘', '⚙️', '🧩', '🌐', '🧪', '📦']

/* ---------- 弹窗状态 ---------- */
const courseOpen = ref(false)
const courseForm = ref({ title: '', description: '', icon: '' })
const chapterOpen = ref(false)
const chapterTarget = ref<Chapter | null>(null)
const chapterForm = ref({ title: '', description: '' })
const pointOpen = ref(false)
const pointTarget = ref<KnowledgePoint | null>(null)
const pointForm = ref({ title: '', description: '', content: '' })
const pointTab = ref<'edit' | 'preview'>('edit')
const saving = ref(false)

const breadcrumb = computed(() => pointDetail.value?.chapterTitle ?? '')
const renderedContent = computed(() => renderMarkdown(pointDetail.value?.content ?? ''))
const hasContent = computed(() => Boolean((pointDetail.value?.content ?? '').trim()))

/** 目录里所有知识点的扁平顺序，用于"继续学习"与上下翻页 */
const flatPoints = computed(() =>
  (course.value?.chapters ?? []).flatMap((chapter) =>
    chapter.knowledgePoints.map((point) => ({ point, chapterTitle: chapter.title })),
  ),
)

const statusCounters = computed(() =>
  STATUS_ORDER.map((status) => ({
    status,
    label: STATUS_LABELS[status],
    value: countOf(course.value?.statusCounts, status),
  })),
)

onMounted(() => void load())

watch(
  () => route.params.id,
  () => void load(),
)

async function load(): Promise<void> {
  const id = courseId.value
  if (!Number.isFinite(id)) {
    errorMessage.value = '课程地址无效'
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    course.value = await courseLibraryApi.detail(id)
    // 进度接口只用来看"最近学习"，失败不影响主流程
    progress.value = await courseLibraryApi.progress(id).catch(() => null)
    await pickInitialPoint()
  } catch (err) {
    errorMessage.value = err instanceof ApiError ? err.message : '加载课程失败'
  } finally {
    loading.value = false
  }
}

/** 优先选中 URL 指定的知识点，其次是最近学习的、第一个未完成的，最后是第一个 */
async function pickInitialPoint(): Promise<void> {
  const data = course.value
  if (!data) return
  const query = route.query.point
  const fromQuery = query ? Number(query) : NaN
  const recent = progress.value?.recent?.[0]?.pointId ?? null
  const firstOpen = flatPoints.value.find((item) => item.point.learningStatus !== 'completed')?.point.id ?? null
  const target =
    (Number.isFinite(fromQuery) && flatPoints.value.some((item) => item.point.id === fromQuery) ? fromQuery : null) ??
    (recent && flatPoints.value.some((item) => item.point.id === recent) ? recent : null) ??
    firstOpen ??
    flatPoints.value[0]?.point.id ??
    null
  if (target !== null) await selectPoint(target)
}

async function selectPoint(pointId: number): Promise<void> {
  selectedPointId.value = pointId
  // 自动展开所在章节
  const owner = course.value?.chapters.find((chapter) =>
    chapter.knowledgePoints.some((point) => point.id === pointId),
  )
  if (owner && collapsed.value.has(owner.id)) {
    const next = new Set(collapsed.value)
    next.delete(owner.id)
    collapsed.value = next
  }
  pointLoading.value = true
  try {
    pointDetail.value = await courseLibraryApi.point(pointId)
  } catch (err) {
    pointDetail.value = null
    ElMessage.error(err instanceof ApiError ? err.message : '加载知识点失败')
  } finally {
    pointLoading.value = false
  }
}

function toggleChapter(chapterId: number): void {
  const next = new Set(collapsed.value)
  if (next.has(chapterId)) next.delete(chapterId)
  else next.add(chapterId)
  collapsed.value = next
}

function requestError(err: unknown, fallback: string): void {
  ElMessage.error(err instanceof ApiError ? err.message : fallback)
}

async function refreshAfter(mutate: () => Promise<CourseDetail>, options: { keepPoint?: boolean } = {}): Promise<void> {
  busy.value = true
  try {
    course.value = await mutate()
    progress.value = await courseLibraryApi.progress(courseId.value).catch(() => progress.value)
    const stillThere = flatPoints.value.some((item) => item.point.id === selectedPointId.value)
    if (!stillThere) {
      const next = flatPoints.value[0]?.point.id ?? null
      if (next !== null) await selectPoint(next)
      else {
        selectedPointId.value = null
        pointDetail.value = null
      }
    } else if (options.keepPoint) {
      pointDetail.value = await courseLibraryApi.point(selectedPointId.value as number).catch(() => pointDetail.value)
    }
  } catch (err) {
    requestError(err, '操作失败')
  } finally {
    busy.value = false
  }
}

/* ---------------- 课程信息 ---------------- */

function openCourseEdit(): void {
  const data = course.value
  if (!data) return
  courseForm.value = { title: data.title, description: data.description, icon: data.icon ?? '' }
  courseOpen.value = true
}

async function saveCourse(): Promise<void> {
  const data = course.value
  if (!data) return
  const title = courseForm.value.title.trim()
  if (!title) {
    ElMessage.warning('课程名称不能为空')
    return
  }
  saving.value = true
  try {
    course.value = await courseLibraryApi.update(data.id, {
      title,
      description: courseForm.value.description,
      icon: courseForm.value.icon,
    })
    courseOpen.value = false
    ElMessage.success('课程信息已保存')
  } catch (err) {
    requestError(err, '保存失败')
  } finally {
    saving.value = false
  }
}

async function removeCourse(): Promise<void> {
  const data = course.value
  if (!data) return
  try {
    await ElMessageBox.confirm(
      `将删除「${data.title}」的 ${data.chapterCount} 个章节、${data.knowledgePointCount} 个知识点的全部学习状态，以及本地教材文件，无法恢复。`,
      '删除课程',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消', confirmButtonClass: 'el-button--danger' },
    )
  } catch {
    return
  }
  try {
    await courseLibraryApi.remove(data.id)
    ElMessage.success('课程已删除')
    await router.push({ name: 'courses' })
  } catch (err) {
    requestError(err, '删除失败')
  }
}

/* ---------------- 章节 ---------------- */

function openChapterDialog(chapter: Chapter | null): void {
  chapterTarget.value = chapter
  chapterForm.value = { title: chapter?.title ?? '', description: chapter?.description ?? '' }
  chapterOpen.value = true
}

async function saveChapter(): Promise<void> {
  const data = course.value
  if (!data) return
  const title = chapterForm.value.title.trim()
  if (!title) {
    ElMessage.warning('章节名称不能为空')
    return
  }
  const target = chapterTarget.value
  saving.value = true
  try {
    const payload = { title, description: chapterForm.value.description }
    await refreshAfter(() =>
      target
        ? courseLibraryApi.updateChapter(data.id, target.id, payload)
        : courseLibraryApi.addChapter(data.id, payload),
    )
    chapterOpen.value = false
    ElMessage.success(target ? '章节已更新' : '章节已添加')
  } finally {
    saving.value = false
  }
}

async function removeChapter(chapter: Chapter): Promise<void> {
  const data = course.value
  if (!data) return
  try {
    await ElMessageBox.confirm(
      `将删除章节「${chapter.title}」及其下 ${chapter.knowledgePoints.length} 个知识点的学习状态，无法恢复。`,
      '删除章节',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消', confirmButtonClass: 'el-button--danger' },
    )
  } catch {
    return
  }
  await refreshAfter(() => courseLibraryApi.removeChapter(data.id, chapter.id))
  ElMessage.success('章节已删除')
}

async function moveChapter(index: number, delta: number): Promise<void> {
  const data = course.value
  if (!data) return
  const ids = data.chapters.map((chapter) => chapter.id)
  const target = index + delta
  if (target < 0 || target >= ids.length) return
  ;[ids[index], ids[target]] = [ids[target], ids[index]]
  await refreshAfter(() => courseLibraryApi.reorderChapters(data.id, ids))
}

/* ---------------- 知识点 ---------------- */

function openPointDialog(chapter: Chapter, point: KnowledgePoint | null): void {
  chapterTarget.value = chapter
  pointTarget.value = point
  pointForm.value = {
    title: point?.title ?? '',
    description: point?.description ?? '',
    content: '',
  }
  pointTab.value = 'edit'
  pointOpen.value = true
  // 编辑已有知识点时，正文单独拉一次详情（列表接口不带正文）
  if (point) {
    void courseLibraryApi
      .point(point.id)
      .then((detail) => {
        if (pointTarget.value?.id === point.id) pointForm.value.content = detail.content
      })
      .catch(() => undefined)
  }
}

/** 阅读面板里的"编辑内容"：直接对当前打开的知识点打开编辑弹窗 */
function openPointInDialog(): void {
  const detail = pointDetail.value
  if (!detail) return
  const chapter = course.value?.chapters.find((item) => item.id === detail.chapterId)
  const point = chapter?.knowledgePoints.find((item) => item.id === detail.id)
  if (chapter && point) openPointDialog(chapter, point)
}

async function savePoint(): Promise<void> {  const data = course.value
  const chapter = chapterTarget.value
  if (!data || !chapter) return
  const title = pointForm.value.title.trim()
  if (!title) {
    ElMessage.warning('知识点名称不能为空')
    return
  }
  const target = pointTarget.value
  saving.value = true
  try {
    const payload = {
      title,
      description: pointForm.value.description,
      content: pointForm.value.content,
    }
    await refreshAfter(
      () =>
        target
          ? courseLibraryApi.updatePoint(data.id, target.id, payload)
          : courseLibraryApi.addPoint(data.id, chapter.id, payload),
      { keepPoint: Boolean(target) },
    )
    if (!target) {
      const created = flatPoints.value.filter((item) => item.point.chapterId === chapter.id).at(-1)
      if (created) await selectPoint(created.point.id)
    } else if (selectedPointId.value === target.id) {
      pointDetail.value = await courseLibraryApi.point(target.id).catch(() => pointDetail.value)
    }
    pointOpen.value = false
    ElMessage.success(target ? '知识点已保存' : '知识点已添加')
  } finally {
    saving.value = false
  }
}

async function removePoint(point: KnowledgePoint): Promise<void> {
  const data = course.value
  if (!data) return
  try {
    await ElMessageBox.confirm(`删除知识点「${point.title}」？其学习状态也会一并删除。`, '删除知识点', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return
  }
  await refreshAfter(() => courseLibraryApi.removePoint(data.id, point.id))
  ElMessage.success('知识点已删除')
}

async function movePoint(chapter: Chapter, index: number, delta: number): Promise<void> {
  const data = course.value
  if (!data) return
  const ids = chapter.knowledgePoints.map((point) => point.id)
  const target = index + delta
  if (target < 0 || target >= ids.length) return
  ;[ids[index], ids[target]] = [ids[target], ids[index]]
  await refreshAfter(() => courseLibraryApi.reorderPoints(data.id, chapter.id, ids), { keepPoint: true })
}

/* ---------------- 学习状态 ---------------- */

async function setStatus(status: LearningStatus): Promise<void> {
  if (status === 'completed') {
    enterClassroom()
    return
  }
  const data = course.value
  const point = pointDetail.value
  if (!data || !point || point.learningStatus === status) return
  busy.value = true
  try {
    course.value = await courseLibraryApi.setPointStatus(data.id, point.id, status)
    progress.value = await courseLibraryApi.progress(data.id).catch(() => progress.value)
    pointDetail.value = await courseLibraryApi.point(point.id).catch(() => pointDetail.value)
    ElMessage.success(`已标记为「${statusLabel(status)}」`)
  } catch (err) {
    requestError(err, '更新学习状态失败')
  } finally {
    busy.value = false
  }
}

async function goNeighbor(direction: 'prev' | 'next'): Promise<void> {
  const target = direction === 'prev' ? pointDetail.value?.previousId : pointDetail.value?.nextId
  if (target) await selectPoint(target)
}

function enterClassroom(): void {
  void router.push({
    name: 'classroom',
    params: { id: courseId.value },
    query: selectedPointId.value ? { point: String(selectedPointId.value) } : {},
  })
}

function masteryClass(state: string): string {
  return `is-${state.toLowerCase().replace(/_/g, '-')}`
}
</script>

<template>
  <div v-loading="loading" class="detail-page">
    <div v-if="errorMessage" class="ml-page">
      <div class="ml-empty">
        <h3>课程不可用</h3>
        <p>{{ errorMessage }}</p>
        <el-button type="primary" @click="router.push({ name: 'courses' })">返回课程中心</el-button>
      </div>
    </div>

    <template v-else-if="course">
      <!-- 头部 -->
      <header class="detail-head">
        <button class="back" type="button" @click="router.push({ name: 'courses' })">
          <el-icon :size="14"><ArrowLeft /></el-icon>
          课程中心
        </button>

        <div class="head-row">
          <div class="head-main">
            <h2 class="head-title">
              <span v-if="course.icon" class="head-icon">{{ course.icon }}</span>
              {{ course.title }}
            </h2>
            <p class="head-meta">
              <span>{{ course.sourceName }}</span>
              <span class="dot">·</span>
              <span>{{ course.sourceType === 'pdf' ? 'PDF' : 'Markdown' }} {{ formatBytes(course.sourceBytes) }}</span>
              <span class="dot">·</span>
              <span>{{ course.chapterCount }} 章 / {{ course.knowledgePointCount }} 知识点</span>
              <span class="dot">·</span>
              <span>创建于 {{ formatDateTime(course.createdAt) }}</span>
              <span class="dot">·</span>
              <span>最近学习 {{ formatRelative(course.lastStudiedAt) }}</span>
            </p>
            <p v-if="course.description" class="head-desc">{{ course.description }}</p>
          </div>
          <div class="head-actions">
            <el-button type="primary" :icon="ArrowRight" @click="enterClassroom">
              {{ course.progress ? '继续学习' : '开始学习' }}
            </el-button>
            <el-button :icon="Edit" @click="openCourseEdit">编辑课程</el-button>
            <el-button :icon="Delete" @click="removeCourse">删除</el-button>
          </div>
        </div>

        <el-alert
          v-for="warning in course.warnings"
          :key="warning"
          type="warning"
          :closable="false"
          show-icon
          :title="warning"
          class="detail-warning"
        />
      </header>

      <!-- 进度概览 -->
      <section class="overview">
        <div class="overview-main">
          <div class="overview-head">
            <span class="overview-label">学习进度</span>
            <span class="overview-progress">{{ course.progress }}%</span>
            <span class="ml-muted overview-formula">
              按状态加权：学习中 0.4 · 待复习 0.7 · 已完成 1
            </span>
          </div>
          <div class="overview-track"><div class="overview-fill" :style="{ width: `${course.progress}%` }" /></div>
          <div class="counters">
            <div v-for="item in statusCounters" :key="item.status" class="counter">
              <span class="ml-status" :class="`is-${item.status.replace('_', '-')}`">{{ item.label }}</span>
              <span class="counter-value">{{ item.value }}</span>
            </div>
          </div>
        </div>

        <div class="recent">
          <p class="recent-title">最近学习</p>
          <ul v-if="progress?.recent?.length" class="recent-list">
            <li v-for="item in progress.recent.slice(0, 3)" :key="item.pointId">
              <button type="button" class="recent-item" @click="selectPoint(item.pointId)">
                <span class="recent-name">{{ item.title }}</span>
                <span class="recent-time">{{ formatRelative(item.lastStudiedAt) }}</span>
              </button>
            </li>
          </ul>
          <p v-else class="recent-empty">还没有学习记录，打开任意知识点并标记状态即可开始记录。</p>
        </div>
      </section>

      <!-- 目录 + 阅读面板 -->
      <div class="workspace">
        <aside class="toc">
          <header class="toc-head">
            <span>课程目录</span>
            <el-button link type="primary" :icon="Plus" @click="openChapterDialog(null)">新增章节</el-button>
          </header>

          <div v-if="!course.chapters.length" class="toc-empty">
            还没有章节，先新增一个再添加知识点。
          </div>

          <article v-for="(chapter, chapterIndex) in course.chapters" :key="chapter.id" class="toc-chapter">
            <div class="chapter-row">
              <button type="button" class="chapter-toggle" @click="toggleChapter(chapter.id)">
                <span class="chevron" :class="{ open: !collapsed.has(chapter.id) }">›</span>
                <span class="chapter-index">{{ String(chapterIndex + 1).padStart(2, '0') }}</span>
                <span class="chapter-title">{{ chapter.title }}</span>
                <span class="chapter-meta">{{ chapter.knowledgePoints.length }} 点 · {{ chapter.progress }}%</span>
              </button>
              <div class="row-tools">
                <el-button
                  link
                  :icon="ArrowUp"
                  :disabled="chapterIndex === 0"
                  title="上移章节"
                  @click="moveChapter(chapterIndex, -1)"
                />
                <el-button
                  link
                  :icon="ArrowDown"
                  :disabled="chapterIndex === course.chapters.length - 1"
                  title="下移章节"
                  @click="moveChapter(chapterIndex, 1)"
                />
                <el-button link :icon="Plus" title="添加知识点" @click="openPointDialog(chapter, null)" />
                <el-button link :icon="Edit" title="编辑章节" @click="openChapterDialog(chapter)" />
                <el-button link type="danger" :icon="Delete" title="删除章节" @click="removeChapter(chapter)" />
              </div>
            </div>

            <p v-if="chapter.description && !collapsed.has(chapter.id)" class="chapter-desc">
              {{ chapter.description }}
            </p>

            <ul v-if="!collapsed.has(chapter.id)" class="point-list">
              <li
                v-for="(point, pointIndex) in chapter.knowledgePoints"
                :key="point.id"
                class="point-row"
                :class="{ active: point.id === selectedPointId }"
              >
                <button type="button" class="point-main" @click="selectPoint(point.id)">
                  <span class="point-dot" :class="`is-${point.learningStatus.replace('_', '-')}`" />
                  <span class="point-title">{{ point.title }}</span>
                  <span
                    v-if="point.masteryState !== 'NOT_STARTED'"
                    class="point-mastery"
                    :class="masteryClass(point.masteryState)"
                  >{{ point.masteryLabel }}</span>
                  <span class="point-status">{{ statusLabel(point.learningStatus) }}</span>
                </button>
                <div class="row-tools">
                  <el-button
                    link
                    :icon="ArrowUp"
                    :disabled="pointIndex === 0"
                    title="上移知识点"
                    @click="movePoint(chapter, pointIndex, -1)"
                  />
                  <el-button
                    link
                    :icon="ArrowDown"
                    :disabled="pointIndex === chapter.knowledgePoints.length - 1"
                    title="下移知识点"
                    @click="movePoint(chapter, pointIndex, 1)"
                  />
                  <el-button link :icon="Edit" title="编辑知识点" @click="openPointDialog(chapter, point)" />
                  <el-button link type="danger" :icon="Delete" title="删除知识点" @click="removePoint(point)" />
                </div>
              </li>
              <li v-if="!chapter.knowledgePoints.length" class="point-empty">
                这个章节还没有知识点，
                <button type="button" class="link-button" @click="openPointDialog(chapter, null)">添加一个</button>
              </li>
            </ul>
          </article>
        </aside>

        <section v-loading="pointLoading" class="reader">
          <template v-if="pointDetail">
            <div class="reader-head">
              <p class="reader-crumb">
                <el-icon :size="12"><Document /></el-icon>
                {{ breadcrumb }}
              </p>
              <h3 class="reader-title">{{ pointDetail.title }}</h3>
              <p class="reader-meta">
                <span>第 {{ pointDetail.sortOrder + 1 }} 个知识点</span>
                <span v-if="pointDetail.codeCount" class="dot">·</span>
                <span v-if="pointDetail.codeCount">{{ pointDetail.codeCount }} 个代码块</span>
                <span class="dot">·</span>
                <span>最近学习 {{ formatRelative(pointDetail.lastStudiedAt) }}</span>
              </p>
              <p v-if="pointDetail.description" class="reader-desc">{{ pointDetail.description }}</p>
            </div>

            <div class="status-bar">
              <span class="status-bar-label">学习状态</span>
              <div class="status-switch">
                <button
                  v-for="status in STATUS_ORDER"
                  :key="status"
                  type="button"
                  class="status-button"
                  :class="[`is-${status.replace('_', '-')}`, { active: pointDetail.learningStatus === status }]"
                  :disabled="busy"
                  @click="setStatus(status)"
                >
                  {{ status === 'completed' ? '进入教学验证' : STATUS_LABELS[status] }}
                </button>
              </div>
              <div class="status-bar-actions">
                <el-button link :icon="Edit" @click="openPointInDialog">编辑内容</el-button>
              </div>
            </div>

            <p v-if="pointDetail.completionSource === 'legacy_manual'" class="reader-desc">历史手工完成记录已保留；尚未通过本轮教学验证。</p>
            <div v-if="hasContent" class="md-body reader-body" v-html="renderedContent" />
            <div v-else class="reader-empty">
              <p>这个知识点还没有正文。教材导入时它只有标题，或者你删掉了正文。</p>
              <el-button :icon="Edit" @click="openPointInDialog">补充正文</el-button>
            </div>

            <footer class="reader-foot">
              <el-button :icon="ArrowLeft" :disabled="!pointDetail.previousId" @click="goNeighbor('prev')">
                上一个
              </el-button>
              <el-button :disabled="!pointDetail.nextId" @click="goNeighbor('next')">
                下一个
                <el-icon class="el-icon--right"><ArrowRight /></el-icon>
              </el-button>
            </footer>
          </template>

          <div v-else class="reader-empty">
            <p>从左侧目录选择一个知识点开始阅读。</p>
          </div>
        </section>
      </div>
    </template>

    <!-- 编辑课程 -->
    <el-dialog v-model="courseOpen" title="编辑课程" width="560px" :close-on-click-modal="false">
      <el-form label-position="top">
        <el-form-item label="课程名称">
          <el-input v-model="courseForm.title" maxlength="200" show-word-limit />
        </el-form-item>
        <el-form-item label="课程简介">
          <el-input v-model="courseForm.description" type="textarea" :rows="3" maxlength="2000" show-word-limit />
        </el-form-item>
        <el-form-item label="课程图标">
          <div class="icon-picker">
            <button
              v-for="choice in ICON_CHOICES"
              :key="choice || 'default'"
              type="button"
              class="icon-option"
              :class="{ active: courseForm.icon === choice }"
              @click="courseForm.icon = choice"
            >
              {{ choice || (course?.sourceType === 'pdf' ? 'PDF' : 'MD') }}
            </button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="courseOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveCourse">保存</el-button>
      </template>
    </el-dialog>

    <!-- 新增/编辑章节 -->
    <el-dialog
      v-model="chapterOpen"
      :title="chapterTarget ? '编辑章节' : '新增章节'"
      width="520px"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <el-form-item label="章节名称">
          <el-input v-model="chapterForm.title" maxlength="200" show-word-limit />
        </el-form-item>
        <el-form-item label="章节简介（可选）">
          <el-input v-model="chapterForm.description" type="textarea" :rows="3" maxlength="2000" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="chapterOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveChapter">
          {{ chapterTarget ? '保存' : '添加' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 新增/编辑知识点 -->
    <el-dialog
      v-model="pointOpen"
      :title="pointTarget ? '编辑知识点' : '新增知识点'"
      width="760px"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <div class="form-row">
          <el-form-item label="知识点名称" class="grow">
            <el-input v-model="pointForm.title" maxlength="200" show-word-limit />
          </el-form-item>
          <el-form-item label="所属章节" class="fixed">
            <el-input :model-value="chapterTarget?.title ?? ''" disabled />
          </el-form-item>
        </div>
        <el-form-item label="简介（可选）">
          <el-input v-model="pointForm.description" type="textarea" :rows="2" maxlength="2000" show-word-limit />
        </el-form-item>
        <el-form-item label="正文（支持 Markdown）">
          <div class="editor-tabs">
            <button type="button" :class="{ active: pointTab === 'edit' }" @click="pointTab = 'edit'">编辑</button>
            <button type="button" :class="{ active: pointTab === 'preview' }" @click="pointTab = 'preview'">预览</button>
          </div>
          <el-input
            v-if="pointTab === 'edit'"
            v-model="pointForm.content"
            type="textarea"
            :rows="14"
            class="content-input"
            placeholder="支持标题、列表、代码围栏（```python）、表格、引用与链接"
          />
          <div v-else class="md-body preview-body" v-html="renderMarkdown(pointForm.content)" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pointOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="savePoint">
          {{ pointTarget ? '保存' : '添加' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>


<style scoped>
.detail-page {
  max-width: 1440px;
  padding: 26px 32px 72px;
}

/* ---------- 头部 ---------- */
.detail-head {
  padding-bottom: 16px;
  border-bottom: 1px solid var(--ml-border);
}

.back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 12px;
  padding: 0;
  border: none;
  background: none;
  color: var(--ml-text-3);
  font-family: inherit;
  font-size: 12.5px;
  cursor: pointer;
}

.back:hover {
  color: var(--ml-accent);
}

.head-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
}

.head-main {
  min-width: 0;
}

.head-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 22px;
  line-height: 1.3;
}

.head-icon {
  font-size: 19px;
}

.head-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px;
  margin-top: 8px;
  font-size: 12.5px;
  color: var(--ml-text-3);
}

.head-desc {
  margin-top: 10px;
  max-width: 80ch;
  font-size: 13px;
  color: var(--ml-text-2);
  line-height: 1.7;
}

.head-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.detail-warning {
  margin-top: 12px;
}

.dot {
  margin: 0 6px;
  color: var(--ml-border-strong);
}

/* ---------- 进度概览 ---------- */
.overview {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 28px;
  margin-top: 18px;
  padding: 16px 18px;
  border: 1px solid var(--ml-border);
  border-radius: var(--ml-radius-lg);
  background: var(--ml-bg-soft);
}

.overview-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.overview-label {
  font-size: 12px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--ml-text-3);
}

.overview-progress {
  font-family: var(--ml-font-mono);
  font-size: 20px;
  font-weight: 600;
  color: var(--ml-text);
}

.overview-formula {
  margin-left: auto;
  font-size: 11.5px;
}

.overview-track {
  height: 6px;
  margin-top: 10px;
  border-radius: 3px;
  background: var(--ml-surface-3);
  overflow: hidden;
}

.overview-fill {
  height: 100%;
  border-radius: 3px;
  background: var(--ml-accent);
  transition: width 0.2s ease;
}

.counters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 22px;
  margin-top: 12px;
}

.counter {
  display: flex;
  align-items: center;
  gap: 6px;
}

.counter-value {
  font-family: var(--ml-font-mono);
  font-size: 13px;
  color: var(--ml-text);
}

.recent {
  padding-left: 24px;
  border-left: 1px solid var(--ml-border);
}

.recent-title {
  font-size: 12px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--ml-text-3);
}

.recent-list {
  list-style: none;
  margin: 6px 0 0;
  padding: 0;
  display: grid;
  gap: 2px;
}

.recent-item {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  padding: 3px 0;
  border: none;
  background: none;
  font-family: inherit;
  font-size: 12.5px;
  color: var(--ml-text-2);
  text-align: left;
  cursor: pointer;
}

.recent-item:hover .recent-name {
  color: var(--ml-accent);
}

.recent-name {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.recent-time {
  flex-shrink: 0;
  font-size: 11.5px;
  color: var(--ml-text-3);
}

.recent-empty {
  margin-top: 6px;
  font-size: 12px;
  color: var(--ml-text-3);
  line-height: 1.7;
}

/* ---------- 目录 + 阅读面板 ---------- */
.workspace {
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr);
  gap: 24px;
  margin-top: 22px;
  align-items: start;
}

.toc {
  position: sticky;
  top: 68px;
  max-height: calc(100vh - 100px);
  overflow: auto;
  padding-right: 6px;
}

.toc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--ml-border);
  font-size: 12px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--ml-text-3);
}

.toc-empty {
  padding: 18px 0;
  font-size: 12.5px;
  color: var(--ml-text-3);
}

.toc-chapter {
  border-bottom: 1px solid var(--ml-border);
}

.chapter-row {
  display: flex;
  align-items: center;
  gap: 4px;
}

.chapter-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
  padding: 10px 2px;
  border: none;
  background: none;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}

.chapter-toggle:hover .chapter-title {
  color: var(--ml-accent);
}

.chevron {
  flex-shrink: 0;
  width: 12px;
  color: var(--ml-text-3);
  transition: transform 0.15s ease;
}

.chevron.open {
  transform: rotate(90deg);
}

.chapter-index {
  flex-shrink: 0;
  font-family: var(--ml-font-mono);
  font-size: 11.5px;
  color: var(--ml-text-3);
}

.chapter-title {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 550;
  color: var(--ml-text);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.chapter-meta {
  flex-shrink: 0;
  font-size: 11.5px;
  color: var(--ml-text-3);
}

.chapter-desc {
  margin: -2px 0 8px 22px;
  font-size: 12px;
  color: var(--ml-text-3);
  line-height: 1.6;
}

.row-tools {
  display: flex;
  flex-shrink: 0;
  gap: 0;
  opacity: 0.28;
  transition: opacity 0.12s ease;
}

.chapter-row:hover .row-tools,
.point-row:hover .row-tools {
  opacity: 1;
}

.row-tools :deep(.el-button) {
  padding: 4px;
  height: 22px;
}

.point-list {
  list-style: none;
  margin: 0 0 10px;
  padding: 0 0 0 14px;
  display: grid;
  gap: 1px;
}

.point-row {
  display: flex;
  align-items: center;
  gap: 4px;
  border-radius: var(--ml-radius-sm);
}

.point-row:hover {
  background: var(--ml-surface);
}

.point-row.active {
  background: var(--ml-surface-2);
}

.point-main {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
  padding: 6px 8px;
  border: none;
  background: none;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}

.point-dot {
  flex-shrink: 0;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ml-border-strong);
}

.point-dot.is-in-progress {
  background: var(--ml-accent);
}

.point-dot.is-review {
  background: var(--ml-warning);
}

.point-dot.is-completed {
  background: var(--ml-success);
}

.point-title {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  color: var(--ml-text-2);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.point-row.active .point-title {
  color: var(--ml-text);
  font-weight: 550;
}

.point-mastery {
  flex-shrink: 0;
  padding: 0 6px;
  border-radius: 999px;
  border: 1px solid var(--ml-border);
  font-size: 10.5px;
  color: var(--ml-text-3);
  white-space: nowrap;
}

.point-mastery.is-introduced { color: #8b9cc4; }
.point-mastery.is-understanding { color: var(--ml-accent); border-color: color-mix(in srgb, var(--ml-accent) 36%, transparent); }
.point-mastery.is-guided-practice { color: #d39a4e; }
.point-mastery.is-independent { color: var(--ml-success); border-color: color-mix(in srgb, var(--ml-success) 36%, transparent); }
.point-mastery.is-needs-review { color: var(--ml-warning); border-color: color-mix(in srgb, var(--ml-warning) 36%, transparent); }

.point-status {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--ml-text-3);
}

.point-empty {
  margin: 0 0 10px 22px;
  font-size: 12.5px;
  color: var(--ml-text-3);
}

.link-button {
  padding: 0;
  border: none;
  background: none;
  color: var(--ml-accent);
  font-family: inherit;
  font-size: inherit;
  cursor: pointer;
}

/* ---------- 阅读面板 ---------- */
.reader {
  min-height: 320px;
  padding: 0 0 0 26px;
  border-left: 1px solid var(--ml-border);
}

.reader-head {
  padding-bottom: 14px;
  border-bottom: 1px solid var(--ml-border);
}

.reader-crumb {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ml-text-3);
}

.reader-title {
  margin-top: 8px;
  font-size: 19px;
  line-height: 1.4;
}

.reader-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  margin-top: 6px;
  font-size: 12px;
  color: var(--ml-text-3);
}

.reader-desc {
  margin-top: 8px;
  font-size: 13px;
  color: var(--ml-text-2);
  line-height: 1.7;
}

.status-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 12px 0;
  border-bottom: 1px solid var(--ml-border);
}

.status-bar-label {
  font-size: 12px;
  color: var(--ml-text-3);
}

.status-switch {
  display: flex;
  gap: 4px;
  padding: 2px;
  border-radius: 999px;
  border: 1px solid var(--ml-border);
  background: var(--ml-bg-soft);
}

.status-button {
  padding: 3px 12px;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: var(--ml-text-3);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
  transition: background-color 0.12s ease, color 0.12s ease;
}

.status-button:hover {
  color: var(--ml-text);
}

.status-button.active.is-not-started {
  background: var(--ml-surface-3);
  color: var(--ml-text);
}

.status-button.active.is-in-progress {
  background: color-mix(in srgb, var(--ml-accent) 18%, transparent);
  color: var(--ml-accent);
}

.status-button.active.is-review {
  background: color-mix(in srgb, var(--ml-warning) 18%, transparent);
  color: var(--ml-warning);
}

.status-button.active.is-completed {
  background: color-mix(in srgb, var(--ml-success) 18%, transparent);
  color: var(--ml-success);
}

.status-bar-actions {
  margin-left: auto;
}

.reader-body {
  padding: 18px 0 8px;
  max-width: 84ch;
}

.reader-empty {
  padding: 40px 0;
  text-align: center;
  font-size: 13px;
  color: var(--ml-text-3);
}

.reader-empty p {
  margin-bottom: 12px;
}

.reader-foot {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--ml-border);
}

/* ---------- 弹窗内的小部件 ---------- */
.icon-picker {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.icon-option {
  width: 34px;
  height: 34px;
  border-radius: var(--ml-radius);
  border: 1px solid var(--ml-border);
  background: var(--ml-bg-soft);
  color: var(--ml-text-2);
  font-family: var(--ml-font-mono);
  font-size: 14px;
  cursor: pointer;
}

.icon-option:hover {
  border-color: var(--ml-border-strong);
}

.icon-option.active {
  border-color: var(--ml-accent);
  background: var(--ml-accent-weak);
  color: var(--ml-text);
}

.form-row {
  display: flex;
  gap: 16px;
}

.form-row .grow {
  flex: 1;
}

.form-row .fixed {
  width: 200px;
}

.editor-tabs {
  display: flex;
  gap: 2px;
  margin-bottom: 8px;
}

.editor-tabs button {
  padding: 3px 12px;
  border: 1px solid var(--ml-border);
  border-radius: var(--ml-radius-sm);
  background: transparent;
  color: var(--ml-text-3);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
}

.editor-tabs button.active {
  border-color: var(--ml-accent);
  background: var(--ml-accent-weak);
  color: var(--ml-text);
}

.content-input :deep(.el-textarea__inner) {
  font-family: var(--ml-font-mono);
  font-size: 12.5px;
  line-height: 1.7;
}

.preview-body {
  width: 100%;
  min-height: 240px;
  max-height: 420px;
  overflow: auto;
  padding: 12px 14px;
  border: 1px solid var(--ml-border);
  border-radius: var(--ml-radius);
  background: var(--ml-bg-soft);
}

@media (max-width: 1200px) {
  .workspace {
    grid-template-columns: minmax(0, 1fr);
  }

  .toc {
    position: static;
    max-height: none;
  }

  .reader {
    padding-left: 0;
    border-left: none;
    border-top: 1px solid var(--ml-border);
    padding-top: 18px;
  }

  .overview {
    grid-template-columns: minmax(0, 1fr);
  }

  .recent {
    padding-left: 0;
    border-left: none;
    border-top: 1px solid var(--ml-border);
    padding-top: 12px;
  }
}
</style>

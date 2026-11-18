<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Document, Edit, Reading, Search, UploadFilled } from '@element-plus/icons-vue'

import { courseLibraryApi } from '@/api'
import { ApiError } from '@/api/client'
import type { CourseSort, CourseSummary } from '@/api/types'
import { useCourseStore } from '@/stores/courses'
import { formatBytes, formatDateTime, formatRelative, countOf, STATUS_LABELS, STATUS_ORDER } from '@/utils/learning'

const store = useCourseStore()
const router = useRouter()

const SORT_OPTIONS: { value: CourseSort; label: string }[] = [
  { value: 'studied', label: '最近学习' },
  { value: 'created', label: '创建时间' },
  { value: 'updated', label: '最近更新' },
]

const ICON_CHOICES = ['', '🐍', '🐳', '🦀', '📘', '⚙️', '🧩', '🌐', '🧪', '📦']

const editing = ref<CourseSummary | null>(null)
const editOpen = ref(false)
const saving = ref(false)
const form = ref({ title: '', description: '', icon: '' })

const defaultBadge = computed(() => (editing.value?.sourceType === 'pdf' ? 'PDF' : 'MD'))

onMounted(() => void store.load())

// 搜索输入做 300ms 防抖，避免每敲一个字都打一次接口
let timer: number | undefined
const keywordInput = ref(store.keyword)
watch(keywordInput, (value) => {
  if (timer) window.clearTimeout(timer)
  timer = window.setTimeout(() => void store.setKeyword(value), 300)
})

const summary = computed(() => {
  if (!store.count) return '没有匹配的课程'
  return `${store.count} 门课程 · ${store.totalPoints} 个知识点 · 已完成 ${store.totalCompleted} 个`
})

const statusLine = computed(() =>
  STATUS_ORDER.map((status) => `${STATUS_LABELS[status]} ${countOf(store.statusTotals, status)}`).join(' · '),
)

function typeLabel(course: CourseSummary): string {
  return course.sourceType === 'pdf' ? 'PDF' : 'MD'
}

function openDetail(course: CourseSummary): void {
  void router.push({ name: 'course-detail', params: { id: course.id } })
}

function openEdit(course: CourseSummary): void {
  editing.value = course
  form.value = { title: course.title, description: course.description, icon: course.icon ?? '' }
  editOpen.value = true
}

async function submitEdit(): Promise<void> {
  const course = editing.value
  if (!course) return
  const title = form.value.title.trim()
  if (!title) {
    ElMessage.warning('课程名称不能为空')
    return
  }
  saving.value = true
  try {
    await courseLibraryApi.update(course.id, {
      title,
      description: form.value.description,
      icon: form.value.icon,
    })
    editing.value = null
    editOpen.value = false
    await store.load()
    ElMessage.success('课程信息已保存')
  } catch (err) {
    ElMessage.error(err instanceof ApiError ? err.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function removeCourse(course: CourseSummary): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `将删除「${course.title}」的 ${course.chapterCount} 个章节、${course.knowledgePointCount} 个知识点的全部学习状态，以及本地教材文件，无法恢复。`,
      '删除课程',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消', confirmButtonClass: 'el-button--danger' },
    )
  } catch {
    return
  }
  try {
    await store.remove(course.id)
    ElMessage.success('课程已删除')
  } catch (err) {
    ElMessage.error(err instanceof ApiError ? err.message : '删除失败')
  }
}
</script>

<template>
  <div class="ml-page">
    <div class="ml-page-head">
      <div>
        <h2 class="ml-page-title">课程中心</h2>
        <p class="ml-page-desc">
          这里是你导入的教材整理成的学习目录。进入课程可以维护章节与知识点，并逐个记录学习状态。
        </p>
      </div>
      <el-button type="primary" :icon="UploadFilled" @click="router.push({ name: 'course-import' })">
        导入教材
      </el-button>
    </div>

    <el-alert v-if="store.error" type="error" :closable="false" :title="store.error" show-icon class="page-alert" />

    <div v-if="!store.loading && store.count === 0 && !store.keyword" class="ml-empty">
      <h3>还没有课程</h3>
      <p>
        导入一份 Markdown 或文本型 PDF 教材，系统会解析出章节与知识点。你可以先调整结构，
        确认后再正式创建课程。
      </p>
      <el-button type="primary" :icon="UploadFilled" @click="router.push({ name: 'course-import' })">
        导入第一份教材
      </el-button>
    </div>

    <template v-else>
      <div class="toolbar">
        <el-input
          v-model="keywordInput"
          class="search"
          :prefix-icon="Search"
          placeholder="搜索课程名称、简介或教材文件名"
          clearable
        />
        <el-radio-group v-model="store.sort" size="small" @change="store.setSort(store.sort)">
          <el-radio-button v-for="option in SORT_OPTIONS" :key="option.value" :value="option.value">
            {{ option.label }}
          </el-radio-button>
        </el-radio-group>
      </div>

      <div class="list-head">
        <span>{{ summary }}</span>
        <span class="ml-muted">{{ statusLine }}</span>
      </div>

      <ul v-loading="store.loading" class="course-list">
        <li v-for="course in store.items" :key="course.id" class="course-row">
          <span class="type-badge" :class="[course.sourceType, { custom: Boolean(course.icon) }]">
            {{ course.icon || typeLabel(course) }}
          </span>

          <div class="course-main">
            <button class="course-title" type="button" @click="openDetail(course)">{{ course.title }}</button>
            <p v-if="course.description" class="course-desc">{{ course.description }}</p>
            <p class="course-meta">
              <span class="meta-item">
                <el-icon :size="12"><Document /></el-icon>
                {{ course.sourceName }}
              </span>
              <span class="dot">·</span>
              <span>{{ course.sourceType === 'pdf' ? 'PDF' : 'Markdown' }} {{ formatBytes(course.sourceBytes) }}</span>
              <span class="dot">·</span>
              <span>{{ course.chapterCount }} 章 / {{ course.knowledgePointCount }} 知识点</span>
              <span class="dot">·</span>
              <span>创建于 {{ formatDateTime(course.createdAt) }}</span>
            </p>
          </div>

          <div class="course-progress">
            <div class="progress-line">
              <div class="progress-track"><div class="progress-fill" :style="{ width: `${course.progress}%` }" /></div>
              <span class="progress-text">{{ course.progress }}%</span>
            </div>
            <p class="progress-detail">
              已完成 {{ course.statusCounts.completed }} · 学习中 {{ course.statusCounts.inProgress }} · 待复习
              {{ course.statusCounts.review }}
            </p>
            <p class="course-time">最近学习 {{ formatRelative(course.lastStudiedAt) }}</p>
          </div>

          <div class="course-actions">
            <el-button link type="primary" :icon="Reading" @click="openDetail(course)">继续学习</el-button>
            <el-button link :icon="Edit" @click="openEdit(course)">编辑</el-button>
            <el-button link type="danger" :icon="Delete" @click="removeCourse(course)">删除</el-button>
          </div>
        </li>
      </ul>

      <p v-if="store.count === 0" class="no-match">
        没有找到匹配「{{ store.keyword }}」的课程，试试换一个关键词。
      </p>

      <p v-if="store.count > 0" class="list-foot">
        <el-icon :size="13"><Document /></el-icon>
        教材原文保存在 <code>data/courses/</code>，删除课程会一并清理；学习状态记录在本地数据库。
      </p>
    </template>

    <el-dialog v-model="editOpen" title="编辑课程" width="560px" :close-on-click-modal="false">
      <el-form label-position="top" class="edit-form">
        <el-form-item label="课程名称">
          <el-input v-model="form.title" maxlength="200" show-word-limit />
        </el-form-item>
        <el-form-item label="课程简介">
          <el-input v-model="form.description" type="textarea" :rows="3" maxlength="2000" show-word-limit />
        </el-form-item>
        <el-form-item label="课程图标">
          <div class="icon-picker">
            <button
              v-for="choice in ICON_CHOICES"
              :key="choice || 'default'"
              type="button"
              class="icon-option"
              :class="{ active: form.icon === choice }"
              @click="form.icon = choice"
            >
              {{ choice || defaultBadge }}
            </button>
          </div>
          <p class="field-note">留空则按教材类型显示 MD / PDF 徽标。</p>
        </el-form-item>
      </el-form>

      <div v-if="editing" class="source-info">
        <p class="source-title">原始教材</p>
        <dl>
          <div><dt>文件名</dt><dd>{{ editing.sourceName }}</dd></div>
          <div><dt>类型 / 大小</dt><dd>{{ editing.sourceType === 'pdf' ? 'PDF' : 'Markdown' }} · {{ formatBytes(editing.sourceBytes) }}</dd></div>
          <div><dt>章节 / 知识点</dt><dd>{{ editing.chapterCount }} 章 · {{ editing.knowledgePointCount }} 个知识点</dd></div>
          <div><dt>创建 / 更新</dt><dd>{{ formatDateTime(editing.createdAt) }} / {{ formatDateTime(editing.updatedAt) }}</dd></div>
        </dl>
      </div>

      <template #footer>
        <el-button @click="editOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-alert {
  margin-bottom: 16px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.search {
  max-width: 380px;
}

.list-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding-bottom: 10px;
  font-size: 12.5px;
  color: var(--ml-text-2);
  border-bottom: 1px solid var(--ml-border);
}

.course-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.course-row {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) 250px 170px;
  align-items: center;
  gap: 18px;
  padding: 16px 4px;
  border-bottom: 1px solid var(--ml-border);
}

.course-row:hover {
  background: var(--ml-surface);
}

.type-badge {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 8px;
  border: 1px solid var(--ml-border-strong);
  background: var(--ml-surface-2);
  font-family: var(--ml-font-mono);
  font-size: 11.5px;
  letter-spacing: 0.04em;
  color: var(--ml-text-2);
}

.type-badge.custom {
  font-family: var(--ml-font-sans);
  font-size: 19px;
}

.type-badge.pdf {
  color: #f0a3a3;
  border-color: rgba(248, 81, 73, 0.35);
  background: rgba(248, 81, 73, 0.08);
}

.course-main {
  min-width: 0;
}

.course-title {
  padding: 0;
  border: none;
  background: none;
  font-family: inherit;
  font-size: 15px;
  font-weight: 550;
  color: var(--ml-text);
  cursor: pointer;
  text-align: left;
}

.course-title:hover {
  color: var(--ml-accent);
}

.course-desc {
  margin-top: 3px;
  font-size: 12.5px;
  color: var(--ml-text-3);
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
}

.course-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  margin-top: 5px;
  font-size: 12px;
  color: var(--ml-text-3);
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.dot {
  margin: 0 6px;
  color: var(--ml-border-strong);
}

.course-progress {
  display: grid;
  gap: 3px;
}

.progress-line {
  display: flex;
  align-items: center;
  gap: 8px;
}

.progress-track {
  flex: 1;
  height: 4px;
  border-radius: 2px;
  background: var(--ml-surface-3);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--ml-accent);
  border-radius: 2px;
  transition: width 0.2s ease;
}

.progress-text {
  font-family: var(--ml-font-mono);
  font-size: 11.5px;
  color: var(--ml-text-2);
  min-width: 34px;
  text-align: right;
}

.progress-detail,
.course-time {
  font-size: 11.5px;
  color: var(--ml-text-3);
}

.course-actions {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
}

.no-match {
  padding: 36px 0;
  text-align: center;
  font-size: 13px;
  color: var(--ml-text-3);
}

.list-foot {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 14px;
  font-size: 12.5px;
  color: var(--ml-text-3);
}

.list-foot code {
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--ml-surface-2);
  border: 1px solid var(--ml-border);
}

/* ---------- 编辑弹窗 ---------- */
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
  font-size: 15px;
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

.field-note {
  margin-top: 6px;
  font-size: 11.5px;
  color: var(--ml-text-3);
}

.source-info {
  margin-top: 4px;
  padding-top: 14px;
  border-top: 1px solid var(--ml-border);
}

.source-title {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--ml-text-3);
  margin-bottom: 8px;
}

.source-info dl {
  display: grid;
  gap: 6px;
  margin: 0;
  font-size: 12.5px;
}

.source-info dl > div {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 10px;
}

.source-info dt {
  color: var(--ml-text-3);
}

.source-info dd {
  margin: 0;
  color: var(--ml-text-2);
  word-break: break-all;
}

@media (max-width: 1180px) {
  .course-row {
    grid-template-columns: 44px minmax(0, 1fr);
    grid-template-areas:
      'badge main'
      'badge progress'
      'badge actions';
    row-gap: 8px;
  }

  .type-badge {
    grid-area: badge;
    align-self: start;
  }

  .course-main {
    grid-area: main;
  }

  .course-progress {
    grid-area: progress;
    max-width: 340px;
  }

  .course-actions {
    grid-area: actions;
    justify-content: flex-start;
  }
}
</style>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  ArrowUp,
  Close,
  Delete,
  Document,
  Plus,
  UploadFilled,
} from '@element-plus/icons-vue'

import { courseApi, uploadCourseMaterial } from '@/api'
import { ApiError } from '@/api/client'
import type { Chapter, CourseDetail, KnowledgePoint } from '@/api/types'

const router = useRouter()

const MAX_BYTES = 20 * 1024 * 1024
const ALLOWED = ['.md', '.markdown', '.txt', '.pdf']

const step = ref<'upload' | 'preview'>('upload')
const uploading = ref(false)
const progress = ref(0)
const parsing = ref(false)
const saving = ref(false)
const errorMessage = ref('')
const dragActive = ref(false)
const pickedFile = ref<File | null>(null)
const detail = ref<CourseDetail | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

const totalPoints = computed(() => detail.value?.knowledgePointCount ?? 0)

const fileMeta = computed(() => {
  const file = pickedFile.value
  if (!file) return ''
  return `${file.name} · ${formatBytes(file.size)} · ${extension(file.name).toUpperCase().replace('.', '')}`
})

function extension(name: string): string {
  const index = name.lastIndexOf('.')
  return index >= 0 ? name.slice(index).toLowerCase() : ''
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

function openPicker(): void {
  errorMessage.value = ''
  fileInput.value?.click()
}

function onFileChange(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) void startUpload(file)
}

function onDrop(event: DragEvent): void {
  dragActive.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) void startUpload(file)
}

async function startUpload(file: File): Promise<void> {
  errorMessage.value = ''
  const ext = extension(file.name)
  if (!ALLOWED.includes(ext)) {
    errorMessage.value = `不支持的文件类型 ${ext || '（无扩展名）'}，请选择 Markdown（.md/.markdown/.txt）或 PDF（.pdf）。`
    return
  }
  if (file.size > MAX_BYTES) {
    errorMessage.value = `文件 ${formatBytes(file.size)} 超过 20 MB 上限。`
    return
  }
  if (file.size === 0) {
    errorMessage.value = '文件是空的（0 字节），请选择有内容的教材。'
    return
  }

  pickedFile.value = file
  uploading.value = true
  progress.value = 0
  parsing.value = false

  try {
    const result = await uploadCourseMaterial(file, (event) => {
      progress.value = event.percent
      if (event.percent >= 100) parsing.value = true
    })
    detail.value = result
    step.value = 'preview'
  } catch (err) {
    errorMessage.value = err instanceof ApiError ? err.message : '上传失败，请重试'
  } finally {
    uploading.value = false
    parsing.value = false
  }
}

function fail(err: unknown, fallback: string): void {
  ElMessage.error(err instanceof ApiError ? err.message : fallback)
}

async function saveCourseTitle(): Promise<void> {
  if (!detail.value) return
  const title = detail.value.title.trim()
  if (!title) {
    ElMessage.warning('课程名称不能为空')
    await reload()
    return
  }

  try {
    detail.value = await courseApi.update(detail.value.id, { title })
  } catch (err) {
    fail(err, '保存课程名称失败')
    await reload()
  }
}

async function reload(): Promise<void> {
  if (!detail.value) return
  try {
    detail.value = await courseApi.detail(detail.value.id)
  } catch {
    /* 忽略：下一次操作会再尝试 */
  }
}

async function saveChapterTitle(chapter: Chapter): Promise<void> {
  const title = chapter.title.trim()
  if (!title) {
    ElMessage.warning('章节名称不能为空')
    await reload()
    return
  }
  try {
    detail.value = await courseApi.updateChapter(chapter.id, { title })
  } catch (err) {
    fail(err, '保存章节名称失败')
    await reload()
  }
}

async function savePointTitle(point: KnowledgePoint): Promise<void> {
  const title = point.title.trim()
  if (!title) {
    ElMessage.warning('知识点名称不能为空')
    await reload()
    return
  }
  // 改名不触发全列表的 loading 遮罩：遮罩会在输入框 blur 时出现，
  // 从而把紧接着的一次点击（例如改名后立刻点上移）吞掉。
  try {
    detail.value = await courseApi.updatePoint(point.id, { title })
  } catch (err) {
    fail(err, '保存知识点名称失败')
    await reload()
  }
}

async function addChapter(): Promise<void> {
  if (!detail.value) return
  try {
    const { value } = await ElMessageBox.prompt('新章节会追加到目录末尾，之后可以再调顺序。', '添加章节', {
      confirmButtonText: '添加',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：异常处理',
      inputValidator: (input: string) => (input && input.trim() ? true : '章节名称不能为空'),
    })
    detail.value = await courseApi.addChapter(detail.value.id, value.trim())
    ElMessage.success('章节已添加')
  } catch (err) {
    if (err === 'cancel' || err === 'close') return
    fail(err, '添加章节失败')
  }
}

async function removeChapter(chapter: Chapter): Promise<void> {
  if (!detail.value) return
  try {
    await ElMessageBox.confirm(`将删除章节「${chapter.title}」及其下 ${chapter.knowledgePoints.length} 个知识点。`, '删除章节', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return
  }
  try {
    detail.value = await courseApi.removeChapter(chapter.id)
    ElMessage.success('章节已删除')
  } catch (err) {
    fail(err, '删除章节失败')
  }
}

async function addPoint(chapter: Chapter): Promise<void> {
  if (!detail.value) return
  try {
    const { value } = await ElMessageBox.prompt(`添加到「${chapter.title}」末尾。`, '添加知识点', {
      confirmButtonText: '添加',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：捕获并处理超时',
      inputValidator: (input: string) => (input && input.trim() ? true : '知识点名称不能为空'),
    })
    detail.value = await courseApi.addPoint(chapter.id, value.trim())
    ElMessage.success('知识点已添加')
  } catch (err) {
    if (err === 'cancel' || err === 'close') return
    fail(err, '添加知识点失败')
  }
}

async function removePoint(point: KnowledgePoint): Promise<void> {
  if (!detail.value) return
  try {
    await ElMessageBox.confirm(`删除知识点「${point.title}」？教材原文不受影响。`, '删除知识点', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return
  }
  try {
    detail.value = await courseApi.removePoint(point.id)
    ElMessage.success('知识点已删除')
  } catch (err) {
    fail(err, '删除知识点失败')
  }
}

async function moveChapter(index: number, delta: number): Promise<void> {
  if (!detail.value) return
  const chapters = [...detail.value.chapters]
  const target = index + delta
  if (target < 0 || target >= chapters.length) return
  const ids = chapters.map((chapter) => chapter.id)
  ;[ids[index], ids[target]] = [ids[target], ids[index]]
  await applyChapterOrder(ids)
}

async function movePoint(chapter: Chapter, index: number, delta: number): Promise<void> {
  if (!detail.value) return
  const target = index + delta
  if (target < 0 || target >= chapter.knowledgePoints.length) return
  const ids = chapter.knowledgePoints.map((point) => point.id)
  ;[ids[index], ids[target]] = [ids[target], ids[index]]
  saving.value = true
  try {
    detail.value = await courseApi.reorder(detail.value.id, {
      chapters: [],
      knowledgePoints: [{ chapterId: chapter.id, ids }],
    })
  } catch (err) {
    fail(err, '调整顺序失败')
    await reload()
  } finally {
    saving.value = false
  }
}

async function applyChapterOrder(ids: number[]): Promise<void> {
  if (!detail.value) return
  saving.value = true
  try {
    detail.value = await courseApi.reorder(detail.value.id, {
      chapters: ids,
      knowledgePoints: detail.value.chapters.map((chapter) => ({
        chapterId: chapter.id,
        ids: chapter.knowledgePoints.map((point) => point.id),
      })),
    })
  } catch (err) {
    fail(err, '调整顺序失败')
    await reload()
  } finally {
    saving.value = false
  }
}

async function confirmCreate(): Promise<void> {
  if (!detail.value) return
  if (detail.value.chapters.length === 0) {
    ElMessage.warning('至少保留一个章节才能创建课程')
    return
  }
  saving.value = true
  try {
    const course = await courseApi.confirm(detail.value.id)
    ElMessage.success('课程已创建')
    await router.push({ name: 'course-detail', params: { id: course.id } })
  } catch (err) {
    fail(err, '创建课程失败')
  } finally {
    saving.value = false
  }
}

async function cancelImport(): Promise<void> {
  const id = detail.value?.id
  try {
    if (id) await courseApi.remove(id)
  } catch {
    /* 草稿清理失败不阻塞返回 */
  }
  await router.push({ name: 'courses' })
}

function resetUpload(): void {
  step.value = 'upload'
  detail.value = null
  pickedFile.value = null
  progress.value = 0
  errorMessage.value = ''
}
</script>

<template>
  <div class="ml-page">
    <div class="ml-page-head">
      <div>
        <h2 class="ml-page-title">导入教材</h2>
        <p class="ml-page-desc">
          支持 Markdown 与带文本层的 PDF。文件只保存在本机 data/courses 下，解析在本地完成，
          生成的结构需要你确认后才会成为正式课程。
        </p>
      </div>
      <el-button v-if="step === 'preview'" @click="resetUpload">重新选择文件</el-button>
    </div>

    <!-- 第一步：选择文件 -->
    <section v-if="step === 'upload'" class="upload-step">
      <div
        class="dropzone"
        :class="{ active: dragActive, busy: uploading }"
        role="button"
        tabindex="0"
        @click="openPicker"
        @keydown.enter.prevent="openPicker"
        @dragover.prevent="dragActive = true"
        @dragleave.prevent="dragActive = false"
        @drop.prevent="onDrop"
      >
        <el-icon :size="26" class="dropzone-icon"><UploadFilled /></el-icon>
        <p class="dropzone-title">{{ uploading ? '正在上传…' : '把教材拖到这里，或点击选择文件' }}</p>
        <p class="dropzone-hint">Markdown（.md / .markdown / .txt）· PDF（.pdf）· 单个文件最大 20 MB</p>
        <p v-if="fileMeta" class="dropzone-file">{{ fileMeta }}</p>
        <input ref="fileInput" type="file" accept=".md,.markdown,.txt,.pdf" hidden @change="onFileChange" />
      </div>

      <div v-if="uploading" class="upload-progress">
        <el-progress :percentage="progress" :stroke-width="6" :show-text="false" />
        <span class="progress-label">
          {{ parsing ? '正在解析教材结构…' : `上传中 ${progress}%` }}
        </span>
      </div>

      <el-alert
        v-if="errorMessage"
        type="error"
        :closable="false"
        show-icon
        :title="errorMessage"
        class="upload-error"
      />

      <ul class="notes">
        <li>扫描版 PDF 没有文本层，当前版本会明确提示无法识别，不会编造章节。</li>
        <li>Markdown 按标题层级解析：一级标题作课程名，二级为章节，三到六级为知识点。</li>
        <li>解析结果只是建议，确认之前可以自由改名、增删和调整顺序。</li>
      </ul>
    </section>

    <!-- 第二步：结构预览与编辑 -->
    <section v-else-if="detail" class="preview-step">
      <div class="preview-head">
        <el-input v-model="detail.title" class="title-input" maxlength="200" @blur="saveCourseTitle" @keyup.enter="saveCourseTitle" />
        <p class="preview-meta">
          <el-icon :size="13"><Document /></el-icon>
          <span>{{ detail.sourceName }}</span>
          <span class="dot">·</span>
          <span>{{ detail.sourceType === 'pdf' ? 'PDF' : 'Markdown' }}</span>
          <span class="dot">·</span>
          <span>{{ formatBytes(detail.sourceBytes) }}</span>
          <span class="dot">·</span>
          <span>{{ detail.chapterCount }} 章 / {{ totalPoints }} 知识点 / {{ detail.codeCount }} 代码块</span>
        </p>
        <el-alert
          v-for="warning in detail.warnings"
          :key="warning"
          type="warning"
          :closable="false"
          show-icon
          :title="warning"
          class="preview-warning"
        />
      </div>

      <div v-loading="saving" class="chapter-list">
        <article v-for="(chapter, chapterIndex) in detail.chapters" :key="chapter.id" class="chapter">
          <header class="chapter-head">
            <span class="chapter-index">{{ String(chapterIndex + 1).padStart(2, '0') }}</span>
            <el-input
              v-model="chapter.title"
              class="chapter-title"
              maxlength="200"
              @blur="saveChapterTitle(chapter)"
              @keyup.enter="saveChapterTitle(chapter)"
            />
            <span class="chapter-count">{{ chapter.knowledgePoints.length }} 知识点 · {{ chapter.codeCount }} 代码</span>
            <div class="chapter-tools">
              <el-button link :icon="ArrowUp" :disabled="chapterIndex === 0" title="上移" @click="moveChapter(chapterIndex, -1)" />
              <el-button
                link
                :icon="ArrowDown"
                :disabled="chapterIndex === detail.chapters.length - 1"
                title="下移"
                @click="moveChapter(chapterIndex, 1)"
              />
              <el-button link :icon="Plus" title="添加知识点" @click="addPoint(chapter)" />
              <el-button link type="danger" :icon="Delete" title="删除章节" @click="removeChapter(chapter)" />
            </div>
          </header>

          <ul v-if="chapter.knowledgePoints.length" class="point-list">
            <li v-for="(point, pointIndex) in chapter.knowledgePoints" :key="point.id" class="point">
              <div class="point-main">
                <el-input
                  v-model="point.title"
                  class="point-title"
                  maxlength="200"
                  @blur="savePointTitle(point)"
                  @keyup.enter="savePointTitle(point)"
                />
                <p v-if="point.description" class="point-desc">{{ point.description }}</p>
                <p v-else class="point-desc muted">（这一段没有正文，只有标题）</p>
              </div>
              <el-tag v-if="point.codeCount" size="small" type="info" effect="plain">{{ point.codeCount }} 代码</el-tag>
              <div class="point-tools">
                <el-button link :icon="ArrowUp" :disabled="pointIndex === 0" title="上移" @click="movePoint(chapter, pointIndex, -1)" />
                <el-button
                  link
                  :icon="ArrowDown"
                  :disabled="pointIndex === chapter.knowledgePoints.length - 1"
                  title="下移"
                  @click="movePoint(chapter, pointIndex, 1)"
                />
                <el-button link type="danger" :icon="Close" title="删除知识点" @click="removePoint(point)" />
              </div>
            </li>
          </ul>
          <p v-else class="point-empty">这个章节还没有知识点，点 + 添加一个。</p>
        </article>

        <button type="button" class="add-chapter" @click="addChapter">
          <el-icon :size="14"><Plus /></el-icon>
          添加章节
        </button>
      </div>

      <footer class="preview-foot">
        <p class="foot-note">确认后会创建课程记录，并把每个知识点的学习状态初始化为「未学习」。</p>
        <div class="foot-actions">
          <el-button @click="cancelImport">取消导入</el-button>
          <el-button type="primary" :loading="saving" @click="confirmCreate">确认创建课程</el-button>
        </div>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.upload-step {
  max-width: 720px;
}

.dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 46px 24px;
  border: 1px dashed var(--ml-border-strong);
  border-radius: var(--ml-radius-lg);
  background: var(--ml-bg-soft);
  cursor: pointer;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.dropzone:hover,
.dropzone.active {
  border-color: var(--ml-accent);
  background: var(--ml-accent-weak);
}

.dropzone.busy {
  cursor: progress;
}

.dropzone-icon {
  color: var(--ml-accent);
}

.dropzone-title {
  font-size: 14px;
  color: var(--ml-text);
}

.dropzone-hint {
  font-size: 12.5px;
  color: var(--ml-text-3);
}

.dropzone-file {
  margin-top: 6px;
  font-family: var(--ml-font-mono);
  font-size: 12px;
  color: var(--ml-text-2);
}

.upload-progress {
  margin-top: 14px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.upload-progress :deep(.el-progress) {
  flex: 1;
}

.progress-label {
  font-size: 12.5px;
  color: var(--ml-text-2);
  min-width: 120px;
}

.upload-error {
  margin-top: 14px;
}

.notes {
  margin: 20px 0 0;
  padding-left: 18px;
  color: var(--ml-text-3);
  font-size: 12.5px;
  line-height: 1.9;
}

/* ---------- 预览 ---------- */
.preview-head {
  padding-bottom: 16px;
  border-bottom: 1px solid var(--ml-border);
}

.title-input {
  max-width: 620px;
}

.title-input :deep(.el-input__inner) {
  font-size: 19px;
  font-weight: 600;
  height: 38px;
  color: var(--ml-text);
}

.preview-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 8px;
  font-size: 12.5px;
  color: var(--ml-text-3);
}

.preview-warning {
  margin-top: 10px;
}

.dot {
  margin: 0 6px;
  color: var(--ml-border-strong);
}

.chapter-list {
  margin-top: 8px;
}

.chapter {
  padding: 16px 0;
  border-bottom: 1px solid var(--ml-border);
}

.chapter-head {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 12px;
}

.chapter-index {
  font-family: var(--ml-font-mono);
  font-size: 12px;
  color: var(--ml-text-3);
}

.chapter-title :deep(.el-input__inner) {
  font-size: 14.5px;
  font-weight: 550;
  color: var(--ml-text);
}

.chapter-title,
.point-title {
  width: 100%;
}

.chapter-count {
  font-size: 12px;
  color: var(--ml-text-3);
  white-space: nowrap;
}

.chapter-tools,
.point-tools {
  display: flex;
  gap: 2px;
}

.point-list {
  list-style: none;
  margin: 10px 0 0;
  padding: 0 0 0 46px;
  display: grid;
  gap: 2px;
}

.point {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--ml-radius);
}

.point:hover {
  background: var(--ml-surface);
}

.point-main {
  min-width: 0;
}

.point-title :deep(.el-input__inner) {
  font-size: 13.5px;
  color: var(--ml-text);
  height: 30px;
}

.point-desc {
  margin-top: 2px;
  font-size: 12.5px;
  color: var(--ml-text-3);
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
}

.point-desc.muted {
  color: var(--ml-text-3);
  opacity: 0.7;
}

.point-empty {
  margin: 8px 0 0 46px;
  font-size: 12.5px;
  color: var(--ml-text-3);
}

.add-chapter {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 14px;
  padding: 8px 12px;
  border: 1px dashed var(--ml-border-strong);
  border-radius: var(--ml-radius);
  background: transparent;
  color: var(--ml-text-2);
  font-family: inherit;
  font-size: 13px;
  cursor: pointer;
}

.add-chapter:hover {
  border-color: var(--ml-accent);
  color: var(--ml-accent);
}

.preview-foot {
  position: sticky;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 20px;
  padding: 14px 0 8px;
  background: color-mix(in srgb, var(--ml-bg) 92%, transparent);
  backdrop-filter: blur(6px);
  border-top: 1px solid var(--ml-border);
}

.foot-note {
  font-size: 12.5px;
  color: var(--ml-text-3);
}

.foot-actions {
  display: flex;
  gap: 8px;
}
</style>

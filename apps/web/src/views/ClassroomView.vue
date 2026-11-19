<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft,
  ArrowRight,
  Expand,
  Fold,
  Menu,
  Promotion,
  Refresh,
  VideoPause,
  Warning,
} from '@element-plus/icons-vue'

import { classroomApi, courseLibraryApi, learningApi, modelApi } from '@/api'
import { ApiError, apiBase } from '@/api/client'
import { streamClassroom } from '@/api/classroomStream'
import type {
  BreakpointState,
  Chapter,
  ChatMessage,
  ClassroomSession,
  CourseDetail,
  KnowledgePoint,
  LearningActivityState,
  TeachingAction,
  TeachingState,
  ModelConfig,
} from '@/api/types'
import { formatRelative, statusLabel } from '@/utils/learning'
import { renderMarkdown } from '@/utils/markdown'
import { useTeachingMetaStore } from '@/stores/teachingMeta'
import TeachingFlowPanel from '@/components/TeachingFlowPanel.vue'
import ActivityRenderer from '@/components/ActivityRenderer.vue'

interface QuickAction {
  id: string
  label: string
  prompt?: string
}

const QUICK_ACTIONS: QuickAction[] = [
  { id: 'again', label: '再讲一遍', prompt: '请把当前知识点再讲一遍，换一种更通俗的说法，不要重复刚才的原话。' },
  { id: 'example', label: '换个例子', prompt: '请换一个更贴近日常生活的例子来说明当前知识点。' },
  { id: 'slower', label: '慢一点讲', prompt: '请放慢节奏，把当前知识点拆成更小的步骤重新讲一遍。' },
  { id: 'project', label: '举实际项目例子', prompt: '请举一个实际项目中会用到当前知识点的例子，并说明为什么这样用。' },
  { id: 'code', label: '解释这个示例', prompt: '请解释你刚才给出的示例，逐步说明关键步骤、依据和预期结果。' },
  { id: 'question', label: '我有一个问题' },
]

const route = useRoute()
const router = useRouter()

const courseId = computed(() => Number(route.params.id))
const course = ref<CourseDetail | null>(null)
const session = ref<ClassroomSession | null>(null)
const messages = ref<ChatMessage[]>([])
const activePointId = ref<number | null>(null)

const loadingCourse = ref(false)
const loadingSession = ref(false)
const streaming = ref(false)
const stopping = ref(false)
const errorMessage = ref('')
const streamError = ref('')
const teaching = ref<TeachingState | null>(null)
const controlBusy = ref(false)
const inputMode = ref<'ASK' | 'ANSWER'>('ASK')
const draft = ref('')
const models = ref<ModelConfig[]>([])
const busy = computed(() => streaming.value || stopping.value || loadingSession.value || Boolean(session.value?.streaming))
const activity = ref<LearningActivityState | null>(null)
const breakpoint = ref<BreakpointState | null>(null)
const resumeNotice = ref('')
const autosaveState = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
const autosaveNote = ref('')
const autosaveLabel = computed(() => {
  if (autosaveState.value === 'saving') return '正在自动保存…'
  if (autosaveState.value === 'saved') return '已自动保存'
  if (autosaveState.value === 'error') return autosaveNote.value || '自动保存失败'
  return '对话与草稿自动保存'
})

const collapsed = ref<Set<number>>(new Set())
const catalogOpen = ref(typeof window === 'undefined' || window.innerWidth >= 980)
const infoOpen = ref(typeof window === 'undefined' || window.innerWidth >= 1200)
const shouldStick = ref(true)

const messagesEl = ref<HTMLElement | null>(null)
const composerRef = ref<{ focus: () => void } | null>(null)

let controller: AbortController | null = null
let sessionSeq = 0
let courseSeq = 0

/* ---------------- P1.5 学习活动与断点自动保存 ---------------- */

const HEARTBEAT_MS = 30_000
const IDLE_LIMIT_MS = 5 * 60_000
let activityId: number | null = null
let heartbeatTimer: number | undefined
let lastTickAt = 0
let lastInteractionAt = Date.now()
let clientSeq = 0
let lastSavedDraft = ''
let lastSavedMode: 'ASK' | 'ANSWER' = 'ASK'
let saveTimer: number | undefined
let suppressDraftSave = false
let listenersBound = false
let breakpointReady = false

const teachingMeta = useTeachingMetaStore()

const STAGE_TEXT: Record<string, string> = {
  TEACH: '讲解',
  DEMO: '演示',
  CHECK: '理解检查',
  PAIR: '陪练',
  VERIFY: '独立验证',
  NEXT: '已完成',
  UNDERSTAND: '认识问题',
  DEMONSTRATE: '示范演示',
  INTERACT: '互动检查',
  PRACTICE: '引导练习',
  CONSOLIDATE: '巩固总结',
}

function stageText(stage: string | null | undefined): string {
  return teachingMeta.stageLabel(stage) || STAGE_TEXT[stage ?? ''] || stage || ''
}

function touchActivity(): void {
  lastInteractionAt = Date.now()
}

function onUserActivity(): void {
  touchActivity()
}

function bindActivityListeners(): void {
  if (listenersBound) return
  listenersBound = true
  window.addEventListener('pointerdown', onUserActivity, { passive: true })
  window.addEventListener('keydown', onUserActivity, { passive: true })
  window.addEventListener('scroll', onUserActivity, { passive: true })
  document.addEventListener('visibilitychange', onVisibilityChange)
  window.addEventListener('pagehide', saveOnExit)
  window.addEventListener('beforeunload', saveOnExit)
}

function unbindActivityListeners(): void {
  if (!listenersBound) return
  listenersBound = false
  window.removeEventListener('pointerdown', onUserActivity)
  window.removeEventListener('keydown', onUserActivity)
  window.removeEventListener('scroll', onUserActivity)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  window.removeEventListener('pagehide', saveOnExit)
  window.removeEventListener('beforeunload', saveOnExit)
}

function onVisibilityChange(): void {
  if (document.visibilityState === 'hidden') {
    void flushHeartbeat()
  } else {
    lastTickAt = Date.now()
    touchActivity()
  }
}

function startHeartbeat(): void {
  stopHeartbeat()
  lastTickAt = Date.now()
  heartbeatTimer = window.setInterval(() => void flushHeartbeat(), HEARTBEAT_MS)
}

function stopHeartbeat(): void {
  if (heartbeatTimer) window.clearInterval(heartbeatTimer)
  heartbeatTimer = undefined
}

async function startLearningActivity(sessionId?: number): Promise<void> {
  const pointId = activePointId.value
  if (!sessionId || !pointId) return
  try {
    const started = await learningApi.startActivity({
      courseId: courseId.value,
      knowledgePointId: pointId,
      sessionId,
    })
    activity.value = started
    activityId = started.id
    lastTickAt = Date.now()
    startHeartbeat()
  } catch {
    activity.value = null
    activityId = null
  }
}

async function endLearningActivity(reason = 'user_exit'): Promise<void> {
  stopHeartbeat()
  const id = activityId
  activityId = null
  if (!id) return
  try {
    await learningApi.finishActivity(id, { result: 'finished', reason })
  } catch {
    /* 心跳已经持久化，结束请求失败不影响已记录的有效时长 */
  }
  activity.value = null
}

async function restartLearningActivity(): Promise<void> {
  await endLearningActivity('restarted')
  if (session.value) await startLearningActivity(session.value.id)
}

async function flushHeartbeat(): Promise<void> {
  const id = activityId
  if (!id) return
  const now = Date.now()
  const elapsed = Math.max(0, Math.round((now - lastTickAt) / 1000))
  lastTickAt = now
  if (document.visibilityState === 'hidden') return
  const idle = now - lastInteractionAt > IDLE_LIMIT_MS
  const delta = idle ? 0 : Math.min(elapsed, 35)
  if (delta <= 0) return
  try {
    const result = await learningApi.heartbeat(id, delta)
    activity.value = result
    if (result.closed || result.status !== 'active') {
      activityId = null
      stopHeartbeat()
      if (session.value) await startLearningActivity(session.value.id)
    }
  } catch {
    autosaveState.value = 'error'
    autosaveNote.value = '学习时长暂时无法同步，稍后会自动重试'
  }
}

function markSaved(mode: 'saving' | 'saved' | 'error', note = ''): void {
  autosaveState.value = mode
  autosaveNote.value = note
}

function scheduleSave(delay = 900): void {
  if (!breakpointReady) return
  if (saveTimer) window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(() => void saveBreakpointNow(), delay)
}

async function saveBreakpointNow(): Promise<void> {
  if (!session.value) return
  if (suppressDraftSave || !breakpointReady) return
  if (draft.value === lastSavedDraft && inputMode.value === lastSavedMode) return
  const sid = session.value.id
  const seq = ++clientSeq
  const payloadDraft = draft.value
  const payloadMode = inputMode.value
  markSaved('saving')
  try {
    const saved = await learningApi.saveBreakpoint(sid, {
      clientSeq: seq,
      draftAnswer: payloadDraft,
      inputMode: payloadMode,
    })
    breakpoint.value = saved
    if (!saved.accepted) {
      clientSeq = Math.max(clientSeq, saved.clientSeq)
      markSaved('error', '服务器已有更新的进度，本次草稿未覆盖')
      return
    }
    lastSavedDraft = payloadDraft
    lastSavedMode = payloadMode
    markSaved('saved')
  } catch {
    markSaved('error', '自动保存失败，请检查后端服务')
  }
}

async function restoreBreakpoint(sessionId: number, seq: number): Promise<BreakpointState | null> {
  try {
    const saved = await learningApi.breakpoint(sessionId)
    if (seq !== sessionSeq || session.value?.id !== sessionId) return null
    breakpoint.value = saved
    clientSeq = saved.clientSeq
    lastSavedDraft = saved.draftAnswer
    lastSavedMode = saved.inputMode
    const resumed =
      saved.stageStatus === 'WAITING_USER' ||
      Boolean(saved.draftAnswer) ||
      (saved.currentStage !== 'TEACH' && saved.currentStage !== 'NEXT') ||
      messages.value.length > 0
    if (resumed) {
      const parts = [`已恢复上次进度：${stageText(saved.currentStage)}`]
      if (saved.stageStatus === 'WAITING_USER') parts.push('上一个问题仍在等待你回答')
      if (saved.draftAnswer) parts.push('未提交的草稿已恢复')
      resumeNotice.value = parts.join(' · ')
    }
    return saved
  } catch {
    markSaved('error', '断点读取失败，教学状态仍可从后端恢复')
    return null
  }
}

function saveOnExit(): void {
  if (!session.value || !breakpointReady) return
  const sid = session.value.id
  if (draft.value !== lastSavedDraft || inputMode.value !== lastSavedMode) {
    const seq = ++clientSeq
    const body = JSON.stringify({ clientSeq: seq, draftAnswer: draft.value, inputMode: inputMode.value })
    try {
      void fetch(`${apiBase}/learning/sessions/${sid}/breakpoint`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body,
        keepalive: true,
      })
    } catch {
      /* 页面已卸载，无法再提示 */
    }
  }
  if (activityId) {
    try {
      void fetch(`${apiBase}/learning/activities/${activityId}/finish`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ result: 'finished', reason: 'browser_closed' }),
        keepalive: true,
      })
    } catch {
      /* 心跳已保存最后一次有效时间 */
    }
  }
}

const flatPoints = computed(() =>
  (course.value?.chapters ?? []).flatMap((chapter) =>
    chapter.knowledgePoints.map((point) => ({ point, chapterTitle: chapter.title })),
  ),
)

const totalPoints = computed(() => course.value?.knowledgePointCount ?? 0)
const learnedCount = computed(() => {
  const counts = course.value?.statusCounts
  return counts ? counts.total - counts.notStarted : 0
})
const courseProgress = computed(() => course.value?.progress ?? 0)
const modelLabel = computed(() => session.value?.model?.modelName ?? '未配置模型')
const pointStatus = computed(() =>
  flatPoints.value.find(({ point }) => point.id === session.value?.point.id)?.point.learningStatus ?? 'not_started',
)

const flatIndex = computed(() =>
  flatPoints.value.findIndex((item) => item.point.id === session.value?.point.id),
)
const pendingQuestion = computed(() => {
  const last = messages.value[messages.value.length - 1]
  return Boolean(last && last.role === 'user' && !streaming.value)
})

watch(courseId, () => void bootstrap(), { immediate: true })
watch(() => route.query.point, (value) => {
  const pointId = Number(value)
  if (pointId !== activePointId.value && flatPoints.value.some((item) => item.point.id === pointId)) {
    void selectPoint(pointId, { updateUrl: false })
  }
})
watch([draft, inputMode], ([value, mode]) => {
  if (!breakpointReady || suppressDraftSave) return
  if (value === lastSavedDraft && mode === lastSavedMode) return
  scheduleSave()
})

onMounted(() => {
  bindActivityListeners()
  teachingMeta.ensureLoaded()
})

onBeforeUnmount(() => {
  saveOnExit()
  stopHeartbeat()
  activityId = null
  if (saveTimer) window.clearTimeout(saveTimer)
  unbindActivityListeners()
  courseSeq += 1
  sessionSeq += 1
  abortStream()
})

async function bootstrap(): Promise<void> {
  const currentCourse = ++courseSeq
  sessionSeq += 1
  abortStream()
  void endLearningActivity('course_switch')
  breakpointReady = false
  resumeNotice.value = ''
  autosaveState.value = 'idle'
  autosaveNote.value = ''
  course.value = null
  session.value = null
  messages.value = []
  teaching.value = null
  controlBusy.value = false
  const id = courseId.value
  if (!Number.isFinite(id)) {
    errorMessage.value = '课程地址无效'
    return
  }
  loadingCourse.value = true
  errorMessage.value = ''
  try {
    const [detail, availableModels] = await Promise.all([courseLibraryApi.detail(id), modelApi.list()])
    if (currentCourse !== courseSeq) return
    course.value = detail
    models.value = availableModels
    const query = Number(Array.isArray(route.query.point) ? route.query.point[0] : route.query.point)
    const validQuery = flatPoints.value.some((item) => item.point.id === query) ? query : null
    const firstOpen =
      flatPoints.value.find((item) => item.point.learningStatus !== 'completed')?.point.id ?? null
    const target = validQuery ?? firstOpen ?? flatPoints.value[0]?.point.id ?? null
    if (target === null) {
      errorMessage.value = '这门课程还没有知识点，请先在课程详情里添加内容'
      return
    }
    await selectPoint(target, { updateUrl: true })
  } catch (err) {
    if (currentCourse === courseSeq) errorMessage.value = err instanceof ApiError ? err.message : '加载课程失败'
  } finally {
    if (currentCourse === courseSeq) loadingCourse.value = false
  }
}

async function selectPoint(
  pointId: number,
  options: { updateUrl?: boolean } = {},
): Promise<void> {
  if (pointId === activePointId.value && session.value) return

  abortStream()
  void endLearningActivity('switch_point')
  breakpointReady = false
  resumeNotice.value = ''
  autosaveState.value = 'idle'
  autosaveNote.value = ''
  const seq = ++sessionSeq
  activePointId.value = pointId
  session.value = null
  messages.value = []
  draft.value = ''
  teaching.value = null
  controlBusy.value = false
  if (window.innerWidth < 980) catalogOpen.value = false
  expandChapterOf(pointId)
  loadingSession.value = true
  errorMessage.value = ''
  streamError.value = ''

  if (options.updateUrl !== false) {
    void router.replace({
      name: 'classroom',
      params: { id: courseId.value },
      query: { point: String(pointId) },
    })
  }

  try {
    const data = await classroomApi.openSession({
      courseId: courseId.value,
      knowledgePointId: pointId,
    })
    if (seq !== sessionSeq) return
    session.value = data
    activePointId.value = data.point.id
    messages.value = [...data.messages]
    const [, savedBreakpoint] = await Promise.all([
      loadTeaching(data.id, seq),
      restoreBreakpoint(data.id, seq),
      startLearningActivity(data.id),
    ])
    if (seq !== sessionSeq) return
    loadingSession.value = false
    await nextTick()
    if (
      savedBreakpoint?.draftAnswer &&
      savedBreakpoint.currentStage !== 'NEXT' &&
      !draft.value
    ) {
      suppressDraftSave = true
      draft.value = savedBreakpoint.draftAnswer
      inputMode.value = savedBreakpoint.inputMode
      await nextTick()
      suppressDraftSave = false
    }
    breakpointReady = true
    if (data.streaming) {
      void followSession(data.id, seq)
      return
    }
    shouldStick.value = true
    scrollToBottom(true)
    if (data.model) {
      await nextTick()
      void startTeaching()
    }
  } catch (err) {
    if (seq === sessionSeq) {
      errorMessage.value = err instanceof ApiError ? err.message : '打开学习会话失败'
      session.value = null
      messages.value = []
    }
  } finally {
    if (seq === sessionSeq) loadingSession.value = false
  }
}

function acceptTeaching(state: TeachingState): void {
  if (session.value?.id !== state.sessionId) return
  if (teaching.value && teaching.value.sessionId === state.sessionId && teaching.value.revision > state.revision) return
  const previousQuestion = teaching.value?.currentQuestion
  teaching.value = state
  if (state.currentQuestion && state.currentQuestion !== previousQuestion) inputMode.value = 'ANSWER'
  if (!state.currentQuestion) inputMode.value = 'ASK'
  if (breakpointReady) scheduleSave(300)
}

async function loadTeaching(sid: number, seq: number): Promise<void> {
  const state = await classroomApi.teaching(sid)
  if (seq === sessionSeq) acceptTeaching(state)
}

async function startTeaching(): Promise<void> {
  if (teaching.value?.stageStatus !== 'PENDING' || !session.value?.model || teaching.value.paused) return
  await teachingAction('START')
}

async function teachingAction(action: TeachingAction, content = ''): Promise<void> {
  if (!session.value || !teaching.value || controlBusy.value || !teaching.value.allowedActions.includes(action)) return
  const sid = session.value.id
  const seq = sessionSeq
  const payload = { requestId: crypto.randomUUID(), expectedRevision: teaching.value.revision, action, content }
  if (['PAUSE', 'RESUME', 'NEXT', 'RESTART'].includes(action)) {
    controlBusy.value = true
    try {
      const data = await classroomApi.control(sid, payload)
      if (seq !== sessionSeq) return
      acceptTeaching(data.teaching)
      if (action === 'PAUSE' && (streaming.value || session.value?.streaming)) await stopGenerating()
      if (seq !== sessionSeq) return
      if (action === 'RESTART') {
        draft.value = ''
        resumeNotice.value = ''
        lastSavedDraft = ''
        lastSavedMode = 'ASK'
        if (session.value) {
          clientSeq += 1
          void learningApi
            .saveBreakpoint(session.value.id, { clientSeq, draftAnswer: '', inputMode: 'ASK' })
            .catch(() => undefined)
        }
        void restartLearningActivity()
      }
      if (action === 'NEXT') {
        if (data.nextKnowledgePointId) await selectPoint(data.nextKnowledgePointId)
        else if (data.courseComplete) ElMessage.success('已完成目录最后一个知识点；可回课程详情查看整门课的进度。')
      }
    } catch (error) {
      if (seq === sessionSeq) {
        streamError.value = error instanceof ApiError ? error.message : '教学操作失败，请重试'
        await loadTeaching(sid, seq).catch(() => undefined)
      }
    } finally {
      if (seq === sessionSeq) controlBusy.value = false
    }
    if (seq === sessionSeq && ['RESUME', 'RESTART'].includes(action)) void startTeaching()
    return
  }
  if (busy.value || !session.value.model) return
  await runStream(`/classroom/sessions/${sid}/teaching/actions`, payload)
}

async function send(text?: string): Promise<void> {  const content = (text ?? draft.value).trim()
  const action = text === undefined ? inputMode.value : 'ASK'
  if (!content || busy.value || !session.value?.model || !teaching.value?.allowedActions.includes(action)) return
  if (content.length > 8000) {
    streamError.value = '问题最多 8000 字，请缩短后再发送'
    return
  }
  if (text === undefined) draft.value = ''
  messages.value.push({ id: -Date.now(), role: 'user', content, status: 'completed', modelName: '', errorMessage: '', createdAt: new Date().toISOString() })
  shouldStick.value = true
  scrollToBottom(true)
  await teachingAction(action, content)
}

async function regenerate(): Promise<void> {
  await teachingAction('REGENERATE')
}

function submitActivity(value: string): void {
  draft.value = value
  void send()
}

async function runStream(path: string, body: unknown): Promise<void> {
  if (!session.value) return
  const sid = session.value.id
  const seq = sessionSeq
  const ctrl = new AbortController()
  controller = ctrl
  streaming.value = true
  session.value.streaming = true
  stopping.value = false
  streamError.value = ''
  const isCurrent = () => controller === ctrl && sessionSeq === seq && !ctrl.signal.aborted
  let completed = false

  const assistant = reactive<ChatMessage>({
    id: -1,
    role: 'assistant',
    content: '',
    status: 'streaming',
    modelName: session.value.model?.modelName ?? '',
    errorMessage: '',
    createdAt: new Date().toISOString(),
  })
  messages.value.push(assistant)
  scrollToBottom(true)

  try {
    await streamClassroom(
      path,
      body,
      {
        onMeta(meta) {
          if (!isCurrent()) return
          if (meta.teaching) acceptTeaching(meta.teaching)
          assistant.id = meta.messageId
          if (meta.modelName) assistant.modelName = meta.modelName
        },
        onDelta(text) {
          if (!isCurrent()) return
          assistant.content += text
          scrollToBottom()
        },
        onDone(payload) {
          if (!isCurrent()) return
          Object.assign(assistant, payload.message)
          if (payload.teaching) acceptTeaching(payload.teaching)
          completed = payload.status === 'completed'
        },
        onError(message) {
          if (!isCurrent()) return
          assistant.status = 'failed'
          assistant.errorMessage = message
          streamError.value = message
        },
      },
      ctrl.signal,
    )
  } catch (err) {
    if (isCurrent()) {
      const message = err instanceof ApiError ? err.message : '生成回答失败，请稍后重试'
      streamError.value = message
      assistant.status = 'failed'
      assistant.errorMessage = message
    }
  } finally {
    if (controller === ctrl && seq === sessionSeq) {
      controller = null
      streaming.value = false
      if (session.value?.id === sid) session.value.streaming = false
      await refreshSession(sid, seq)
      if (completed && seq === sessionSeq && !streamError.value) void startTeaching()
    }
  }
}

async function stopGenerating(): Promise<void> {
  if ((!streaming.value && !session.value?.streaming) || !session.value || stopping.value) return
  const sid = session.value.id
  const seq = sessionSeq
  const ctrl = controller
  stopping.value = true
  const stopped = classroomApi.stop(sid).catch(() => null)
  ctrl?.abort()
  try {
    await stopped
    await followSession(sid, seq)
  } finally {
    if (seq === sessionSeq) stopping.value = false
  }
}

async function followSession(sid: number, seq: number): Promise<void> {
  while (seq === sessionSeq && session.value?.id === sid) {
    await delay(500)
    if (seq !== sessionSeq) return
    try {
      const [data, state, detail] = await Promise.all([classroomApi.session(sid), classroomApi.teaching(sid), courseLibraryApi.detail(courseId.value)])
      if (seq !== sessionSeq || controller) return
      session.value = data
      messages.value = [...data.messages]
      acceptTeaching(state)
      course.value = detail
      scrollToBottom()
      if (!data.streaming) return
    } catch {
      if (seq === sessionSeq) streamError.value = '暂时无法恢复对话，请检查后端后刷新页面'
      return
    }
  }
}

async function refreshSession(sid: number, seq: number): Promise<void> {
  try {
    const [data, state, detail] = await Promise.all([classroomApi.session(sid), classroomApi.teaching(sid), courseLibraryApi.detail(courseId.value)])
    if (seq === sessionSeq && session.value?.id === sid && !controller) {
      session.value = data
      messages.value = [...data.messages]
      acceptTeaching(state)
      course.value = detail
      if (data.streaming && !stopping.value) void followSession(sid, seq)
    }
  } catch {
    if (seq === sessionSeq && !streamError.value) streamError.value = '回答已显示，但暂时无法确认保存状态，请检查后端后刷新'
  }
}

function abortStream(): void {
  if (controller) {
    if (session.value) void classroomApi.stop(session.value.id).catch(() => null)
    controller.abort()
    controller = null
  }
  streaming.value = false
  stopping.value = false
}

async function changeModel(modelConfigId: number): Promise<void> {
  if (!session.value || busy.value) return
  const seq = sessionSeq
  loadingSession.value = true
  try {
    const data = await classroomApi.openSession({ courseId: courseId.value, knowledgePointId: session.value.point.id, modelConfigId })
    if (seq !== sessionSeq) return
    session.value = data
    streamError.value = ''
    loadingSession.value = false
    void startTeaching()
  } catch (error) {
    if (seq === sessionSeq) streamError.value = error instanceof ApiError ? error.message : '切换模型失败'
  } finally {
    if (seq === sessionSeq) loadingSession.value = false
  }
}

function expandChapterOf(pointId: number): void {
  const chapter = course.value?.chapters.find((item) =>
    item.knowledgePoints.some((point) => point.id === pointId),
  )
  if (chapter && collapsed.value.has(chapter.id)) {
    const next = new Set(collapsed.value)
    next.delete(chapter.id)
    collapsed.value = next
  }
}

function toggleChapter(chapterId: number): void {
  const next = new Set(collapsed.value)
  if (next.has(chapterId)) next.delete(chapterId)
  else next.add(chapterId)
  collapsed.value = next
}

function onQuick(action: QuickAction): void {
  if (busy.value) return
  if (action.id === 'again' || action.id === 'example' || action.id === 'slower') {
    void teachingAction(action.id === 'example' ? 'CHANGE_EXAMPLE' : 'EXPLAIN_AGAIN')
    return
  }
  if (action.id === 'question') {
    inputMode.value = 'ASK'
    void nextTick(() => composerRef.value?.focus())
    return
  }
  if (action.prompt) void send(action.prompt)
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  void send()
}

function onScroll(): void {
  const el = messagesEl.value
  if (!el) return
  shouldStick.value = el.scrollHeight - el.scrollTop - el.clientHeight < 90
}

function scrollToBottom(force = false): void {
  if (!force && !shouldStick.value) return
  void nextTick(() => {
    const el = messagesEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function goCourse(): void {
  void router.push({ name: 'course-detail', params: { id: courseId.value } })
}

function statusClass(status: string): string {
  return `is-${status.replace('_', '-')}`
}

function formatDuration(seconds: number | undefined): string {
  const value = Math.max(0, Math.round(seconds ?? 0))
  const minutes = Math.floor(value / 60)
  const rest = value % 60
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60)
    return `${hours} 小时 ${minutes % 60} 分`
  }
  if (minutes) return `${minutes} 分 ${rest} 秒`
  return `${rest} 秒`
}

function isPointActive(point: KnowledgePoint): boolean {
  return point.id === activePointId.value
}

function chapterPoints(chapter: Chapter): KnowledgePoint[] {
  return chapter.knowledgePoints
}
</script>

<template>
  <div class="classroom" :class="{ 'info-collapsed': !infoOpen }">
    <div v-if="errorMessage && !course" class="page-state">
      <div class="ml-empty">
        <h3>学习教室暂时不可用</h3>
        <p>{{ errorMessage }}</p>
        <el-button type="primary" @click="bootstrap">重试</el-button>
        <el-button @click="goCourse">返回课程详情</el-button>
      </div>
    </div>

    <template v-else>
      <button v-if="catalogOpen" class="catalog-backdrop" type="button" aria-label="关闭课程目录" @click="catalogOpen = false" />
      <aside class="catalog" :class="{ open: catalogOpen }">
        <header class="catalog-head">
          <button class="back-link" type="button" @click="goCourse">
            <el-icon :size="13"><ArrowLeft /></el-icon>
            课程详情
          </button>
          <p class="catalog-kicker">AI 学习教室</p>
          <h2 class="catalog-title">
            <span v-if="course?.icon" class="catalog-icon">{{ course.icon }}</span>
            {{ course?.title ?? '加载中…' }}
          </h2>
          <div class="catalog-progress">
            <span>{{ courseProgress }}%</span>
            <div class="catalog-track"><div class="catalog-fill" :style="{ width: `${courseProgress}%` }" /></div>
          </div>
        </header>

        <nav class="catalog-body" aria-label="课程目录">
          <div v-for="(chapter, chapterIndex) in course?.chapters" :key="chapter.id" class="chapter-group">
            <button class="chapter-row" type="button" :aria-expanded="!collapsed.has(chapter.id)" @click="toggleChapter(chapter.id)">
              <span class="chevron" :class="{ open: !collapsed.has(chapter.id) }">›</span>
              <span class="chapter-index">{{ String(chapterIndex + 1).padStart(2, '0') }}</span>
              <span class="chapter-name">{{ chapter.title }}</span>
              <span class="chapter-count">{{ chapter.knowledgePoints.length }}</span>
            </button>
            <ul v-show="!collapsed.has(chapter.id)" class="point-list">
              <li v-for="point in chapterPoints(chapter)" :key="point.id">
                <button
                  class="point-row"
                  type="button"
                  :class="{ active: isPointActive(point) }"
                  :aria-current="isPointActive(point) ? 'step' : undefined"
                  @click="selectPoint(point.id)"
                >
                  <span class="point-dot" :class="statusClass(point.learningStatus)" />
                  <span class="point-title">{{ point.title }}</span>
                  <span v-if="isPointActive(point)" class="point-current">当前</span>
                  <span v-else class="point-state">{{ statusLabel(point.learningStatus) }}</span>
                </button>
              </li>
            </ul>
          </div>
          <p v-if="course && !course.chapters.length" class="catalog-empty">这门课程还没有目录。</p>
        </nav>

        <footer class="catalog-foot">记录保存在本机 · 当前教材与对话会发送给所选模型</footer>
      </aside>

      <!-- 中：AI 教学区 -->
      <section class="stage">
        <header class="stage-head">
          <button class="icon-btn nav-toggle" type="button" aria-label="打开课程目录" @click="catalogOpen = !catalogOpen">
            <el-icon :size="16"><Menu /></el-icon>
          </button>
          <div class="stage-title">
            <p class="stage-eyebrow">
              {{ session?.point.chapterTitle ?? '正在载入章节' }}
              <template v-if="flatIndex >= 0">
                <span class="dot">·</span>
                第 {{ flatIndex + 1 }} / {{ flatPoints.length }} 个知识点
              </template>
            </p>
            <h1>{{ session?.point.title ?? '正在打开学习教室' }}</h1>
          </div>
          <div class="stage-actions">
            <div v-if="session" class="learning-status-actions">
              <span class="ml-status" :class="statusClass(pointStatus)" role="status">{{ statusLabel(pointStatus) }}</span>
            </div>
            <el-button
              link
              :icon="ArrowLeft"
              :disabled="!session?.point.previousId"
              title="上一个知识点"
              aria-label="上一个知识点"
              @click="session?.point.previousId && selectPoint(session.point.previousId)"
            />
            <el-button
              link
              :icon="ArrowRight"
              :disabled="!session?.point.nextId"
              title="下一个知识点"
              aria-label="下一个知识点"
              @click="session?.point.nextId && selectPoint(session.point.nextId)"
            />
            <button v-if="!infoOpen" class="icon-btn" type="button" aria-label="展开学习信息" @click="infoOpen = true">
              <el-icon :size="15"><Expand /></el-icon>
            </button>
          </div>
        </header>

        <div v-if="resumeNotice" class="resume-note" role="status">
          <span>{{ resumeNotice }}</span>
          <button type="button" @click="resumeNotice = ''">知道了</button>
        </div>

        <TeachingFlowPanel v-if="teaching" :state="teaching" :busy="busy" :control-busy="controlBusy" :has-model="Boolean(session?.model)" @action="teachingAction" />

        <div v-loading="loadingCourse || loadingSession" class="conversation" ref="messagesEl" @scroll="onScroll">
          <div class="conversation-inner">
            <div v-if="errorMessage" role="alert" class="stream-error">{{ errorMessage }}</div>
            <p v-if="session?.streaming && !streaming" class="pending-hint">正在同步这个知识点的回答…</p>
            <div v-if="streamError" class="stream-error">
              <el-icon :size="15"><Warning /></el-icon>
              <span>{{ streamError }}</span>
              <el-button
                v-if="!busy && session?.model"
                link
                type="primary"
                @click="streamError = ''; regenerate()"
              >重新生成</el-button>
              <el-button link @click="streamError = ''">关闭</el-button>
            </div>

            <div v-if="!session?.model" class="model-missing">
              <strong>还没有可用的模型配置</strong>
              <p>学习教室需要调用你配置的 OpenAI 兼容模型。密钥只保存在后端。</p>
              <el-button type="primary" size="small" @click="router.push({ name: 'models' })">去配置模型</el-button>
            </div>

            <p v-if="pendingQuestion" class="pending-hint">
              上一个问题还没有回答。可以点「重新生成」继续，或重新发送。
            </p>

            <article v-for="(message, index) in messages" :key="`${message.id}-${index}`" class="turn" :class="message.role">
              <header class="turn-head">
                <span class="turn-avatar">{{ message.role === 'assistant' ? 'AI' : '你' }}</span>
                <span class="turn-role">{{ message.role === 'assistant' ? 'AI 老师' : '我的提问' }}</span>
                <span v-if="message.role === 'assistant' && message.modelName" class="turn-model">{{ message.modelName }}</span>
                <span v-if="message.status === 'interrupted'" class="turn-flag">已停止</span>
                <span v-if="message.status === 'failed'" class="turn-flag is-error">生成失败</span>
              </header>

              <template v-if="message.role === 'assistant'">
                <div v-if="!message.content && message.status === 'streaming'" class="thinking">
                  <span class="thinking-dot" />
                  <span class="thinking-dot" />
                  <span class="thinking-dot" />
                  <span>老师正在组织讲解…</span>
                </div>
                <div v-else class="md-body turn-body" v-html="renderMarkdown(message.content)" />
              </template>
              <div v-else class="turn-body student-text">{{ message.content }}</div>

              <p v-if="message.errorMessage" class="turn-error">{{ message.errorMessage }}</p>
            </article>

            <div v-if="!messages.length && !streaming && !loadingSession" class="empty-hint">
              <h3>准备开始这个知识点的学习</h3>
              <p>老师会先讲清楚它解决什么问题，再给出完整示例，最后逐步解释关键步骤。</p>
            </div>
          </div>
        </div>

        <footer class="composer">
          <div class="quick-row">
            <button
              v-for="action in QUICK_ACTIONS.filter(item => ['project', 'code', 'question'].includes(item.id))"
              :key="action.id"
              type="button"
              class="quick-chip"
              :disabled="busy || !session?.model || !teaching?.allowedActions.includes('ASK')"
              @click="onQuick(action)"
            >
              {{ action.label }}
            </button>
          </div>
          <div v-if="teaching?.currentQuestion" class="input-mode">
            <el-radio-group v-model="inputMode" size="small" :disabled="busy || teaching.paused">
              <el-radio-button value="ANSWER">提交回答</el-radio-button>
              <el-radio-button value="ASK">自由提问</el-radio-button>
            </el-radio-group>
            <span>只有提交回答会进行评价；自由提问不会推进阶段。</span>
          </div>
          <div class="composer-box">
            <ActivityRenderer
              v-if="inputMode === 'ANSWER' && teaching?.currentActivity"
              :key="teaching.currentActivity.id"
              :activity="teaching.currentActivity"
              :model-value="draft"
              :disabled="!session || loadingSession || busy || teaching?.paused"
              @update:model-value="draft = $event"
              @submit="submitActivity"
              @regenerate="regenerate"
            />
            <el-input
              v-else
              ref="composerRef"
              v-model="draft"
              type="textarea"
              resize="none"
              :autosize="{ minRows: 2, maxRows: 6 }"
              :disabled="!session || loadingSession || teaching?.paused"
              aria-label="向 AI 老师提问"
              :maxlength="8000"
              :placeholder="inputMode === 'ANSWER' ? '写下你的解释或回答……（Enter 提交，Shift+Enter 换行）' : '随时向老师提问……（Enter 发送，Shift+Enter 换行）'"
              @keydown="onKeydown"
            />
            <div class="composer-actions">
              <span class="composer-hint" :class="{ 'is-error': autosaveState === 'error' }">
                Enter 发送 · Shift+Enter 换行 · {{ autosaveLabel }}
              </span>
              <div class="composer-buttons">
                <el-button
                  v-if="streaming || session?.streaming || stopping"
                  type="danger"
                  plain
                  size="small"
                  :icon="VideoPause"
                  :loading="stopping"
                  @click="stopGenerating"
                >停止生成</el-button>
                <el-button
                  v-else
                  size="small"
                  :icon="Refresh"
                  :disabled="busy || !session?.model || !teaching?.allowedActions.includes('REGENERATE')"
                  @click="regenerate"
                >重新生成</el-button>
                <el-button
                  type="primary"
                  size="small"
                  :icon="Promotion"
                  :disabled="busy || controlBusy || !draft.trim() || !session?.model || !teaching?.allowedActions.includes(inputMode)"
                  :loading="streaming"
                  @click="send()"
                >{{ inputMode === 'ANSWER' ? '提交回答' : '发送' }}</el-button>
              </div>
            </div>
          </div>
        </footer>
      </section>

      <!-- 右：学习信息 -->
      <aside v-if="infoOpen" class="info">
        <header class="info-head">
          <span>学习信息</span>
          <button class="icon-btn" type="button" aria-label="收起学习信息" @click="infoOpen = false">
            <el-icon :size="15"><Fold /></el-icon>
          </button>
        </header>

        <section class="info-block">
          <p class="info-label">课程</p>
          <p class="info-value">{{ session?.course.title ?? course?.title ?? '—' }}</p>
          <div class="info-progress">
            <span>{{ courseProgress }}%</span>
            <div class="info-track"><div class="info-fill" :style="{ width: `${courseProgress}%` }" /></div>
          </div>
          <p class="info-note">{{ learnedCount }} / {{ totalPoints }} 个知识点已开始学习</p>
        </section>

        <section class="info-block">
          <p class="info-label">当前章节</p>
          <p class="info-value small">{{ session?.point.chapterTitle ?? '—' }}</p>
        </section>

        <section class="info-block">
          <p class="info-label">当前知识点</p>
          <p class="info-value">{{ session?.point.title ?? '—' }}</p>
          <span class="ml-status" :class="statusClass(pointStatus)">{{ statusLabel(pointStatus) }}</span>
          <p v-if="session?.point.description" class="info-note clamp">{{ session.point.description }}</p>
        </section>

        <section class="info-block">
          <p class="info-label">AI 模型</p>
          <el-select
            :model-value="session?.model?.id"
            aria-label="选择教学模型"
            placeholder="选择模型"
            :disabled="busy || !session"
            @change="changeModel"
          >
            <el-option v-for="model in models" :key="model.id" :value="model.id" :label="model.name" />
          </el-select>
          <p class="info-value small">{{ modelLabel }}</p>
          <p v-if="session?.model" class="info-note">{{ session.model.name }}</p>
          <p v-else class="info-note">请先在「模型配置」中添加并测试连接</p>
        </section>

        <section class="info-block">
          <p class="info-label">本次会话</p>
          <p class="info-value small">{{ messages.length }} 条消息</p>
          <p class="info-note">最近更新 {{ formatRelative(session?.lastMessageAt) }}</p>
        </section>

        <section class="info-block">
          <p class="info-label">本次学习活动</p>
          <p class="info-value small">{{ activity ? formatDuration(activity.activeSeconds) : '正在记录…' }}</p>
          <p class="info-note">每 30 秒上报有效时长；空闲超过 5 分钟自动暂停计时。</p>
          <p class="info-note">{{ autosaveLabel }}</p>
        </section>

        <section class="info-block">
          <p class="info-label">学习状态</p>
          <dl class="info-stats">
            <div><dt>{{ learnedCount }}</dt><dd>已学习</dd></div>
            <div><dt>{{ totalPoints }}</dt><dd>知识点</dd></div>
            <div><dt>{{ courseProgress }}%</dt><dd>课程进度</dd></div>
          </dl>
          <p class="info-note">通过本轮 VERIFY 后更新完成状态；旧手工完成不代表教学验证。代码片段尚未实际运行。</p>
        </section>
      </aside>
    </template>
  </div>
</template>

<style scoped>
.classroom {
  --catalog-w: 248px;
  --info-w: 300px;
  display: grid;
  grid-template-columns: var(--catalog-w) minmax(0, 1fr) var(--info-w);
  height: 100vh;
  overflow: hidden;
  background: var(--ml-bg);
}

.classroom.info-collapsed {
  --info-w: 0px;
}

.catalog-backdrop { display: none; }

.info .el-select { margin-bottom: 10px; width: 100%; }

.page-state {
  grid-column: 1 / -1;
  display: grid;
  place-items: center;
  padding: 40px;
}

/* ---------------- 左栏 ---------------- */

.catalog {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--ml-border);
  background: var(--ml-bg-soft);
}

.catalog-head {
  padding: 20px 16px 16px;
  border-bottom: 1px solid var(--ml-border);
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0;
  border: none;
  background: none;
  color: var(--ml-text-3);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
}

.back-link:hover {
  color: var(--ml-text);
}

.catalog-kicker {
  margin-top: 18px;
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--ml-text-3);
}

.catalog-title {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  margin-top: 5px;
  font-size: 15px;
  line-height: 1.45;
}

.catalog-icon {
  flex: none;
}

.catalog-progress {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  font-family: var(--ml-font-mono);
  font-size: 11px;
  color: var(--ml-text-3);
}

.catalog-track,
.info-track {
  flex: 1;
  height: 3px;
  border-radius: 2px;
  background: var(--ml-surface-3);
  overflow: hidden;
}

.catalog-fill,
.info-fill {
  height: 100%;
  background: var(--ml-accent);
  border-radius: 2px;
}

.catalog-body {
  flex: 1;
  overflow-y: auto;
  padding: 10px 8px 24px;
}

.chapter-group + .chapter-group {
  margin-top: 4px;
}

.chapter-row {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 7px 8px;
  border: none;
  border-radius: var(--ml-radius-sm);
  background: none;
  color: var(--ml-text-2);
  font-family: inherit;
  font-size: 12.5px;
  text-align: left;
  cursor: pointer;
}

.chapter-row:hover {
  background: var(--ml-surface);
  color: var(--ml-text);
}

.chevron {
  display: inline-block;
  width: 12px;
  color: var(--ml-text-3);
  transition: transform 0.12s ease;
}

.chevron.open {
  transform: rotate(90deg);
}

.chapter-index {
  font-family: var(--ml-font-mono);
  font-size: 10.5px;
  color: var(--ml-text-3);
}

.chapter-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}

.chapter-count {
  font-family: var(--ml-font-mono);
  font-size: 10.5px;
  color: var(--ml-text-3);
}

.point-list {
  list-style: none;
  margin: 0;
  padding: 0 0 4px;
}

.point-row {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  padding: 6px 8px 6px 26px;
  border: none;
  border-radius: var(--ml-radius-sm);
  background: none;
  color: var(--ml-text-3);
  font-family: inherit;
  font-size: 12.5px;
  text-align: left;
  cursor: pointer;
}

.point-row:hover {
  background: var(--ml-surface);
  color: var(--ml-text-2);
}

.point-row.active {
  background: var(--ml-accent-weak);
  color: var(--ml-text);
}

.point-dot {
  flex: none;
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
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.point-state {
  font-size: 10.5px;
  color: var(--ml-text-3);
}

.point-current {
  font-size: 10.5px;
  color: var(--ml-accent);
}

.catalog-empty {
  padding: 12px;
  font-size: 12.5px;
  color: var(--ml-text-3);
}

.catalog-foot {
  padding: 12px 16px;
  border-top: 1px solid var(--ml-border);
  font-size: 11px;
  color: var(--ml-text-3);
}

/* ---------------- 中栏 ---------------- */

.stage {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  background: var(--ml-bg);
}

.resume-note {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 7px 28px;
  border-bottom: 1px solid color-mix(in srgb, var(--ml-accent) 26%, var(--ml-border));
  background: color-mix(in srgb, var(--ml-accent) 8%, transparent);
  color: var(--ml-text-2);
  font-size: 12px;
}

.resume-note button {
  padding: 0;
  border: none;
  background: none;
  color: var(--ml-accent);
  font: inherit;
  cursor: pointer;
  white-space: nowrap;
}

.input-mode { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 8px; font-size: 11px; color: var(--ml-text-3); }

.stage-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 28px;
  border-bottom: 1px solid var(--ml-border);
  background: var(--ml-bg-soft);
}

.stage-title {
  flex: 1;
  min-width: 0;
}

.stage-eyebrow {
  font-size: 11.5px;
  color: var(--ml-text-3);
}

.stage-eyebrow .dot {
  margin: 0 5px;
}

.stage-title h1 {
  margin-top: 2px;
  font-size: 16px;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stage-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.learning-status-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-right: 8px;
}

.status-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 28px;
  border-bottom: 1px solid var(--ml-border);
  color: var(--el-color-danger);
  font-size: 12px;
}

.nav-toggle {
  display: none !important;
}

.icon-btn {
  display: inline-grid;
  place-items: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: var(--ml-radius-sm);
  background: transparent;
  color: var(--ml-text-2);
  cursor: pointer;
}

.icon-btn:hover {
  border-color: var(--ml-border);
  background: var(--ml-surface-2);
  color: var(--ml-text);
}

.conversation {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scroll-behavior: smooth;
}

.conversation-inner {
  width: min(100%, 820px);
  margin: 0 auto;
  padding: 30px 36px 40px;
}

.stream-error {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 18px;
  padding: 9px 12px;
  border: 1px solid color-mix(in srgb, var(--ml-danger) 36%, var(--ml-border));
  border-radius: var(--ml-radius);
  background: color-mix(in srgb, var(--ml-danger) 8%, transparent);
  color: var(--ml-danger);
  font-size: 12.5px;
}

.stream-error span {
  flex: 1;
}

.model-missing {
  margin-bottom: 18px;
  padding: 14px 16px;
  border: 1px solid var(--ml-border-strong);
  border-radius: var(--ml-radius);
  background: var(--ml-surface);
}

.model-missing strong {
  font-size: 13.5px;
}

.model-missing p {
  margin: 4px 0 10px;
  font-size: 12.5px;
  color: var(--ml-text-3);
}

.pending-hint {
  margin-bottom: 16px;
  padding: 8px 12px;
  border-left: 2px solid var(--ml-warning);
  background: var(--ml-surface);
  color: var(--ml-text-3);
  font-size: 12.5px;
}

.turn {
  padding: 18px 0;
  border-top: 1px solid var(--ml-border);
}

.turn:first-of-type {
  border-top: none;
}

.turn-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.turn-avatar {
  display: inline-grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  background: var(--ml-surface-2);
  border: 1px solid var(--ml-border);
  font-family: var(--ml-font-mono);
  font-size: 10px;
  color: var(--ml-text-2);
}

.turn.assistant .turn-avatar {
  background: var(--ml-accent-weak);
  border-color: color-mix(in srgb, var(--ml-accent) 35%, var(--ml-border));
  color: var(--ml-accent);
}

.turn-role {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ml-text-2);
}

.turn-model {
  font-family: var(--ml-font-mono);
  font-size: 10.5px;
  color: var(--ml-text-3);
}

.turn-flag {
  padding: 0 6px;
  border-radius: 999px;
  background: var(--ml-surface-2);
  font-size: 10.5px;
  color: var(--ml-text-3);
}

.turn-flag.is-error {
  background: color-mix(in srgb, var(--ml-danger) 12%, transparent);
  color: var(--ml-danger);
}

.turn-body {
  font-size: 14px;
  line-height: 1.8;
}

.turn.assistant .turn-body {
  color: var(--ml-text-2);
}

.student-text {
  padding: 10px 14px;
  border-left: 2px solid var(--ml-accent);
  border-radius: 0 var(--ml-radius) var(--ml-radius) 0;
  background: var(--ml-surface);
  color: var(--ml-text);
  white-space: pre-wrap;
}

.turn-error {
  margin-top: 8px;
  font-size: 12px;
  color: var(--ml-danger);
}

.thinking {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ml-text-3);
  font-size: 13px;
}

.thinking-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--ml-accent);
  animation: thinking 1.2s infinite ease-in-out;
}

.thinking-dot:nth-child(2) {
  animation-delay: 0.15s;
}

.thinking-dot:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes thinking {
  0%,
  70%,
  100% {
    opacity: 0.25;
    transform: translateY(0);
  }
  35% {
    opacity: 1;
    transform: translateY(-3px);
  }
}

.empty-hint {
  padding: 48px 20px;
  text-align: center;
  color: var(--ml-text-3);
}

.empty-hint h3 {
  margin-bottom: 6px;
  font-size: 15px;
  color: var(--ml-text-2);
}

.empty-hint p {
  font-size: 13px;
}

/* ---------------- 输入区 ---------------- */

.composer {
  padding: 10px 28px 18px;
  border-top: 1px solid var(--ml-border);
  background: var(--ml-bg-soft);
}

.quick-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  width: min(100%, 820px);
  margin: 0 auto 8px;
}

.quick-chip {
  padding: 3px 10px;
  border: 1px solid var(--ml-border);
  border-radius: 999px;
  background: var(--ml-surface);
  color: var(--ml-text-3);
  font-family: inherit;
  font-size: 11.5px;
  cursor: pointer;
  transition: border-color 0.12s ease, color 0.12s ease;
}

.quick-chip:hover:not(:disabled) {
  border-color: var(--ml-border-strong);
  color: var(--ml-text);
}

.quick-chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.composer-box {
  width: min(100%, 820px);
  margin: 0 auto;
  padding: 8px 10px 6px;
  border: 1px solid var(--ml-border-strong);
  border-radius: var(--ml-radius-lg);
  background: var(--ml-surface);
}

.composer-box:focus-within {
  border-color: color-mix(in srgb, var(--ml-accent) 60%, var(--ml-border-strong));
}

.composer-box :deep(.el-textarea__inner) {
  padding: 4px 4px 8px;
  border: none;
  background: transparent;
  box-shadow: none;
  color: var(--ml-text);
  font-family: inherit;
  font-size: 13.5px;
  line-height: 1.65;
}

.composer-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 6px;
  border-top: 1px solid var(--ml-border);
}

.composer-hint {
  font-size: 10.5px;
  color: var(--ml-text-3);
}

.composer-hint.is-error {
  color: var(--ml-warning);
}

.composer-buttons {
  display: flex;
  gap: 6px;
}

/* ---------------- 右栏 ---------------- */

.info {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow-y: auto;
  border-left: 1px solid var(--ml-border);
  background: var(--ml-bg-soft);
}

.info-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 1;
  padding: 16px 18px;
  border-bottom: 1px solid var(--ml-border);
  background: var(--ml-bg-soft);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--ml-text-2);
}

.info-block {
  padding: 14px 18px;
  border-bottom: 1px solid var(--ml-border);
}

.info-label {
  margin-bottom: 5px;
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ml-text-3);
}

.info-value {
  font-size: 13px;
  line-height: 1.55;
  color: var(--ml-text);
}

.info-value.small {
  font-size: 12.5px;
  color: var(--ml-text-2);
}

.info-note {
  margin-top: 5px;
  font-size: 11.5px;
  line-height: 1.55;
  color: var(--ml-text-3);
}

.info-note.clamp {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.info-progress {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 9px;
  font-family: var(--ml-font-mono);
  font-size: 10.5px;
  color: var(--ml-text-3);
}

.info-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin: 6px 0 0;
}

.info-stats div {
  min-width: 0;
}

.info-stats dt {
  font-family: var(--ml-font-mono);
  font-size: 15px;
  color: var(--ml-text);
}

.info-stats dd {
  margin: 1px 0 0;
  font-size: 10.5px;
  color: var(--ml-text-3);
}

/* ---------------- 响应式 ---------------- */

@media (max-width: 1240px) {
  .classroom {
    --info-w: 272px;
  }
}

@media (max-width: 1100px) {
  .classroom {
    --info-w: 0px;
  }

  .info {
    position: fixed;
    inset: 0 0 0 auto;
    width: 272px;
    z-index: 35;
    box-shadow: -12px 0 40px rgba(0, 0, 0, 0.3);
  }
}

@media (max-width: 980px) {
  .catalog-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 29;
    border: 0;
    background: rgba(0, 0, 0, 0.45);
  }
  .classroom {
    grid-template-columns: minmax(0, 1fr);
  }

  .catalog {
    position: fixed;
    inset: 0 auto 0 0;
    z-index: 30;
    width: 272px;
    transform: translateX(-100%);
    transition: transform 0.18s ease;
    box-shadow: 0 0 40px rgba(0, 0, 0, 0.35);
  }

  .catalog.open {
    transform: translateX(0);
  }

  .nav-toggle {
    display: inline-grid !important;
  }

  .stage-head {
    padding: 12px 16px;
  }

  .conversation-inner {
    padding: 24px 20px 32px;
  }

  .composer {
    padding: 8px 16px 14px;
  }

  .composer-hint {
    display: none;
  }
}
@media (max-width: 640px) {
  .stage-head {
    flex-wrap: wrap;
  }

  .stage-actions {
    width: 100%;
    justify-content: flex-end;
  }

  .status-error {
    padding: 10px 16px;
  }
}
</style>

import { apiBase, ApiError, request } from './client'
import type {
  Chapter,
  ChapterPointOrder,
  ClassroomContext,
  ClassroomSession,
  CourseDetail,
  CourseProgress,
  CourseSort,
  CourseSummary,
  HealthPayload,
  KnowledgePointDetail,
  KnowledgePointSummary,
  LearningStatus,
  ModelConfig,
  ModelConfigCreatePayload,
  ModelConfigUpdatePayload,
  ModelTestPayload,
  ModelTestResult,
  SessionOpenPayload,
  StopStreamResult,
  TeachingMeta,
  ArchiveOverview,
  BreakpointState,
  CourseLearningProgress,
  LearningActivityState,
  LearningHistoryDetail,
  LearningHistoryPage,
  LearningReport,
  MasteryOverview,
  MistakeDetail,
  MistakePage,
  MistakeRecord,
  ResumeInfo,
} from './types'

export const systemApi = {
  health: () => request<HealthPayload>('/health'),
  teachingMeta: () => request<TeachingMeta>('/meta/teaching'),
}

export const modelApi = {
  list: () => request<ModelConfig[]>('/models'),
  get: (id: number) => request<ModelConfig>(`/models/${id}`),
  create: (payload: ModelConfigCreatePayload) =>
    request<ModelConfig>('/models', { method: 'POST', body: JSON.stringify(payload) }),
  update: (id: number, payload: ModelConfigUpdatePayload) =>
    request<ModelConfig>(`/models/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  remove: (id: number) => request<null>(`/models/${id}`, { method: 'DELETE' }),
  test: (payload: ModelTestPayload) =>
    request<ModelTestResult>('/models/test', { method: 'POST', body: JSON.stringify(payload) }),
}

/**
 * 课程中心与课程详情用（P1.2）。
 * 全部走 `/courses/{courseId}/...` 的课程内路径，后端会校验被操作的章节/知识点属于该课程。
 */
export const courseLibraryApi = {
  list: (params: { q?: string; sort?: CourseSort } = {}) => {
    const search = new URLSearchParams()
    if (params.q?.trim()) search.set('q', params.q.trim())
    if (params.sort) search.set('sort', params.sort)
    const query = search.toString()
    return request<CourseSummary[]>(`/courses${query ? `?${query}` : ''}`)
  },
  detail: (courseId: number) => request<CourseDetail>(`/courses/${courseId}`),
  progress: (courseId: number) => request<CourseProgress>(`/courses/${courseId}/progress`),
  update: (
    courseId: number,
    payload: { title?: string; description?: string; icon?: string },
  ) => request<CourseDetail>(`/courses/${courseId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  remove: (courseId: number) => request<null>(`/courses/${courseId}`, { method: 'DELETE' }),

  addChapter: (courseId: number, payload: { title: string; description?: string }) =>
    request<CourseDetail>(`/courses/${courseId}/chapters`, { method: 'POST', body: JSON.stringify(payload) }),
  updateChapter: (courseId: number, chapterId: number, payload: { title?: string; description?: string }) =>
    request<CourseDetail>(`/courses/${courseId}/chapters/${chapterId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  removeChapter: (courseId: number, chapterId: number) =>
    request<CourseDetail>(`/courses/${courseId}/chapters/${chapterId}`, { method: 'DELETE' }),
  reorderChapters: (courseId: number, ids: number[]) =>
    request<CourseDetail>(`/courses/${courseId}/chapters/reorder`, {
      method: 'PATCH',
      body: JSON.stringify({ ids }),
    }),

  points: (courseId: number, params: { status?: LearningStatus; q?: string } = {}) => {
    const search = new URLSearchParams()
    if (params.status) search.set('status', params.status)
    if (params.q?.trim()) search.set('q', params.q.trim())
    const query = search.toString()
    return request<KnowledgePointSummary[]>(`/courses/${courseId}/knowledge-points${query ? `?${query}` : ''}`)
  },
  point: (pointId: number) => request<KnowledgePointDetail>(`/knowledge-points/${pointId}`),
  addPoint: (courseId: number, chapterId: number, payload: { title: string; description?: string; content?: string }) =>
    request<CourseDetail>(`/courses/${courseId}/chapters/${chapterId}/knowledge-points`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updatePoint: (
    courseId: number,
    pointId: number,
    payload: { title?: string; description?: string; content?: string },
  ) =>
    request<CourseDetail>(`/courses/${courseId}/knowledge-points/${pointId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  removePoint: (courseId: number, pointId: number) =>
    request<CourseDetail>(`/courses/${courseId}/knowledge-points/${pointId}`, { method: 'DELETE' }),
  reorderPoints: (courseId: number, chapterId: number, ids: number[]) =>
    request<CourseDetail>(`/courses/${courseId}/chapters/${chapterId}/knowledge-points/reorder`, {
      method: 'PATCH',
      body: JSON.stringify({ ids }),
    }),
  setPointStatus: (courseId: number, pointId: number, status: LearningStatus) =>
    request<CourseDetail>(`/courses/${courseId}/knowledge-points/${pointId}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    }),
  chapters: (courseId: number) => request<Chapter[]>(`/courses/${courseId}/chapters`),
}

/** 教材导入流程用（P1.1 的扁平路径，后端继续保留；导入页还要用到草稿的增删改序） */
export const courseApi = {
  list: () => request<CourseSummary[]>('/courses'),
  detail: (id: number) => request<CourseDetail>(`/courses/${id}`),
  update: (id: number, payload: { title?: string; description?: string }) =>
    request<CourseDetail>(`/courses/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  confirm: (id: number) => request<CourseDetail>(`/courses/${id}/confirm`, { method: 'POST' }),
  remove: (id: number) => request<null>(`/courses/${id}`, { method: 'DELETE' }),

  addChapter: (courseId: number, title: string) =>
    request<CourseDetail>(`/courses/${courseId}/chapters`, {
      method: 'POST',
      body: JSON.stringify({ title }),
    }),
  updateChapter: (chapterId: number, payload: { title?: string; description?: string }) =>
    request<CourseDetail>(`/chapters/${chapterId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  removeChapter: (chapterId: number) => request<CourseDetail>(`/chapters/${chapterId}`, { method: 'DELETE' }),

  addPoint: (chapterId: number, title: string) =>
    request<CourseDetail>(`/chapters/${chapterId}/knowledge-points`, {
      method: 'POST',
      body: JSON.stringify({ title }),
    }),
  updatePoint: (pointId: number, payload: { title?: string; description?: string; content?: string }) =>
    request<CourseDetail>(`/knowledge-points/${pointId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  removePoint: (pointId: number) => request<CourseDetail>(`/knowledge-points/${pointId}`, { method: 'DELETE' }),

  reorder: (courseId: number, payload: { chapters: number[]; knowledgePoints: ChapterPointOrder[] }) =>
    request<CourseDetail>(`/courses/${courseId}/reorder`, { method: 'PATCH', body: JSON.stringify(payload) }),
}

export interface UploadProgress {
  loaded: number
  total: number
  percent: number
}

/** 教材上传：用 XHR 才能拿到上传进度（fetch 不提供 upload progress）。 */
export function uploadCourseMaterial(
  file: File,
  onProgress?: (progress: UploadProgress) => void,
): Promise<CourseDetail> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${apiBase}/courses/upload`)

    xhr.upload.onprogress = (event) => {
      if (!onProgress || !event.lengthComputable) return
      onProgress({
        loaded: event.loaded,
        total: event.total,
        percent: Math.max(1, Math.round((event.loaded / event.total) * 100)),
      })
    }

    xhr.onerror = () => reject(new ApiError('上传失败：无法连接后端服务'))
    xhr.onabort = () => reject(new ApiError('上传已取消'))
    xhr.onload = () => {
      let payload: { code?: number; message?: string; data?: CourseDetail } | null = null
      try {
        payload = JSON.parse(xhr.responseText)
      } catch {
        payload = null
      }
      if (xhr.status >= 200 && xhr.status < 300 && payload?.code === 0 && payload.data) {
        resolve(payload.data)
        return
      }
      reject(
        new ApiError(
          payload?.message ?? `上传失败（HTTP ${xhr.status}）`,
          payload?.code ?? xhr.status,
          xhr.status,
        ),
      )
    }

    const form = new FormData()
    form.append('file', file)
    xhr.send(form)
  })
}

/** AI 学习教室（P1.3）：会话、上下文与停止生成。流式接口见 api/classroomStream.ts */
export const classroomApi = {
  teaching: (sessionId: number) => request<import('./types').TeachingState>(`/classroom/sessions/${sessionId}/teaching`),
  control: (sessionId: number, payload: { requestId: string; expectedRevision: number; action: import('./types').TeachingAction }) =>
    request<{ teaching: import('./types').TeachingState; nextKnowledgePointId: number | null; courseComplete: boolean }>(`/classroom/sessions/${sessionId}/teaching/control`, { method: 'POST', body: JSON.stringify(payload) }),
  context: (courseId: number, pointId: number) =>
    request<ClassroomContext>(`/classroom/context?courseId=${courseId}&pointId=${pointId}`),
  openSession: (payload: SessionOpenPayload) =>
    request<ClassroomSession>('/classroom/sessions', { method: 'POST', body: JSON.stringify(payload) }),
  session: (sessionId: number) => request<ClassroomSession>(`/classroom/sessions/${sessionId}`),
  stop: (sessionId: number) =>
    request<StopStreamResult>(`/classroom/sessions/${sessionId}/stop`, { method: 'POST' }),
}

function queryString(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}

/** 学习档案、学习历史、错题与断点续学（P1.5） */
export const learningApi = {
  startActivity: (payload: { courseId: number; knowledgePointId: number; sessionId?: number }) =>
    request<LearningActivityState>('/learning/activities/start', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  heartbeat: (activityId: number, activeSecondsDelta: number) =>
    request<LearningActivityState>(`/learning/activities/${activityId}/heartbeat`, {
      method: 'POST',
      body: JSON.stringify({ activeSecondsDelta }),
    }),
  finishActivity: (
    activityId: number,
    payload: { result?: 'finished' | 'completed' | 'interrupted'; reason?: string } = {},
  ) =>
    request<LearningActivityState>(`/learning/activities/${activityId}/finish`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  resume: () => request<ResumeInfo | null>('/learning/resume'),
  breakpoint: (sessionId: number) =>
    request<BreakpointState>(`/learning/sessions/${sessionId}/breakpoint`),
  saveBreakpoint: (
    sessionId: number,
    payload: { clientSeq: number; draftAnswer: string; inputMode: 'ASK' | 'ANSWER' },
  ) =>
    request<BreakpointState>(`/learning/sessions/${sessionId}/breakpoint`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),

  overview: () => request<ArchiveOverview>('/learning/overview'),
  courses: () => request<CourseLearningProgress[]>('/learning/courses'),
  mastery: (params: { courseId?: number; chapterId?: number } = {}) =>
    request<MasteryOverview>(
      `/learning/mastery${queryString({ courseId: params.courseId, chapterId: params.chapterId })}`,
    ),
  history: (
    params: {
      courseId?: number
      pointId?: number
      from?: string
      to?: string
      limit?: number
      offset?: number
    } = {},
  ) => request<LearningHistoryPage>(`/learning/history${queryString(params)}`),
  historyDetail: (activityId: number) =>
    request<LearningHistoryDetail>(`/learning/history/${activityId}`),
  report: (courseId?: number) =>
    request<LearningReport>(`/learning/report${queryString({ courseId })}`),

  mistakes: (
    params: {
      courseId?: number
      pointId?: number
      errorType?: string
      status?: string
      limit?: number
      offset?: number
    } = {},
  ) => request<MistakePage>(`/learning/mistakes${queryString(params)}`),
  mistake: (mistakeId: number) => request<MistakeDetail>(`/learning/mistakes/${mistakeId}`),
  updateMistake: (mistakeId: number, status: 'open' | 'understood') =>
    request<MistakeRecord>(`/learning/mistakes/${mistakeId}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    }),
  practiceMistake: (mistakeId: number) =>
    request<{ courseId: number; knowledgePointId: number; sessionId: number; route: string }>(
      `/learning/mistakes/${mistakeId}/practice`,
      { method: 'POST' },
    ),
}

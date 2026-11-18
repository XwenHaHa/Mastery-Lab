/** 与后端 camelCase 响应一一对应的类型定义。 */

export interface HealthPayload {
  status: 'ok' | 'degraded'
  app: string
  version: string
  serverTime: string
  database: {
    ok: boolean
    engine: string
    path: string
  }
  paths: {
    dataDir: string
    uploadsDir: string
  }
  security: {
    secretScheme: string
  }
  runtime: {
    python: string
    platform: string
  }
}

export interface ModelConfig {
  id: number
  name: string
  baseUrl: string
  modelName: string
  apiKeyHint: string
  apiKeyScheme: string
  isDefault: boolean
  lastTestAt: string | null
  lastTestOk: boolean | null
  lastTestMessage: string
  createdAt: string
  updatedAt: string
}

export interface ModelConfigCreatePayload {
  name: string
  baseUrl: string
  modelName: string
  apiKey: string
  isDefault: boolean
}

export interface ModelConfigUpdatePayload {
  name?: string
  baseUrl?: string
  modelName?: string
  apiKey?: string
  isDefault?: boolean
}

export interface ModelTestPayload {
  id?: number
  baseUrl?: string
  modelName?: string
  apiKey?: string
  prompt?: string
}

export interface ModelTestResult {
  ok: boolean
  message: string
  latencyMs: number
  model: string
  reply: string
  httpStatus: number | null
}

/* ---------------- 课程与教材 ---------------- */

/** 四态学习状态；进度权重见 apps/api/app/services/learning.py */
export type LearningStatus = 'not_started' | 'in_progress' | 'review' | 'completed'

export interface StatusCounts {
  total: number
  notStarted: number
  inProgress: number
  review: number
  completed: number
}

export interface KnowledgePoint {
  completionSource?: 'legacy_manual' | 'verified' | null
  id: number
  chapterId: number
  title: string
  description: string
  contentLength: number
  sortOrder: number
  codeCount: number
  masteryLevel: number
  learningStatus: LearningStatus
  lastStudiedAt: string | null
}

export interface Chapter {
  id: number
  courseId: number
  title: string
  description: string
  sortOrder: number
  codeCount: number
  knowledgePoints: KnowledgePoint[]
  statusCounts: StatusCounts
  progress: number
}

export interface CourseSummary {
  id: number
  title: string
  description: string
  status: 'draft' | 'active'
  icon: string
  sourceType: 'markdown' | 'pdf'
  sourceName: string
  sourceBytes: number
  chapterCount: number
  knowledgePointCount: number
  codeCount: number
  progress: number
  statusCounts: StatusCounts
  lastStudiedAt: string | null
  createdAt: string
  updatedAt: string
}

export interface CourseDetail extends CourseSummary {
  warnings: string[]
  stats: Record<string, number>
  chapters: Chapter[]
}

/** 知识点列表项（不带正文） */
export interface KnowledgePointSummary {
  id: number
  chapterId: number
  chapterTitle: string
  title: string
  description: string
  sortOrder: number
  codeCount: number
  contentLength: number
  learningStatus: LearningStatus
  lastStudiedAt: string | null
}

/** 知识点详情（带正文与前后邻居） */
export interface KnowledgePointDetail {
  completionSource?: 'legacy_manual' | 'verified' | null
  id: number
  chapterId: number
  chapterTitle: string
  courseId: number
  courseTitle: string
  title: string
  description: string
  content: string
  sortOrder: number
  codeCount: number
  learningStatus: LearningStatus
  lastStudiedAt: string | null
  previousId: number | null
  nextId: number | null
}

export interface ChapterProgress {
  id: number
  title: string
  sortOrder: number
  knowledgePointCount: number
  progress: number
  statusCounts: StatusCounts
}

export interface RecentStudy {
  pointId: number
  title: string
  chapterId: number
  chapterTitle: string
  learningStatus: LearningStatus
  lastStudiedAt: string
}

export interface CourseProgress {
  courseId: number
  progress: number
  statusCounts: StatusCounts
  chapters: ChapterProgress[]
  recent: RecentStudy[]
}

export type CourseSort = 'updated' | 'created' | 'studied'

export interface ChapterPointOrder {
  chapterId: number
  ids: number[]
}

/* ---------------- AI 学习教室（P1.3） ---------------- */

export type ChatRole = 'user' | 'assistant'
export type ChatStatus = 'streaming' | 'completed' | 'interrupted' | 'failed'

export interface ClassroomCourseInfo {
  id: number
  title: string
  description: string
  icon: string
  progress: number
  chapterCount: number
  knowledgePointCount: number
  learnedCount: number
  statusCounts: StatusCounts
}

export interface ClassroomPointInfo {
  id: number
  chapterId: number
  chapterTitle: string
  title: string
  description: string
  contentLength: number
  sortOrder: number
  learningStatus: LearningStatus
  previousId: number | null
  nextId: number | null
}

export interface ClassroomModelInfo {
  id: number
  name: string
  modelName: string
}

export interface ChatMessage {
  id: number
  role: ChatRole
  content: string
  status: ChatStatus
  modelName: string
  errorMessage: string
  createdAt: string
}

export interface ClassroomContext {
  course: ClassroomCourseInfo
  point: ClassroomPointInfo
  model: ClassroomModelInfo | null
}

export interface ClassroomSession {
  id: number
  course: ClassroomCourseInfo
  point: ClassroomPointInfo
  model: ClassroomModelInfo | null
  messages: ChatMessage[]
  streaming: boolean
  createdAt: string
  updatedAt: string
  lastMessageAt: string | null
}

export interface SessionOpenPayload {
  courseId: number
  knowledgePointId: number
  modelConfigId?: number
}

export interface StopStreamResult {
  stopped: boolean
  message: string
}

export type TeachingStage = 'TEACH' | 'DEMO' | 'CHECK' | 'PAIR' | 'VERIFY' | 'NEXT'
export type TeachingAction = 'START' | 'CONTINUE' | 'ANSWER' | 'ASK' | 'EXPLAIN_AGAIN' | 'CHANGE_EXAMPLE' | 'GIVE_HINT' | 'DONT_UNDERSTAND' | 'TRY_MYSELF' | 'REGENERATE' | 'PAUSE' | 'RESUME' | 'NEXT' | 'RESTART'

export interface TeachingState {
  sessionId: number
  revision: number
  currentStage: TeachingStage
  stageStatus: 'PENDING' | 'ACTIVE' | 'WAITING_USER' | 'COMPLETED' | 'BLOCKED'
  paused: boolean
  goal: string
  nextStep: string
  allowedActions: TeachingAction[]
  completedStages: TeachingStage[]
  currentQuestion: string | null
  pairStep: number
  pairTotalSteps: number
  checkAttempts: number
  pairAttempts: number
  verifyAttempts: number
  hintCount: number
  verifyHintCount: number
  backtrackCount: number
  masteryState: string
  verificationResult: string | null
  legacyCompletion: boolean
  summary: string
  errorMessage: string
  completedAt: string | null
  lastActivityAt: string
}

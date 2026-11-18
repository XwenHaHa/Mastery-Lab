import type { LearningStatus, StatusCounts } from '@/api/types'

/** 四态学习状态在界面上的统一展示顺序与文案（与后端 services/learning.py 对应）。 */
export const STATUS_ORDER: LearningStatus[] = ['not_started', 'in_progress', 'review', 'completed']

/** StatusCounts 用的是 camelCase 字段名，这里做一次映射，避免各处写三元表达式 */
export const STATUS_COUNTER_KEYS: Record<LearningStatus, keyof StatusCounts> = {
  not_started: 'notStarted',
  in_progress: 'inProgress',
  review: 'review',
  completed: 'completed',
}

export function countOf(counts: StatusCounts | null | undefined, status: LearningStatus): number {
  if (!counts) return 0
  return counts[STATUS_COUNTER_KEYS[status]]
}

export const STATUS_LABELS: Record<LearningStatus, string> = {
  not_started: '未学习',
  in_progress: '学习中',
  review: '待复习',
  completed: '已完成',
}

/** 进度权重，仅用于界面说明，真正的计算在后端。 */
export const STATUS_WEIGHTS: Record<LearningStatus, number> = {
  not_started: 0,
  in_progress: 0.4,
  review: 0.7,
  completed: 1,
}

export function statusLabel(status: LearningStatus): string {
  return STATUS_LABELS[status] ?? '未学习'
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString('zh-CN')
}

/** 「刚刚 / 3 小时前 / 2 天前」，超过 30 天回退成日期。 */
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '还没有学习记录'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '还没有学习记录'
  const diff = Date.now() - date.getTime()
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  if (diff < 2_592_000_000) return `${Math.floor(diff / 86_400_000)} 天前`
  return formatDate(iso)
}

export function formatBytes(bytes: number): string {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

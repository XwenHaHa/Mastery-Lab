import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { courseLibraryApi } from '@/api'
import { ApiError } from '@/api/client'
import type { CourseSort, CourseSummary, StatusCounts } from '@/api/types'

/** 课程中心列表状态：搜索词与排序都放在 store 里，返回列表页时保持上次的选择。 */
export const useCourseStore = defineStore('courses', () => {
  const items = ref<CourseSummary[]>([])
  const loading = ref(false)
  const error = ref('')
  const keyword = ref('')
  const sort = ref<CourseSort>('updated')

  const count = computed(() => items.value.length)
  const totalPoints = computed(() => items.value.reduce((sum, item) => sum + item.knowledgePointCount, 0))
  const totalCompleted = computed(() => items.value.reduce((sum, item) => sum + item.statusCounts.completed, 0))
  const learning = computed(() => items.value.filter((item) => item.progress > 0 && item.progress < 100).length)
  const statusTotals = computed<StatusCounts>(() => {
    const totals: StatusCounts = { total: 0, notStarted: 0, inProgress: 0, review: 0, completed: 0 }
    for (const item of items.value) {
      totals.total += item.statusCounts.total
      totals.notStarted += item.statusCounts.notStarted
      totals.inProgress += item.statusCounts.inProgress
      totals.review += item.statusCounts.review
      totals.completed += item.statusCounts.completed
    }
    return totals
  })

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      // 空搜索词时后端按「无关键字」处理，这里直接传 undefined 更清晰
      items.value = await courseLibraryApi.list({
        q: keyword.value.trim() || undefined,
        sort: sort.value,
      })
    } catch (err) {
      error.value = err instanceof ApiError ? err.message : '加载课程列表失败'
    } finally {
      loading.value = false
    }
  }

  async function setKeyword(value: string): Promise<void> {
    keyword.value = value
    await load()
  }

  async function setSort(value: CourseSort): Promise<void> {
    sort.value = value
    await load()
  }

  async function remove(id: number): Promise<void> {
    await courseLibraryApi.remove(id)
    await load()
  }

  return {
    items,
    loading,
    error,
    keyword,
    sort,
    count,
    totalPoints,
    totalCompleted,
    learning,
    statusTotals,
    load,
    setKeyword,
    setSort,
    remove,
  }
})

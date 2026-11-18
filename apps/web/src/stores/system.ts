import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { systemApi } from '@/api'
import { ApiError } from '@/api/client'
import type { HealthPayload } from '@/api/types'

/** 后端可用性与运行环境状态，侧边栏状态点和概览/设置页共用。 */
export const useSystemStore = defineStore('system', () => {
  const health = ref<HealthPayload | null>(null)
  const loading = ref(false)
  const error = ref('')
  const checkedAt = ref<number | null>(null)

  const online = computed(() => health.value?.database.ok === true)
  const statusLabel = computed(() => {
    if (loading.value && !health.value) return '连接中'
    if (error.value) return '未连接'
    if (!health.value) return '未知'
    return health.value.database.ok ? '服务正常' : '数据库异常'
  })

  async function refresh(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      health.value = await systemApi.health()
      checkedAt.value = Date.now()
    } catch (err) {
      health.value = null
      error.value = err instanceof ApiError ? err.message : '健康检查失败'
    } finally {
      loading.value = false
    }
  }

  return { health, loading, error, checkedAt, online, statusLabel, refresh }
})

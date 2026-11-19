import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { systemApi } from '@/api'
import { ApiError } from '@/api/client'
import type { TeachingMeta, TeachingStageMeta } from '@/api/types'

/** 后端不可用时的兜底：与 P1.4 六阶段保持一致，保证旧会话仍能显示。 */
const FALLBACK_STAGES: TeachingStageMeta[] = [
  { key: 'TEACH', label: '讲解', goal: '', order: 1, family: 'lesson', optional: false },
  { key: 'DEMO', label: '演示', goal: '', order: 2, family: 'lesson', optional: false },
  { key: 'CHECK', label: '理解检查', goal: '', order: 3, family: 'check', optional: false },
  { key: 'PAIR', label: '共同实践', goal: '', order: 4, family: 'practice', optional: false },
  { key: 'VERIFY', label: '独立验证', goal: '', order: 5, family: 'verify', optional: false },
  { key: 'NEXT', label: '本节总结', goal: '', order: 6, family: 'next', optional: false },
]

/** 教学阶段与学科策略元数据：后端为准，前端只保留兜底。 */
export const useTeachingMetaStore = defineStore('teachingMeta', () => {
  const meta = ref<TeachingMeta | null>(null)
  const loading = ref(false)
  const error = ref('')
  let requested = false

  const labelMap = computed<Record<string, string>>(() => {
    const result: Record<string, string> = {}
    for (const stage of FALLBACK_STAGES) result[stage.key] = stage.label
    for (const stages of Object.values(meta.value?.pipelines ?? {})) {
      for (const stage of stages) result[stage.key] = stage.label
    }
    return result
  })

  async function ensureLoaded(): Promise<void> {
    if (requested) return
    requested = true
    loading.value = true
    try {
      meta.value = await systemApi.teachingMeta()
    } catch (err) {
      error.value = err instanceof ApiError ? err.message : '教学元数据加载失败'
    } finally {
      loading.value = false
    }
  }

  function stagesFor(version?: number): TeachingStageMeta[] {
    const pipeline = meta.value?.pipelines?.[String(version ?? meta.value?.defaultPipelineVersion ?? 1)]
    return pipeline?.length ? pipeline : FALLBACK_STAGES
  }

  function stageLabel(stage?: string | null): string {
    if (!stage) return ''
    return labelMap.value[stage] ?? stage
  }

  return { meta, loading, error, ensureLoaded, stagesFor, stageLabel }
})

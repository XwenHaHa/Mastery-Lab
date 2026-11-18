import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { modelApi } from '@/api'
import { ApiError } from '@/api/client'
import type {
  ModelConfig,
  ModelConfigCreatePayload,
  ModelConfigUpdatePayload,
  ModelTestPayload,
  ModelTestResult,
} from '@/api/types'

function toMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback
}

/** 模型配置列表状态。密钥永不出现在这里——后端只返回掩码。 */
export const useModelStore = defineStore('models', () => {
  const items = ref<ModelConfig[]>([])
  const loading = ref(false)
  const error = ref('')

  const count = computed(() => items.value.length)
  const defaultConfig = computed(() => items.value.find((item) => item.isDefault) ?? null)

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      items.value = await modelApi.list()
    } catch (err) {
      error.value = toMessage(err, '加载模型配置失败')
    } finally {
      loading.value = false
    }
  }

  async function create(payload: ModelConfigCreatePayload): Promise<ModelConfig> {
    const created = await modelApi.create(payload)
    await load()
    return created
  }

  async function update(id: number, payload: ModelConfigUpdatePayload): Promise<ModelConfig> {
    const updated = await modelApi.update(id, payload)
    await load()
    return updated
  }

  async function remove(id: number): Promise<void> {
    await modelApi.remove(id)
    await load()
  }

  async function test(payload: ModelTestPayload): Promise<ModelTestResult> {
    const result = await modelApi.test(payload)
    if (payload.id) await load()
    return result
  }

  return { items, loading, error, count, defaultConfig, load, create, update, remove, test }
})

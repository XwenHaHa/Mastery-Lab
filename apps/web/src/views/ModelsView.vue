<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { Connection, Delete, Edit, Plus } from '@element-plus/icons-vue'

import { ApiError } from '@/api/client'
import type { ModelConfig, ModelTestResult } from '@/api/types'
import { useModelStore } from '@/stores/models'

const store = useModelStore()

const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const testing = ref(false)
const rowTestingId = ref<number | null>(null)
const testResult = ref<ModelTestResult | null>(null)
const formRef = ref<FormInstance>()

const form = reactive({
  name: '',
  baseUrl: '',
  modelName: '',
  apiKey: '',
  isDefault: false,
})

const isEditing = computed(() => editingId.value !== null)

const rules = computed<FormRules>(() => ({
  name: [{ required: true, message: '给这条配置起个名字，例如「日常对话」', trigger: 'blur' }],
  baseUrl: [
    { required: true, message: '填写 OpenAI 兼容接口地址', trigger: 'blur' },
    {
      validator: (_rule, value: string, callback) => {
        if (!value) return callback()
        if (!/^https?:\/\/.+/i.test(value.trim())) {
          callback(new Error('地址需要以 http:// 或 https:// 开头'))
          return
        }
        callback()
      },
      trigger: 'blur',
    },
  ],
  modelName: [{ required: true, message: '填写模型名称，例如 deepseek-chat', trigger: 'blur' }],
  apiKey: [
    {
      validator: (_rule, value: string, callback) => {
        if (isEditing.value && !value) return callback()
        if (!value) {
          callback(new Error('填写 API Key，它会加密后保存在本机'))
          return
        }
        callback()
      },
      trigger: 'blur',
    },
  ],
}))

onMounted(() => void store.load())

function resetForm(): void {
  form.name = ''
  form.baseUrl = ''
  form.modelName = ''
  form.apiKey = ''
  form.isDefault = false
  testResult.value = null
  formRef.value?.clearValidate()
}

function openCreate(): void {
  editingId.value = null
  resetForm()
  form.isDefault = store.items.length === 0
  dialogVisible.value = true
}

function openEdit(row: ModelConfig): void {
  editingId.value = row.id
  resetForm()
  form.name = row.name
  form.baseUrl = row.baseUrl
  form.modelName = row.modelName
  form.isDefault = row.isDefault
  dialogVisible.value = true
}

async function submit(): Promise<void> {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  saving.value = true
  try {
    if (editingId.value === null) {
      await store.create({
        name: form.name.trim(),
        baseUrl: form.baseUrl.trim(),
        modelName: form.modelName.trim(),
        apiKey: form.apiKey.trim(),
        isDefault: form.isDefault,
      })
      ElMessage.success('配置已保存')
    } else {
      await store.update(editingId.value, {
        name: form.name.trim(),
        baseUrl: form.baseUrl.trim(),
        modelName: form.modelName.trim(),
        apiKey: form.apiKey.trim() || undefined,
        isDefault: form.isDefault,
      })
      ElMessage.success('配置已更新')
    }
    dialogVisible.value = false
  } catch (err) {
    ElMessage.error(err instanceof ApiError ? err.message : '保存失败，请查看后端日志')
  } finally {
    saving.value = false
  }
}

async function testCurrent(): Promise<void> {
  if (!formRef.value) return
  if (!form.baseUrl || !form.modelName) {
    ElMessage.warning('先填写接口地址和模型名称')
    return
  }
  if (!isEditing.value && !form.apiKey) {
    ElMessage.warning('先填写 API Key')
    return
  }

  testing.value = true
  testResult.value = null
  try {
    testResult.value = await store.test({
      id: editingId.value ?? undefined,
      baseUrl: form.baseUrl.trim(),
      modelName: form.modelName.trim(),
      apiKey: form.apiKey.trim() || undefined,
    })
  } catch (err) {
    testResult.value = {
      ok: false,
      message: err instanceof ApiError ? err.message : '测试失败',
      latencyMs: 0,
      model: '',
      reply: '',
      httpStatus: null,
    }
  } finally {
    testing.value = false
  }
}

async function testRow(row: ModelConfig): Promise<void> {
  rowTestingId.value = row.id
  try {
    const result = await store.test({ id: row.id })
    if (result.ok) {
      ElMessage.success(result.message)
    } else {
      ElMessage.warning(result.message)
    }
  } catch (err) {
    ElMessage.error(err instanceof ApiError ? err.message : '测试失败')
  } finally {
    rowTestingId.value = null
  }
}

async function setDefault(row: ModelConfig): Promise<void> {
  try {
    await store.update(row.id, { isDefault: true })
    ElMessage.success(`已将「${row.name}」设为默认`)
  } catch (err) {
    ElMessage.error(err instanceof ApiError ? err.message : '设置失败')
  }
}

async function removeRow(row: ModelConfig): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `删除后「${row.name}」的接口地址与加密密钥都会从本机数据库移除，且无法恢复。`,
      '删除模型配置',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消', confirmButtonClass: 'el-button--danger' },
    )
  } catch {
    return
  }
  try {
    await store.remove(row.id)
    ElMessage.success('配置已删除')
  } catch (err) {
    ElMessage.error(err instanceof ApiError ? err.message : '删除失败')
  }
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', { hour12: false })
}

function schemeLabel(scheme: string): string {
  if (scheme === 'windows-dpapi') return 'DPAPI'
  if (scheme === 'fernet-local-key') return '本地密钥'
  return scheme || '未知'
}
</script>

<template>
  <div class="ml-page">
    <div class="ml-page-head">
      <div>
        <h2 class="ml-page-title">模型配置</h2>
        <p class="ml-page-desc">
          接入任意 OpenAI 兼容 API。API Key 只写入本机数据库，由 Windows DPAPI 按当前用户加密，
          接口永远不会把明文返回给浏览器，也不会写进日志。
        </p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建配置</el-button>
    </div>

    <el-alert
      v-if="store.error"
      type="error"
      :closable="false"
      :title="store.error"
      show-icon
      class="page-alert"
    />

    <div v-if="!store.loading && store.items.length === 0" class="ml-empty">
      <h3>还没有模型配置</h3>
      <p>
        添加一条 OpenAI 兼容的接入信息（Base URL、模型名称、API Key）后，Mastery Lab 才能用大模型讲解释疑。
        先保存再点「测试连接」，确认配置可用。
      </p>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建配置</el-button>
    </div>

    <el-table v-else v-loading="store.loading" :data="store.items" row-key="id" class="config-table">
      <el-table-column label="名称" min-width="160">
        <template #default="{ row }">
          <div class="cell-name">
            <span>{{ row.name }}</span>
            <el-tag v-if="row.isDefault" size="small" effect="plain">默认</el-tag>
          </div>
        </template>
      </el-table-column>

      <el-table-column label="模型" min-width="140">
        <template #default="{ row }">
          <span class="ml-mono">{{ row.modelName }}</span>
        </template>
      </el-table-column>

      <el-table-column label="接口地址" min-width="240" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="ml-mono">{{ row.baseUrl }}</span>
        </template>
      </el-table-column>

      <el-table-column label="密钥" width="140">
        <template #default="{ row }">
          <div class="cell-key">
            <span class="ml-mono">{{ row.apiKeyHint || '****' }}</span>
            <el-tag size="small" type="info" effect="plain">{{ schemeLabel(row.apiKeyScheme) }}</el-tag>
          </div>
        </template>
      </el-table-column>

      <el-table-column label="最近测试" width="190">
        <template #default="{ row }">
          <div v-if="row.lastTestAt" class="cell-test">
            <el-tag size="small" :type="row.lastTestOk ? 'success' : 'danger'" effect="plain">
              {{ row.lastTestOk ? '通过' : '失败' }}
            </el-tag>
            <span class="test-time" :title="row.lastTestMessage">{{ formatTime(row.lastTestAt) }}</span>
          </div>
          <span v-else class="ml-muted">未测试</span>
        </template>
      </el-table-column>

      <el-table-column label="操作" width="220" align="right">
        <template #default="{ row }">
          <el-button
            link
            type="primary"
            :icon="Connection"
            :loading="rowTestingId === row.id"
            @click="testRow(row as ModelConfig)"
          >
            测试
          </el-button>
          <el-button link :icon="Edit" @click="openEdit(row as ModelConfig)">编辑</el-button>
          <el-button link :disabled="row.isDefault" @click="setDefault(row as ModelConfig)">设为默认</el-button>
          <el-button link type="danger" :icon="Delete" @click="removeRow(row as ModelConfig)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <p class="table-note">
      提示：Base URL 一般形如 <code>https://api.deepseek.com/v1</code>。若填写到 <code>/chat/completions</code>
      也能识别。
    </p>

    <el-dialog
      v-model="dialogVisible"
      :title="isEditing ? '编辑模型配置' : '新建模型配置'"
      width="560px"
      :close-on-click-modal="false"
      destroy-on-close
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
        <el-form-item label="配置名称" prop="name">
          <el-input v-model="form.name" placeholder="例如：日常对话 / 代码讲解" maxlength="80" />
        </el-form-item>

        <el-form-item label="API Base URL" prop="baseUrl">
          <el-input v-model="form.baseUrl" placeholder="https://api.deepseek.com/v1" />
        </el-form-item>

        <el-form-item label="模型名称" prop="modelName">
          <el-input v-model="form.modelName" placeholder="deepseek-chat / gpt-4o-mini" />
        </el-form-item>

        <el-form-item :label="isEditing ? 'API Key（原地址可留空，更换地址须重新填写）' : 'API Key'" prop="apiKey">
          <el-input v-model="form.apiKey" type="password" show-password autocomplete="new-password" placeholder="sk-..." />
        </el-form-item>

        <el-form-item>
          <el-checkbox v-model="form.isDefault">设为默认模型</el-checkbox>
        </el-form-item>
      </el-form>

      <el-alert
        v-if="testResult"
        :type="testResult.ok ? 'success' : 'error'"
        :closable="false"
        show-icon
        :title="testResult.message"
        class="test-result"
      >
        <p v-if="testResult.reply" class="test-reply">模型回复：{{ testResult.reply }}</p>
      </el-alert>

      <template #footer>
        <div class="dialog-footer">
          <el-button :loading="testing" :icon="Connection" @click="testCurrent">测试连接</el-button>
          <div>
            <el-button @click="dialogVisible = false">取消</el-button>
            <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-alert {
  margin-bottom: 16px;
}

.config-table {
  border: 1px solid var(--ml-border);
  border-radius: var(--ml-radius-lg);
}

.cell-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
}

.cell-key {
  display: flex;
  align-items: center;
  gap: 6px;
}

.cell-test {
  display: flex;
  align-items: center;
  gap: 8px;
}

.config-table :deep(.el-table__inner-wrapper) {
  border-radius: var(--ml-radius-lg);
  overflow: hidden;
}

.test-time {
  font-family: var(--ml-font-mono);
  font-size: 11.5px;
  color: var(--ml-text-3);
}

.table-note {
  margin-top: 12px;
  font-size: 12.5px;
  color: var(--ml-text-3);
}

.table-note code {
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--ml-surface-2);
  border: 1px solid var(--ml-border);
}

.dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.test-result {
  margin-top: 4px;
}

.test-reply {
  margin-top: 4px;
  font-size: 12.5px;
  word-break: break-all;
}
</style>

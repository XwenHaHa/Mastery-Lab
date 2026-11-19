<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'

import type { ActivityContentBlock, CurrentActivity } from '@/api/types'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{
  activity: CurrentActivity
  modelValue: string
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  submit: [value: string]
}>()

const TYPE_LABELS: Record<string, string> = {
  TEXT_EXPLANATION: '文字讲解',
  IMAGE_ANALYSIS: '图片分析',
  FORMULA_DERIVATION: '公式推导',
  DIAGRAM_WALKTHROUGH: '图表讲解',
  CODE_DEMO: '代码演示',
  MULTIPLE_CHOICE: '选择',
  FILL_IN_BLANK: '填空',
  SHORT_ANSWER: '简答',
  STEP_ORDERING: '步骤排序',
  CALCULATION: '计算',
  CONVERSATION: '对话练习',
  PRACTICAL_TASK: '实操任务',
  AUDIO_EXERCISE: '听说练习',
  VIDEO_ANALYSIS: '视频分析',
}

const definition = computed(() => props.activity.definition)
const activityType = computed(() => props.activity.activityType || definition.value?.type || 'SHORT_ANSWER')
const inputKind = computed(() => definition.value?.interaction?.inputKind ?? 'SHORT_TEXT')
const payload = computed<Record<string, unknown>>(
  () => (definition.value?.interaction?.payload ?? {}) as Record<string, unknown>,
)
const prompt = computed(() => definition.value?.interaction?.prompt || '请完成当前任务。')
const typeLabel = computed(() => TYPE_LABELS[activityType.value] ?? activityType.value)
const showContent = computed(() =>
  ['CODE_DEMO', 'TEXT_EXPLANATION', 'DIAGRAM_WALKTHROUGH', 'FORMULA_DERIVATION'].includes(activityType.value),
)

const shortText = ref('')
const selected = ref<string[]>([])
const blankValues = reactive<Record<string, string>>({})
const calcValue = ref('')
const prediction = ref('')

function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function blockToMarkdown(block: ActivityContentBlock): string {
  switch (block.kind) {
    case 'markdown':
      return asString(block.text)
    case 'code':
      return `\`\`\`${asString(block.language)}\n${asString(block.code)}\n\`\`\``
    case 'latex': {
      const expression = asString(block.expression)
      return block.display ? `$$\n${expression}\n$$` : `$${expression}$`
    }
    case 'callout': {
      const tone = block.tone === 'warning' ? '注意' : block.tone === 'tip' ? '提示' : '说明'
      return `> **${tone}**：${asString(block.text)}`
    }
    case 'steps':
      return (block.items ?? [])
        .map((item, index) => `${index + 1}. **${asString(item.title)}** ${asString(item.body)}`)
        .join('\n')
    case 'table': {
      const headers = block.headers ?? []
      if (!headers.length) return ''
      const rows = block.rows ?? []
      return [
        `| ${headers.join(' | ')} |`,
        `| ${headers.map(() => '---').join(' | ')} |`,
        ...rows.map(row => `| ${row.join(' | ')} |`),
      ].join('\n')
    }
    case 'diagram':
      return `> 图表（${asString(block.format)}）：${asString(block.caption)}`
    case 'image':
      return `![${asString(block.alt) || asString(block.caption)}](material://${Number(block.materialId)})`
    case 'audio':
    case 'video':
      return ''
    default:
      return ''
  }
}

function materialUrl(materialId: unknown): string {
  return `/api/v1/materials/${Number(materialId)}/content`
}

const mediaBlocks = computed(() =>
  (definition.value?.content ?? []).filter(
    block => block.kind === 'audio' || block.kind === 'video',
  ),
)

const renderedContent = computed(() =>
  (definition.value?.content ?? []).map(blockToMarkdown).filter(Boolean).join('\n\n'),
)

interface ChoiceOption {
  id: string
  label: string
}

const options = computed<ChoiceOption[]>(() => {
  const raw = payload.value.options
  if (!Array.isArray(raw)) return []
  return raw
    .filter(item => item && typeof item === 'object')
    .map((item, index) => {
      const record = item as Record<string, unknown>
      return {
        id: asString(record.id, String(index + 1)),
        label: asString(record.label, asString(record.text, `选项 ${index + 1}`)),
      }
    })
})

const multiple = computed(() => Boolean(payload.value.multiple))
const singleSelected = computed({
  get: () => selected.value[0] ?? '',
  set: (value: string) => {
    selected.value = value ? [value] : []
  },
})

interface BlankItem {
  id: string
  label: string
}

const blankItems = computed<BlankItem[]>(() => {
  const raw = payload.value.blanks
  if (!Array.isArray(raw) || !raw.length) return [{ id: 'blank-1', label: '你的答案' }]
  return raw.map((item, index) => {
    const record = item && typeof item === 'object' ? (item as Record<string, unknown>) : {}
    return {
      id: asString(record.id, `blank-${index + 1}`),
      label: asString(record.label, `第 ${index + 1} 空`),
    }
  })
})

const calcUnit = computed(() => asString(payload.value.unit))

const answerText = computed(() => {
  if (activityType.value === 'MULTIPLE_CHOICE') {
    const labels = options.value.filter(option => selected.value.includes(option.id)).map(option => option.label)
    return labels.join('、')
  }
  if (activityType.value === 'FILL_IN_BLANK') {
    return blankItems.value
      .map(blank => `${blank.label}：${blankValues[blank.id] ?? ''}`)
      .filter(item => !item.endsWith('：'))
      .join('；')
  }
  if (activityType.value === 'CALCULATION') {
    return calcValue.value.trim() ? `结果：${calcValue.value.trim()}${calcUnit.value}` : ''
  }
  if (activityType.value === 'CODE_DEMO' && inputKind.value === 'PREDICT_OUTPUT') {
    return prediction.value
  }
  return shortText.value
})

const canSubmit = computed(() => answerText.value.trim().length > 0 && !props.disabled)

let restoring = false

function restore(value: string) {
  restoring = true
  const text = value ?? ''
  shortText.value = text
  selected.value = []
  calcValue.value = ''
  prediction.value = ''
  for (const key of Object.keys(blankValues)) delete blankValues[key]

  if (text && activityType.value === 'MULTIPLE_CHOICE') {
    selected.value = options.value
      .filter(option => text.includes(option.label) || text.includes(`[${option.id}]`))
      .map(option => option.id)
  } else if (text && activityType.value === 'FILL_IN_BLANK') {
    for (const blank of blankItems.value) {
      const match = text.match(new RegExp(`${blank.label}[：:]\\s*([^；;\\n]+)`))
      if (match) blankValues[blank.id] = match[1].trim()
    }
  } else if (text && activityType.value === 'CALCULATION') {
    calcValue.value = text.replace(/^结果[：:]\s*/, '').replace(calcUnit.value, '').trim()
  } else if (text && activityType.value === 'CODE_DEMO' && inputKind.value === 'PREDICT_OUTPUT') {
    prediction.value = text
  }
  restoring = false
}

watch(
  () => props.modelValue,
  value => {
    if (!restoring && value !== answerText.value) restore(value)
  },
  { immediate: true },
)

watch(answerText, value => {
  if (!restoring) emit('update:modelValue', value)
})

function submit() {
  if (!canSubmit.value) return
  emit('update:modelValue', answerText.value)
  emit('submit', answerText.value)
}
</script>

<template>
  <section class="activity-renderer" aria-label="当前教学活动">
    <header class="activity-head">
      <span class="activity-type">{{ typeLabel }}</span>
      <span v-if="activity.attemptNo > 1" class="activity-attempt">第 {{ activity.attemptNo }} 次尝试</span>
    </header>

    <p v-if="definition?.title" class="activity-title">{{ definition.title }}</p>
    <p v-if="definition?.objective" class="activity-objective">{{ definition.objective }}</p>

    <div v-if="showContent && renderedContent" class="activity-content" v-html="renderMarkdown(renderedContent)" />

    <div v-if="mediaBlocks.length" class="activity-media">
      <template v-for="(block, index) in mediaBlocks" :key="`${block.kind}-${index}`">
        <audio v-if="block.kind === 'audio'" controls :src="materialUrl(block.materialId)" />
        <video v-else controls :src="materialUrl(block.materialId)" />
        <p v-if="block.caption" class="media-caption">{{ block.caption }}</p>
      </template>
    </div>

    <p class="activity-prompt">{{ prompt }}</p>

    <div v-if="activityType === 'MULTIPLE_CHOICE'" class="choice-list">
      <el-radio-group v-if="!multiple" v-model="singleSelected" :disabled="disabled">
        <el-radio v-for="option in options" :key="option.id" :value="option.id">{{ option.label }}</el-radio>
      </el-radio-group>
      <el-checkbox-group v-else v-model="selected" :disabled="disabled">
        <el-checkbox v-for="option in options" :key="option.id" :value="option.id">{{ option.label }}</el-checkbox>
      </el-checkbox-group>
      <p v-if="!options.length" class="activity-empty">当前活动没有提供选项，请改用文字回答。</p>
    </div>

    <div v-else-if="activityType === 'FILL_IN_BLANK'" class="blank-list">
      <label v-for="blank in blankItems" :key="blank.id" class="blank-row">
        <span class="blank-label">{{ blank.label }}</span>
        <el-input v-model="blankValues[blank.id]" :disabled="disabled" placeholder="填写答案" />
      </label>
    </div>

    <div v-else-if="activityType === 'CALCULATION'" class="calc-row">
      <el-input v-model="calcValue" :disabled="disabled" placeholder="填写计算结果或表达式" />
      <span v-if="calcUnit" class="calc-unit">{{ calcUnit }}</span>
    </div>

    <div v-else-if="activityType === 'CODE_DEMO' && inputKind === 'PREDICT_OUTPUT'" class="short-row">
      <el-input v-model="prediction" :disabled="disabled" placeholder="先不要运行，猜一猜输出是什么" />
    </div>

    <div v-else class="short-row">
      <el-input
        v-model="shortText"
        type="textarea"
        :rows="3"
        resize="none"
        :disabled="disabled"
        :maxlength="8000"
        placeholder="写下你的解释或回答……"
      />
    </div>

    <div class="activity-actions">
      <span class="activity-tip">提交后会由老师评价；不确定也可以先提问。</span>
      <el-button type="primary" size="small" :disabled="!canSubmit" @click="submit">提交回答</el-button>
    </div>
  </section>
</template>

<style scoped>
.activity-renderer {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px 8px;
}

.activity-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.activity-type {
  padding: 2px 8px;
  border: 1px solid var(--ml-border-strong);
  border-radius: 999px;
  color: var(--ml-text-3);
  font-size: 11px;
  letter-spacing: 0.04em;
}

.activity-attempt {
  color: var(--ml-text-4, var(--ml-text-3));
  font-size: 11px;
}

.activity-title {
  margin: 0;
  color: var(--ml-text);
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.5;
}

.activity-objective {
  margin: 0;
  color: var(--ml-text-3);
  font-size: 12px;
  line-height: 1.6;
}

.activity-content {
  max-height: 260px;
  overflow: auto;
  padding: 8px 10px;
  border: 1px solid var(--ml-border);
  border-radius: var(--ml-radius-md);
  background: var(--ml-bg-soft);
  color: var(--ml-text-2);
  font-size: 12.5px;
  line-height: 1.65;
}

.activity-content :deep(pre) {
  margin: 6px 0;
  padding: 8px;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.25);
  overflow: auto;
}

.activity-prompt {
  margin: 0;
  color: var(--ml-text);
  font-size: 13px;
  line-height: 1.6;
}

.activity-media {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.activity-media audio,
.activity-media video {
  width: 100%;
  max-height: 320px;
  border-radius: 8px;
  background: #000;
}

.media-caption {
  margin: 0;
  color: var(--ml-text-3);
  font-size: 11px;
}

.choice-list :deep(.el-radio-group),
.choice-list :deep(.el-checkbox-group) {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}

.blank-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.blank-row {
  display: grid;
  grid-template-columns: 72px 1fr;
  align-items: center;
  gap: 8px;
}

.blank-label {
  color: var(--ml-text-3);
  font-size: 12px;
}

.calc-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.calc-unit {
  color: var(--ml-text-3);
  font-size: 12px;
}

.activity-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.activity-tip {
  color: var(--ml-text-3);
  font-size: 11px;
}

.activity-empty {
  margin: 0;
  color: var(--ml-text-3);
  font-size: 12px;
}
</style>

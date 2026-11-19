<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'

import type { ActivityContentBlock, ActivityMaterialRef, CurrentActivity } from '@/api/types'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{
  activity: CurrentActivity
  modelValue: string
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  submit: [value: string]
  regenerate: []
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
const activityType = computed(
  () => props.activity.activityType || definition.value?.type || 'SHORT_ANSWER',
)
const inputKind = computed(() => definition.value?.interaction?.inputKind ?? 'SHORT_TEXT')
const payload = computed<Record<string, unknown>>(
  () => (definition.value?.interaction?.payload ?? {}) as Record<string, unknown>,
)
const prompt = computed(() => definition.value?.interaction?.prompt || '请完成当前任务。')
const typeLabel = computed(() => TYPE_LABELS[activityType.value] ?? activityType.value)
const unknownActivity = computed(() => !TYPE_LABELS[activityType.value])
const evaluationMode = computed(() => definition.value?.evaluation?.mode ?? 'RUBRIC_AI')

const shortText = ref('')
const selected = ref<string[]>([])
const blankValues = reactive<Record<string, string>>({})
const calcValue = ref('')
const prediction = ref('')
const stepValues = ref<string[]>([])
const orderIds = ref<string[]>([])
const hotspotIds = ref<string[]>([])
const videoTimestamp = ref('')
const videoText = ref('')
const dictation = ref('')
const brokenMaterials = ref<Set<number>>(new Set())
const restoring = ref(false)

function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function recordOf(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function arrayOf(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

/* ---------------- 内容与素材 ---------------- */

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
      return arrayOf(block.items)
        .map((item, index) => {
          const step = recordOf(item)
          return `${index + 1}. **${asString(step.title)}** ${asString(step.body)}`
        })
        .join('\n')
    case 'table': {
      const headers = (block.headers ?? []) as string[]
      if (!headers.length) return ''
      const rows = (block.rows ?? []) as string[][]
      return [
        `| ${headers.join(' | ')} |`,
        `| ${headers.map(() => '---').join(' | ')} |`,
        ...rows.map((row) => `| ${row.join(' | ')} |`),
      ].join('\n')
    }
    case 'diagram':
      return `> 图表（${asString(block.format)}）：${asString(block.caption)}`
    default:
      return ''
  }
}

const textContent = computed(() =>
  (definition.value?.content ?? [])
    .filter((block) => !['image', 'audio', 'video'].includes(block.kind))
    .map(blockToMarkdown)
    .filter(Boolean)
    .join('\n\n'),
)
const renderedContent = computed(() => renderMarkdown(textContent.value))

interface MediaBlock {
  kind: 'image' | 'audio' | 'video'
  materialId: number
  alt: string
  caption: string
}

const mediaBlocks = computed<MediaBlock[]>(() =>
  (definition.value?.content ?? [])
    .filter((block) => ['image', 'audio', 'video'].includes(block.kind))
    .map((block) => ({
      kind: block.kind as MediaBlock['kind'],
      materialId: Number(block.materialId),
      alt: asString(block.alt, asString(block.caption, '素材')),
      caption: asString(block.caption),
    })),
)
const imageBlocks = computed(() => mediaBlocks.value.filter((block) => block.kind === 'image'))
const audioBlocks = computed(() => mediaBlocks.value.filter((block) => block.kind === 'audio'))
const videoBlocks = computed(() => mediaBlocks.value.filter((block) => block.kind === 'video'))

const materialMap = computed<Record<number, ActivityMaterialRef>>(() => {
  const result: Record<number, ActivityMaterialRef> = {}
  for (const item of props.activity.materials ?? []) result[item.materialId] = item
  return result
})

function materialUrl(materialId: number): string {
  const known = materialMap.value[materialId]
  return known?.exists && known.url ? known.url : `/api/v1/materials/${materialId}/content`
}

function materialMissing(materialId: number): boolean {
  if (brokenMaterials.value.has(materialId)) return true
  const known = materialMap.value[materialId]
  return known ? known.exists === false : false
}

function markBroken(materialId: number): void {
  const next = new Set(brokenMaterials.value)
  next.add(materialId)
  brokenMaterials.value = next
}

/* ---------------- 交互数据 ---------------- */

interface ChoiceOption {
  id: string
  label: string
}

const options = computed<ChoiceOption[]>(() =>
  arrayOf(payload.value.options)
    .filter((item) => item && typeof item === 'object')
    .map((item, index) => {
      const record = recordOf(item)
      return {
        id: asString(record.id, String(index + 1)),
        label: asString(record.label, asString(record.text, `选项 ${index + 1}`)),
      }
    }),
)
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
  const raw = arrayOf(payload.value.blanks)
  if (!raw.length) return [{ id: 'blank-1', label: '你的答案' }]
  return raw.map((item, index) => {
    const record = recordOf(item)
    return {
      id: asString(record.id, `blank-${index + 1}`),
      label: asString(record.label, `第 ${index + 1} 空`),
    }
  })
})

interface OrderedItem {
  id: string
  label: string
}

const payloadItems = computed<OrderedItem[]>(() =>
  arrayOf(payload.value.items).map((item, index) => {
    const record = recordOf(item)
    return {
      id: asString(record.id, String(index + 1)),
      label: asString(record.label, asString(record.text, `步骤 ${index + 1}`)),
    }
  }),
)

const hotspotItems = computed<OrderedItem[]>(() =>
  arrayOf(payload.value.hotspots).map((item, index) => {
    const record = recordOf(item)
    return {
      id: asString(record.id, String(index + 1)),
      label: asString(record.label, asString(record.name, `热点 ${index + 1}`)),
    }
  }),
)

function itemLabel(items: OrderedItem[], id: string): string {
  return items.find((item) => item.id === id)?.label ?? id
}

function moveItem(list: string[], index: number, delta: number): void {
  const target = index + delta
  if (target < 0 || target >= list.length) return
  const next = [...list]
  ;[next[index], next[target]] = [next[target], next[index]]
  list.splice(0, list.length, ...next)
}

function moveOrder(index: number, delta: number): void {
  moveItem(orderIds.value, index, delta)
}

function moveHotspot(index: number, delta: number): void {
  moveItem(hotspotIds.value, index, delta)
}

function resetOrder(): void {
  orderIds.value = payloadItems.value.map((item) => item.id)
}

function resetHotspots(): void {
  hotspotIds.value = hotspotItems.value.map((item) => item.id)
}

interface StepItem {
  id: string
  title: string
  body: string
}

const stepItems = computed<StepItem[]>(() =>
  arrayOf(payload.value.steps).map((item, index) => {
    const record = recordOf(item)
    return {
      id: asString(record.id, String(index + 1)),
      title: asString(record.title, asString(record.label, `第 ${index + 1} 步`)),
      body: asString(record.body, ''),
    }
  }),
)

const checklistItems = computed(() =>
  arrayOf(payload.value.checklist).map((item, index) => {
    const record = recordOf(item)
    return asString(record.label, asString(item, `检查项 ${index + 1}`))
  }),
)

const conversationTurns = computed(() =>
  arrayOf(payload.value.turns).map((item) => {
    const record = recordOf(item)
    return {
      role: asString(record.role, 'other'),
      text: asString(record.text, asString(record.content, '')),
    }
  }),
)

/* ---------------- 序列化 ---------------- */

const confirmOnly = computed(
  () =>
    (activityType.value === 'TEXT_EXPLANATION' && inputKind.value === 'NONE') ||
    (activityType.value === 'CODE_DEMO' && inputKind.value === 'NONE') ||
    (activityType.value === 'DIAGRAM_WALKTHROUGH' && inputKind.value === 'NONE'),
)

const audioUnsupported = computed(
  () => activityType.value === 'AUDIO_EXERCISE' && inputKind.value === 'AUDIO_RESPONSE',
)

const unsupported = computed(() => audioUnsupported.value)

const choiceAnswer = computed(() =>
  selected.value.map((id) => `[${id}]`).join('、'),
)
const orderAnswer = computed(() => orderIds.value.map((id) => `[${id}]`).join('、'))
const hotspotAnswer = computed(() => hotspotIds.value.map((id) => `[${id}]`).join('、'))
const stepAnswer = computed(() =>
  stepValues.value
    .map((value, index) => `${index + 1}. ${value.trim()}`)
    .filter((item) => !item.endsWith('. '))
    .join('\n'),
)
const videoAnswer = computed(() => {
  const time = videoTimestamp.value.trim()
  const text = videoText.value.trim()
  if (!time && !text) return ''
  return `时间点：${time || '未填写'}；分析：${text}`
})

const answerText = computed(() => {
  if (unsupported.value) return ''
  if (confirmOnly.value) return '已阅读当前内容'
  if (activityType.value === 'MULTIPLE_CHOICE') return choiceAnswer.value
  if (activityType.value === 'FILL_IN_BLANK') {
    return blankItems.value
      .map((blank) => `${blank.label}：${blankValues[blank.id] ?? ''}`)
      .filter((item) => !item.endsWith('：'))
      .join('；')
  }
  if (activityType.value === 'CALCULATION') {
    const unit = asString(payload.value.unit)
    return calcValue.value.trim() ? `结果：${calcValue.value.trim()}${unit}` : ''
  }
  if (activityType.value === 'STEP_ORDERING') return orderAnswer.value
  if (activityType.value === 'DIAGRAM_WALKTHROUGH') {
    return inputKind.value === 'HOTSPOT_ORDER' ? hotspotAnswer.value : ''
  }
  if (activityType.value === 'FORMULA_DERIVATION') {
    return inputKind.value === 'STEPS' && stepItems.value.length ? stepAnswer.value : shortText.value
  }
  if (activityType.value === 'CODE_DEMO' && inputKind.value === 'PREDICT_OUTPUT') {
    return prediction.value
  }
  if (activityType.value === 'AUDIO_EXERCISE') {
    if (inputKind.value === 'CHOICE') return choiceAnswer.value
    if (inputKind.value === 'DICTATION') return dictation.value
    return ''
  }
  if (activityType.value === 'VIDEO_ANALYSIS') return videoAnswer.value
  return shortText.value
})

const canSubmit = computed(() => answerText.value.trim().length > 0 && !props.disabled && !unsupported.value)

const calcUnit = computed(() => asString(payload.value.unit))
const resultFeedback = computed(() => {
  const result = props.activity.result as Record<string, unknown> | null
  return asString(result?.feedback, props.activity.aiFeedback)
})

/* ---------------- 恢复 ---------------- */

function parseChoiceIds(text: string, items: ChoiceOption[]): string[] {
  const bracketed = [...text.matchAll(/\[([^\]]+)\]/g)].flatMap((match) =>
    match[1].split(/[,，、;；\s]+/).filter(Boolean),
  )
  const tokens = bracketed.length
    ? bracketed
    : text.split(/[,，、;；\s]+/).filter(Boolean)
  return tokens
    .map((token) => items.find((item) => token === item.id || token === item.label)?.id)
    .filter((id): id is string => Boolean(id))
}

function parseOrderedIds(text: string, items: OrderedItem[]): string[] {
  const bracketed = [...text.matchAll(/\[([^\]]+)\]/g)].flatMap((match) =>
    match[1].split(/[,，、;；\s]+/).filter(Boolean),
  )
  const tokens = bracketed.length
    ? bracketed
    : text
        .split('\n')
        .map((line) => line.replace(/^\s*\d+[.)、]\s*/, '').trim())
        .filter(Boolean)
  return tokens
    .map((token) => items.find((item) => token === item.id || token === item.label)?.id)
    .filter((id): id is string => Boolean(id))
}

function restore(value: string): void {
  restoring.value = true
  const text = value ?? ''
  shortText.value = text
  selected.value = []
  calcValue.value = ''
  prediction.value = ''
  dictation.value = ''
  videoTimestamp.value = ''
  videoText.value = ''
  for (const key of Object.keys(blankValues)) delete blankValues[key]

  if (text && activityType.value === 'MULTIPLE_CHOICE') {
    selected.value = parseChoiceIds(text, options.value)
  } else if (text && activityType.value === 'FILL_IN_BLANK') {
    for (const blank of blankItems.value) {
      const match = text.match(new RegExp(`${blank.label}[：:]\\s*([^；;\\n|]+)`))
      if (match) blankValues[blank.id] = match[1].trim()
    }
    if (!Object.keys(blankValues).length && blankItems.value.length === 1) {
      blankValues[blankItems.value[0].id] = text
    }
  } else if (text && activityType.value === 'CALCULATION') {
    calcValue.value = text.replace(/^结果[：:]\s*/, '').replace(calcUnit.value, '').trim()
  } else if (text && activityType.value === 'CODE_DEMO' && inputKind.value === 'PREDICT_OUTPUT') {
    prediction.value = text
  } else if (text && activityType.value === 'STEP_ORDERING') {
    const parsed = parseOrderedIds(text, payloadItems.value)
    const rest = payloadItems.value.map((item) => item.id).filter((id) => !parsed.includes(id))
    orderIds.value = [...parsed, ...rest]
  } else if (text && activityType.value === 'DIAGRAM_WALKTHROUGH' && inputKind.value === 'HOTSPOT_ORDER') {
    const parsed = parseOrderedIds(text, hotspotItems.value)
    const rest = hotspotItems.value.map((item) => item.id).filter((id) => !parsed.includes(id))
    hotspotIds.value = [...parsed, ...rest]
  } else if (text && activityType.value === 'FORMULA_DERIVATION' && stepItems.value.length) {
    const lines = text.split('\n').map((line) => line.replace(/^\s*\d+[.)、]\s*/, '').trim())
    stepValues.value = stepItems.value.map((_item, index) => lines[index] ?? '')
  } else if (text && activityType.value === 'AUDIO_EXERCISE' && inputKind.value === 'CHOICE') {
    selected.value = parseChoiceIds(text, options.value)
  } else if (text && activityType.value === 'AUDIO_EXERCISE' && inputKind.value === 'DICTATION') {
    dictation.value = text
  } else if (text && activityType.value === 'VIDEO_ANALYSIS') {
    const time = text.match(/时间点[：:]\s*([^；;\\n]*)/)
    const analysis = text.match(/分析[：:]\s*([\s\S]*)/)
    videoTimestamp.value = time ? time[1].trim() : ''
    videoText.value = analysis ? analysis[1].trim() : text
  }
  restoring.value = false
}

watch(
  () => props.modelValue,
  (value) => {
    if (!restoring.value && value !== answerText.value) restore(value)
  },
  { immediate: true },
)

watch(answerText, (value) => {
  if (!restoring.value) emit('update:modelValue', value)
})

watch(
  () => props.activity.id,
  () => {
    resetOrder()
    resetHotspots()
    stepValues.value = stepItems.value.map(() => '')
    brokenMaterials.value = new Set()
    restore(props.modelValue)
  },
  { immediate: true },
)

function submit(): void {
  if (!canSubmit.value) return
  emit('update:modelValue', answerText.value)
  emit('submit', answerText.value)
}

function regenerate(): void {
  emit('regenerate')
}
</script>

<template>
  <section class="activity-renderer" aria-label="当前教学活动">
    <header class="activity-head">
      <span class="activity-type">{{ typeLabel }}</span>
      <span v-if="activity.attemptNo > 1" class="activity-attempt">第 {{ activity.attemptNo }} 次尝试</span>
      <span v-if="definition?.meta?.degraded" class="activity-degraded">已安全降级为文字问答</span>
    </header>

    <p v-if="definition?.title" class="activity-title">{{ definition.title }}</p>
    <p v-if="definition?.objective" class="activity-objective">{{ definition.objective }}</p>

    <div v-if="renderedContent" class="activity-content" v-html="renderedContent" />

    <div v-if="imageBlocks.length" class="activity-images">
      <figure v-for="(block, index) in imageBlocks" :key="`image-${index}`" class="activity-image">
        <div v-if="materialMissing(block.materialId)" class="media-missing">素材已删除或不属于当前课程</div>
        <img
          v-else
          :src="materialUrl(block.materialId)"
          :alt="block.alt"
          loading="lazy"
          @error="markBroken(block.materialId)"
        />
        <figcaption v-if="block.caption || block.alt">{{ block.caption || block.alt }}</figcaption>
      </figure>
    </div>

    <div v-if="audioBlocks.length" class="activity-media">
      <template v-for="(block, index) in audioBlocks" :key="`audio-${index}`">
        <div v-if="materialMissing(block.materialId)" class="media-missing">音频素材已删除或不属于当前课程</div>
        <audio v-else controls :src="materialUrl(block.materialId)" @error="markBroken(block.materialId)" />
        <p v-if="block.caption" class="media-caption">{{ block.caption }}</p>
      </template>
    </div>

    <div v-if="videoBlocks.length" class="activity-media">
      <template v-for="(block, index) in videoBlocks" :key="`video-${index}`">
        <div v-if="materialMissing(block.materialId)" class="media-missing">视频素材已删除或不属于当前课程</div>
        <video v-else controls :src="materialUrl(block.materialId)" @error="markBroken(block.materialId)" />
        <p v-if="block.caption" class="media-caption">{{ block.caption }}</p>
      </template>
    </div>

    <p class="activity-prompt">{{ prompt }}</p>

    <div v-if="resultFeedback" class="activity-result">{{ resultFeedback }}</div>

    <div v-if="unknownActivity" class="activity-unsupported">
      <p>未知活动类型「{{ activityType }}」，已安全降级为文字回答；不会丢弃当前教学进度。</p>
    </div>

    <div v-if="audioUnsupported" class="activity-unsupported">
      <p>当前浏览器录音与语音转写尚未接入，不能假装完成语音作答。</p>
      <el-button size="small" @click="regenerate">请老师换一个活动</el-button>
    </div>

    <div v-else-if="confirmOnly" class="activity-confirm">
      <p>本活动为讲解/演示，无需书面作答。阅读完成后继续。</p>
    </div>

    <div v-else-if="activityType === 'MULTIPLE_CHOICE' || (activityType === 'AUDIO_EXERCISE' && inputKind === 'CHOICE')" class="choice-list">
      <el-radio-group v-if="!multiple" v-model="singleSelected" :disabled="disabled">
        <el-radio v-for="option in options" :key="option.id" :value="option.id">{{ option.label }}</el-radio>
      </el-radio-group>
      <el-checkbox-group v-else v-model="selected" :disabled="disabled">
        <el-checkbox v-for="option in options" :key="option.id" :value="option.id">{{ option.label }}</el-checkbox>
      </el-checkbox-group>
      <div v-if="!options.length" class="activity-unsupported">
        <p>当前活动缺少选项，不能伪装成文字题。</p>
        <el-button size="small" @click="regenerate">请老师重新生成</el-button>
      </div>
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

    <div v-else-if="activityType === 'STEP_ORDERING'" class="order-list">
      <div v-for="(id, index) in orderIds" :key="id" class="order-row">
        <span class="order-index">{{ index + 1 }}</span>
        <span class="order-label">{{ itemLabel(payloadItems, id) }}</span>
        <el-button link :disabled="disabled || index === 0" @click="moveOrder(index, -1)">上移</el-button>
        <el-button link :disabled="disabled || index === orderIds.length - 1" @click="moveOrder(index, 1)">下移</el-button>
      </div>
      <div v-if="!payloadItems.length" class="activity-unsupported">
        <p>当前活动缺少排序项，不能伪装成文字题。</p>
        <el-button size="small" @click="regenerate">请老师重新生成</el-button>
      </div>
    </div>

    <div v-else-if="activityType === 'DIAGRAM_WALKTHROUGH' && inputKind === 'HOTSPOT_ORDER'" class="order-list">
      <p class="activity-note">当前以“热点顺序选择”收集答案；图像坐标点击热点暂未支持。</p>
      <div v-for="(id, index) in hotspotIds" :key="id" class="order-row">
        <span class="order-index">{{ index + 1 }}</span>
        <span class="order-label">{{ itemLabel(hotspotItems, id) }}</span>
        <el-button link :disabled="disabled || index === 0" @click="moveHotspot(index, -1)">上移</el-button>
        <el-button link :disabled="disabled || index === hotspotIds.length - 1" @click="moveHotspot(index, 1)">下移</el-button>
      </div>
      <div v-if="!hotspotItems.length" class="activity-unsupported">
        <p>当前活动没有提供热点标签，无法完成结构化排序。</p>
        <el-button size="small" @click="regenerate">请老师重新生成</el-button>
      </div>
    </div>

    <div v-else-if="activityType === 'FORMULA_DERIVATION' && inputKind === 'STEPS' && stepItems.length" class="step-list">
      <label v-for="(step, index) in stepItems" :key="step.id" class="step-row">
        <span class="blank-label">{{ step.title }}</span>
        <el-input v-model="stepValues[index]" :disabled="disabled" :placeholder="step.body || '写出这一步的推导'" />
      </label>
    </div>

    <div v-else-if="activityType === 'AUDIO_EXERCISE' && inputKind === 'DICTATION'" class="short-row">
      <el-input v-model="dictation" :disabled="disabled" placeholder="写下你听到的内容（文字转写）" />
    </div>

    <div v-else-if="activityType === 'VIDEO_ANALYSIS'" class="video-answer">
      <div class="video-row">
        <span class="blank-label">时间点</span>
        <el-input v-model="videoTimestamp" :disabled="disabled" placeholder="例如 01:23" />
      </div>
      <el-input
        v-model="videoText"
        type="textarea"
        :rows="3"
        resize="none"
        :disabled="disabled"
        placeholder="说明这个时间点发生了什么、为什么重要"
      />
    </div>

    <div v-else-if="activityType === 'PRACTICAL_TASK'" class="short-row">
      <ul v-if="checklistItems.length" class="checklist">
        <li v-for="(item, index) in checklistItems" :key="index">{{ item }}</li>
      </ul>
      <el-input
        v-model="shortText"
        type="textarea"
        :rows="4"
        resize="none"
        :disabled="disabled"
        placeholder="描述你的操作步骤、交付物和检查结果"
      />
    </div>

    <div v-else-if="activityType === 'CONVERSATION'" class="short-row">
      <div v-if="conversationTurns.length" class="dialogue">
        <p v-for="(turn, index) in conversationTurns" :key="index" :class="['dialogue-turn', turn.role]">
          <span class="dialogue-role">{{ turn.role === 'user' ? '你' : '对方' }}</span>
          {{ turn.text }}
        </p>
      </div>
      <el-input
        v-model="shortText"
        type="textarea"
        :rows="3"
        resize="none"
        :disabled="disabled"
        placeholder="用目标语言完成这一轮对话"
      />
    </div>

    <div v-else-if="activityType === 'CODE_DEMO' && inputKind === 'PREDICT_OUTPUT'" class="short-row">
      <el-input v-model="prediction" :disabled="disabled" placeholder="先不要运行，猜一猜输出是什么" />
    </div>

    <div v-else class="short-row">
      <el-input
        v-model="shortText"
        type="textarea"
        :rows="4"
        resize="none"
        :disabled="disabled"
        :maxlength="8000"
        :placeholder="
          activityType === 'IMAGE_ANALYSIS'
            ? '描述图片中的关键结构、关系或现象'
            : activityType === 'TEXT_EXPLANATION'
              ? '写下你的理解或疑问'
              : '写下你的解释或回答……'
        "
      />
    </div>

    <div class="activity-actions">
      <span class="activity-tip">
        评价模式：{{ evaluationMode }}；提交后由老师评价。
      </span>
      <el-button type="primary" size="small" :disabled="!canSubmit" @click="submit">
        {{ confirmOnly ? '我已阅读，继续' : '提交回答' }}
      </el-button>
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

.activity-attempt,
.activity-degraded {
  color: var(--ml-text-3);
  font-size: 11px;
}

.activity-degraded {
  color: var(--ml-warning);
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
  max-height: 300px;
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

.activity-images {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 8px;
}

.activity-image {
  margin: 0;
}

.activity-image img {
  width: 100%;
  max-height: 280px;
  object-fit: contain;
  border-radius: 8px;
  background: var(--ml-bg-soft);
  border: 1px solid var(--ml-border);
}

.activity-image figcaption {
  margin-top: 4px;
  color: var(--ml-text-3);
  font-size: 11px;
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

.media-caption,
.activity-note {
  margin: 0;
  color: var(--ml-text-3);
  font-size: 11px;
}

.media-missing {
  display: grid;
  place-items: center;
  min-height: 96px;
  padding: 12px;
  border: 1px dashed var(--ml-border-strong);
  border-radius: 8px;
  background: var(--ml-surface);
  color: var(--ml-text-3);
  font-size: 12px;
}

.choice-list :deep(.el-radio-group),
.choice-list :deep(.el-checkbox-group) {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}

.blank-list,
.step-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.blank-row,
.step-row {
  display: grid;
  grid-template-columns: 96px 1fr;
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

.order-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.order-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border: 1px solid var(--ml-border);
  border-radius: var(--ml-radius-sm);
  background: var(--ml-bg-soft);
}

.order-index {
  display: inline-grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--ml-accent-weak);
  color: var(--ml-accent);
  font-family: var(--ml-font-mono);
  font-size: 10.5px;
}

.order-label {
  flex: 1;
  min-width: 0;
  font-size: 12.5px;
  color: var(--ml-text-2);
}

.video-answer {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.video-row {
  display: grid;
  grid-template-columns: 72px 160px;
  align-items: center;
  gap: 8px;
}

.checklist {
  margin: 0 0 6px;
  padding-left: 18px;
  color: var(--ml-text-3);
  font-size: 12px;
  line-height: 1.6;
}

.dialogue {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 6px;
}

.dialogue-turn {
  margin: 0;
  padding: 6px 10px;
  border-radius: 8px;
  background: var(--ml-surface);
  color: var(--ml-text-2);
  font-size: 12.5px;
  line-height: 1.6;
}

.dialogue-turn.user {
  background: var(--ml-accent-weak);
}

.dialogue-role {
  margin-right: 6px;
  color: var(--ml-text-3);
  font-size: 11px;
}

.activity-result {
  padding: 8px 10px;
  border-left: 2px solid var(--ml-accent);
  border-radius: 0 var(--ml-radius-sm) var(--ml-radius-sm) 0;
  background: var(--ml-surface);
  color: var(--ml-text-2);
  font-size: 12.5px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.activity-unsupported,
.activity-confirm {
  padding: 10px 12px;
  border: 1px dashed var(--ml-border-strong);
  border-radius: var(--ml-radius);
  background: var(--ml-surface);
  color: var(--ml-text-3);
  font-size: 12.5px;
}

.activity-unsupported p,
.activity-confirm p {
  margin: 0 0 8px;
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
</style>

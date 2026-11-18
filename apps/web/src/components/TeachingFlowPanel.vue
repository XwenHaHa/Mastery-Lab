<script setup lang="ts">
import type { TeachingAction, TeachingStage, TeachingState } from '@/api/types'

defineProps<{ state: TeachingState; busy: boolean; controlBusy: boolean; hasModel: boolean }>()
defineEmits<{ action: [action: TeachingAction] }>()

const stages: { id: TeachingStage; label: string }[] = [
  { id: 'TEACH', label: '讲解' }, { id: 'DEMO', label: '演示' }, { id: 'CHECK', label: '理解检查' },
  { id: 'PAIR', label: '共同实践' }, { id: 'VERIFY', label: '独立验证' }, { id: 'NEXT', label: '本节总结' },
]
const actions: { id: TeachingAction; label: string }[] = [
  { id: 'START', label: '开始当前步骤' }, { id: 'CONTINUE', label: '继续下一步' },
  { id: 'EXPLAIN_AGAIN', label: '再讲一遍' }, { id: 'CHANGE_EXAMPLE', label: '换个例子' },
  { id: 'GIVE_HINT', label: '给我一点提示' }, { id: 'DONT_UNDERSTAND', label: '我还是不理解' },
  { id: 'TRY_MYSELF', label: '我想自己试试' }, { id: 'NEXT', label: '继续下一知识点' },
  { id: 'RESTART', label: '重新学习本节' },
]
const statusLabels = { PENDING: '待开始', ACTIVE: '老师正在准备', WAITING_USER: '等待你的回答', COMPLETED: '本步骤已完成', BLOCKED: '需要重试' }
</script>

<template>
  <section class="teaching-panel" aria-label="教学流程">
    <ol class="teaching-stages">
      <li v-for="stage in stages" :key="stage.id" :class="{ current: state.currentStage === stage.id, finished: state.completedStages.includes(stage.id) }" :aria-current="state.currentStage === stage.id ? 'step' : undefined">
        <span>{{ stage.label }}</span>
      </li>
    </ol>
    <div class="teaching-goal">
      <strong>{{ state.goal }}</strong>
      <span role="status">{{ state.paused ? '已暂停' : statusLabels[state.stageStatus] }}</span>
    </div>
    <p class="teaching-next">{{ state.nextStep }}<template v-if="state.currentStage === 'PAIR'"> · 小步骤 {{ state.pairStep }}/{{ state.pairTotalSteps }}</template></p>
    <p v-if="state.legacyCompletion" class="teaching-note">保留历史手工完成记录；不代表通过本轮教学验证。</p>
    <p v-if="state.currentStage === 'VERIFY' || state.currentStage === 'NEXT'" class="teaching-note">验证帮助 {{ state.verifyHintCount }} 次 · {{ state.masteryState === 'INDEPENDENT' ? '本轮独立完成（不等于长期掌握）' : '依据文本与代码片段评价，未执行代码' }}</p>
    <p v-if="state.summary && state.currentStage === 'NEXT'" class="teaching-summary">{{ state.summary }}</p>
    <p v-if="state.errorMessage" class="teaching-error" role="alert">{{ state.errorMessage }}</p>
    <div class="teaching-actions">
      <el-button v-for="action in actions.filter(item => state.allowedActions.includes(item.id))" :key="action.id" size="small"
        :type="['START', 'CONTINUE', 'NEXT'].includes(action.id) ? 'primary' : 'default'" plain
        :disabled="busy || controlBusy || (!hasModel && !['NEXT', 'RESTART'].includes(action.id))" @click="$emit('action', action.id)">
        {{ action.label }}
      </el-button>
      <el-button v-if="state.allowedActions.includes('PAUSE')" size="small" :disabled="controlBusy || (busy && state.stageStatus !== 'ACTIVE')" @click="$emit('action', 'PAUSE')">暂停学习</el-button>
      <el-button v-if="state.allowedActions.includes('RESUME')" size="small" type="primary" :disabled="busy || controlBusy" @click="$emit('action', 'RESUME')">继续学习</el-button>
    </div>
  </section>
</template>

<style scoped>
.teaching-panel { padding: 14px 28px; border-bottom: 1px solid var(--ml-border); background: var(--ml-bg-soft); }
.teaching-stages { display: flex; gap: 6px; padding: 0; margin: 0 0 12px; list-style: none; flex-wrap: wrap; }
.teaching-stages li { padding: 3px 9px; border-bottom: 2px solid var(--ml-border); color: var(--ml-text-3); font-size: 12px; }
.teaching-stages .current { color: var(--el-color-primary); border-color: var(--el-color-primary); }
.teaching-stages .finished:not(.current) { color: var(--el-color-success); }
.teaching-goal { display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap; font-size: 13px; }
.teaching-goal span, .teaching-next, .teaching-note { font-size: 12px; color: var(--ml-text-2); }
.teaching-next { margin-top: 6px; }
.teaching-note { margin-top: 5px; color: var(--ml-text-3); }
.teaching-summary { margin-top: 8px; font-size: 13px; }
.teaching-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.teaching-actions .el-button + .el-button { margin-left: 0; }
.teaching-error { color: var(--el-color-danger); margin-top: 8px; font-size: 12px; }
@media (max-width: 640px) { .teaching-panel { padding: 12px 16px; max-height: 42vh; overflow-y: auto; } }
</style>

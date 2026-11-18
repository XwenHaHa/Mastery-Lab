import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export type ThemeMode = 'dark' | 'light' | 'system'
export type ResolvedTheme = 'dark' | 'light'

const STORAGE_KEY = 'mastery-lab:theme'

/** 主题状态：默认深色，可切浅色或跟随系统，选择结果存本地（含设置，不含任何密钥）。 */
export const useThemeStore = defineStore('theme', () => {
  const mode = ref<ThemeMode>('dark')
  const resolved = ref<ResolvedTheme>('dark')

  const media = typeof window !== 'undefined' ? window.matchMedia('(prefers-color-scheme: light)') : null

  function apply(): void {
    const effective: ResolvedTheme = mode.value === 'system' ? (media?.matches ? 'light' : 'dark') : mode.value
    resolved.value = effective
    const root = document.documentElement
    root.classList.toggle('dark', effective === 'dark')
    root.dataset.theme = effective
  }

  function init(): void {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    if (saved === 'dark' || saved === 'light' || saved === 'system') {
      mode.value = saved
    }
    apply()
    media?.addEventListener('change', () => {
      if (mode.value === 'system') apply()
    })
  }

  function setMode(next: ThemeMode): void {
    mode.value = next
    window.localStorage.setItem(STORAGE_KEY, next)
    apply()
  }

  const isDark = computed(() => resolved.value === 'dark')

  return { mode, resolved, isDark, init, setMode }
})

import { ref, computed, watch } from 'vue'
import { readText, writeText } from '../utils/storage'

export type ThemeChoice = 'system' | 'light' | 'dark'

const THEME_KEY = 'studio.theme'

const isChoice = (value: string | null): value is ThemeChoice =>
  value === 'system' || value === 'light' || value === 'dark'

// The Studio's light / dark / system theme, remembered in this browser
export function useStudioTheme() {
  const stored = readText(THEME_KEY)
  const theme = ref<ThemeChoice>(isChoice(stored) ? stored : 'system')
  const query = window.matchMedia('(prefers-color-scheme: dark)') as MediaQueryList | undefined
  const systemDark = ref(query ? query.matches : true)
  query?.addEventListener('change', event => {
    systemDark.value = event.matches
  })
  const dataTheme = computed<'light' | 'dark'>(() =>
    theme.value === 'system' ? (systemDark.value ? 'dark' : 'light') : theme.value,
  )
  // The tokens live on :root (style.css), so the theme goes on <html>: dialogs
  // and popovers teleported to <body> then follow it too, not just the shell.
  watch(
    dataTheme,
    value => {
      document.documentElement.setAttribute('data-theme', value)
    },
    { immediate: true },
  )
  function setTheme(choice: ThemeChoice): void {
    theme.value = choice
    writeText(THEME_KEY, choice)
  }
  return { theme, dataTheme, setTheme }
}

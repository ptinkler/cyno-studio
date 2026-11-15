import { ref, computed, watch } from 'vue'

// The Studio's light / dark / system theme, remembered in this browser
export function useStudioTheme() {
  const THEME_KEY = 'studio.theme'
  const readTheme = () => {
    try {
      return localStorage.getItem(THEME_KEY) || 'system'
    } catch {
      return 'system'
    }
  }
  const theme = ref(readTheme())
  const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
  const systemDark = ref(mq ? mq.matches : true)
  mq?.addEventListener?.('change', e => (systemDark.value = e.matches))
  const dataTheme = computed(() => (theme.value === 'system' ? (systemDark.value ? 'dark' : 'light') : theme.value))
  // The tokens live on :root (style.css), so the theme goes on <html>: dialogs
  // and popovers teleported to <body> then follow it too, not just the shell.
  watch(dataTheme, t => document.documentElement.setAttribute('data-theme', t), { immediate: true })
  function setTheme(t) {
    theme.value = t
    try {
      localStorage.setItem(THEME_KEY, t)
    } catch {
      /* storage unavailable */
    }
  }
  return { theme, dataTheme, setTheme }
}

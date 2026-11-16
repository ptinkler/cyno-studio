import { ref, watch } from 'vue'
import { readText, writeText } from '../utils/storage'

export type TextSize = 'compact' | 'comfortable' | 'large'

export const TEXT_SIZES: readonly { id: TextSize; label: string; hint: string }[] = [
  { id: 'compact', label: 'Compact', hint: '15px' },
  { id: 'comfortable', label: 'Comfortable', hint: '16px' },
  { id: 'large', label: 'Large', hint: '18px' },
]

const KEY = 'studio.textSize'

const isSize = (value: string | null): value is TextSize => TEXT_SIZES.some(size => size.id === value)

// Shared by everything that asks, and remembered in this browser. Every text size is rem (style.css), so the
// choice is one attribute on <html>; it is set as soon as this module loads so the page never shows the wrong size.
const stored = readText(KEY)
const textSize = ref<TextSize>(isSize(stored) ? stored : 'comfortable')
watch(
  textSize,
  value => {
    document.documentElement.setAttribute('data-text', value)
  },
  { immediate: true },
)

export function useTextSize() {
  function setTextSize(choice: TextSize): void {
    textSize.value = choice
    writeText(KEY, choice)
  }
  return { textSize, setTextSize }
}

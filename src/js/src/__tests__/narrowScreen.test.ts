import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { NARROW_QUERY, useNarrowScreen } from '../composables/useNarrowScreen'

// A window that can be narrowed and widened, standing in for matchMedia
function fakeWindow(initiallyNarrow: boolean) {
  let narrow = initiallyNarrow
  const listeners = new Set<(event: MediaQueryListEvent) => void>()
  vi.stubGlobal('matchMedia', (query: string) => {
    expect(query).toBe(NARROW_QUERY)
    return {
      get matches() {
        return narrow
      },
      addEventListener: (_: string, fn: (event: MediaQueryListEvent) => void) => listeners.add(fn),
      removeEventListener: (_: string, fn: (event: MediaQueryListEvent) => void) => listeners.delete(fn),
    }
  })
  return {
    resize(isNarrow: boolean) {
      narrow = isNarrow
      for (const fn of listeners) fn({ matches: isNarrow } as MediaQueryListEvent)
    },
    listeners,
  }
}

function useIt(onNarrow: () => void) {
  const wrapper = mount(
    defineComponent({
      setup() {
        const narrow = useNarrowScreen(onNarrow)
        return () => h('div', String(narrow.value))
      },
    }),
  )
  return { wrapper, startedNarrow: wrapper.text() === 'true' }
}

describe('useNarrowScreen', () => {
  it('reports a narrow window and calls back each time the window becomes narrow', () => {
    const win = fakeWindow(false)
    const onNarrow = vi.fn()
    const { wrapper, startedNarrow } = useIt(onNarrow)
    expect(startedNarrow).toBe(false)
    win.resize(true)
    expect(onNarrow).toHaveBeenCalledTimes(1)
    win.resize(false)
    expect(onNarrow).toHaveBeenCalledTimes(1)
    win.resize(true)
    expect(onNarrow).toHaveBeenCalledTimes(2)
    wrapper.unmount()
    expect(win.listeners.size).toBe(0)
  })

  it('starts narrow when the window already is', () => {
    fakeWindow(true)
    expect(useIt(vi.fn()).startedNarrow).toBe(true)
  })
})

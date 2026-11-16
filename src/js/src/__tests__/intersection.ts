/** A stand-in for IntersectionObserver that a test drives by hand: `reveal()` says the watched element came into view. */
export function stubIntersectionObserver(): { observed: Element[]; reveal: () => void; restore: () => void } {
  let callback: ((entries: { isIntersecting: boolean }[]) => void) | undefined
  const observed: Element[] = []
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      constructor(cb: (entries: { isIntersecting: boolean }[]) => void) {
        callback = cb
      }
      observe(el: Element): void {
        observed.push(el)
      }
      unobserve = vi.fn()
      disconnect = vi.fn()
    },
  )
  return {
    observed,
    reveal: () => {
      callback?.([{ isIntersecting: true }])
    },
    restore: () => {
      vi.stubGlobal('IntersectionObserver', undefined)
    },
  }
}

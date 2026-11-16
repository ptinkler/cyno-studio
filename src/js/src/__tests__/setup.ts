// Test setup for Vitest
// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: (key: string): string | null => store[key] ?? null,
    setItem: (key: string, value: unknown): void => {
      store[key] = String(value)
    },
    removeItem: (key: string): void => {
      Reflect.deleteProperty(store, key)
    },
    clear: (): void => {
      store = {}
    },
    get length(): number {
      return Object.keys(store).length
    },
    key: (index: number): string | null => Object.keys(store)[index] ?? null,
  }
})()

// vi.stubGlobal installs reliably whether or not jsdom already defined
// localStorage as a non-configurable property (a plain defineProperty threw
// there, aborting setup and leaving tests with no localStorage).
vi.stubGlobal('localStorage', localStorageMock)

// jsdom has no ResizeObserver (the chat follows new content with one)
vi.stubGlobal(
  'ResizeObserver',
  class {
    observe = vi.fn()
    unobserve = vi.fn()
    disconnect = vi.fn()
  },
)

import { ref } from 'vue'

export type ToastType = 'success' | 'error' | 'info'

export interface Toast {
  id: number
  message: string
  type: ToastType
}

const DEFAULT_DURATION_MS = 3000

export function useToast() {
  const toasts = ref<Toast[]>([])
  let toastId = 0

  function removeToast(id: number): void {
    const index = toasts.value.findIndex(t => t.id === id)
    if (index > -1) {
      toasts.value.splice(index, 1)
    }
  }

  function showToast(message: string, type: ToastType = 'success', duration = DEFAULT_DURATION_MS): number {
    const id = ++toastId
    toasts.value.push({ id, message, type })

    setTimeout(() => {
      removeToast(id)
    }, duration)

    return id
  }

  return { toasts, showToast, removeToast }
}

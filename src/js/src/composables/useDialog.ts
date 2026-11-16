import { reactive } from 'vue'

// App-wide replacements for the browser's confirm()/prompt() popups. One
// dialog is shown at a time (AppDialog.vue, mounted in App.vue); each call
// returns a promise.
//
//   const r = await confirmDialog({ title, message, confirmLabel, danger,
//                                   checkbox: { label, checked } })
//   if (!r) return              // cancelled
//   r.checked                   // the checkbox's state, when there is one
//
//   const name = await promptDialog({ title, label, value, confirmLabel })
//   if (name == null) return    // cancelled

export interface DialogCheckbox {
  label: string
  checked: boolean
}

export interface DialogOptions {
  title?: string
  message?: string
  label?: string
  value?: string
  confirmLabel?: string
  danger?: boolean
  checkbox?: DialogCheckbox
}

/** What the dialog's buttons settle with: `true` for OK on a confirm, the text for a prompt, null for cancel. */
export type DialogResult = true | string | null

interface DialogState {
  open: boolean
  kind: 'confirm' | 'prompt'
  title: string
  message: string
  label: string
  value: string
  confirmLabel: string
  danger: boolean
  checkbox: DialogCheckbox | null
  resolve: ((result: DialogResult) => void) | null
}

export const dialog = reactive<DialogState>({
  open: false,
  kind: 'confirm',
  title: '',
  message: '',
  label: '',
  value: '',
  confirmLabel: 'OK',
  danger: false,
  checkbox: null,
  resolve: null,
})

function show(kind: DialogState['kind'], options: DialogOptions): Promise<DialogResult> {
  // A second dialog while one is open cancels the first
  dialog.resolve?.(null)
  return new Promise(resolve => {
    Object.assign(dialog, {
      open: true,
      kind,
      title: '',
      message: '',
      label: '',
      value: '',
      confirmLabel: 'OK',
      danger: false,
      ...options,
      checkbox: options.checkbox ? { ...options.checkbox } : null,
      resolve,
    })
  })
}

export const confirmDialog = (options: DialogOptions): Promise<{ checked: boolean } | false> =>
  show('confirm', options).then(result => (result ? { checked: !!dialog.checkbox?.checked } : false))

export const promptDialog = (options: DialogOptions): Promise<string | null> =>
  show('prompt', options).then(result => (typeof result === 'string' ? result : null))

// Called by AppDialog: the button pressed (or null for cancel)
export function settleDialog(result: DialogResult): void {
  const resolve = dialog.resolve
  dialog.open = false
  dialog.resolve = null
  resolve?.(result)
}

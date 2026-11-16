import { inject } from 'vue'
import type { InjectionKey } from 'vue'
import type { Catalogues, ComposerSettings } from './composables/useComposerSettings'
import type { ShowToast } from './composables/useToast'

// What the app hands down the component tree with provide/inject. Each is typed by its key, so an injecting
// component gets the real type rather than whatever it claims.

/** Shows a toast: provided by App, used by anything that can fail. */
export const showToastKey: InjectionKey<ShowToast> = Symbol('showToast')

/** The Studio's composer settings, read by the inspector's model and option sections. */
export const composerSettingsKey: InjectionKey<ComposerSettings> = Symbol('composerSettings')

/** The model catalogue, for a message's "Try another model". */
export const chatModelsKey: InjectionKey<Catalogues> = Symbol('chatModels')

/** A toast function that does nothing, for a component rendered without an App around it. */
export const noToast: ShowToast = () => 0

/** The provided value for `key`; a component that needs it fails loudly when nothing above provides it. */
export function injectRequired<T>(key: InjectionKey<T>): T {
  const value = inject(key)
  if (value === undefined) throw new Error(`${key.description ?? 'A value'} was not provided`)
  return value
}

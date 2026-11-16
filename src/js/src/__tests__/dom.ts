/**
 * DOM lookups for tests that read the real document (teleported dialogs live in <body>). A miss, or an
 * element of another kind than asked for, fails the test with the selector instead of a vague null.
 */
import type { VueWrapper } from '@vue/test-utils'

/** What tests need of a mounted component: typed ESLint reads components as untyped, so helpers take this shape. */
export type Wrapper = Pick<VueWrapper, 'find' | 'findAll' | 'emitted'>

/** The JSON a component saved to localStorage under `key` (null when there is none). */
export const storedJson = (key: string): unknown => JSON.parse(localStorage.getItem(key) ?? 'null') as unknown

type Kind<E extends Element> = new (...args: never[]) => E

export function one(selector: string, root?: ParentNode): HTMLElement
export function one<E extends Element>(kind: Kind<E>, selector: string, root?: ParentNode): E
export function one(first: string | Kind<Element>, second?: string | ParentNode, third?: ParentNode): Element {
  const [kind, selector, root] =
    typeof first === 'string'
      ? [HTMLElement, first, second as ParentNode | undefined]
      : [first, second as string, third]
  const found = (root ?? document.body).querySelector(selector)
  if (!(found instanceof kind)) throw new Error(`Nothing of the right kind matches "${selector}"`)
  return found
}

/** Every HTML element matching `selector`. */
export const all = (selector: string, root: ParentNode = document.body): HTMLElement[] =>
  [...root.querySelectorAll(selector)].filter((el): el is HTMLElement => el instanceof HTMLElement)

/** The value, or a failed test when there is none (an array element or a lookup the test relies on). */
export function defined<T>(value: T | null | undefined, what = 'value'): T {
  if (value === undefined || value === null) throw new Error(`Expected ${what} to exist`)
  return value
}

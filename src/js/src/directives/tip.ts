import type { Directive } from 'vue'

// `v-tip="'Rename'"`: the same popover as InfoTip, on the element itself instead of a wrapper, so a button keeps
// its place in its row. It opens on hover and on keyboard focus (a tap does the button's own action) and closes on
// leave, blur, Escape or click. One shared bubble serves every element. Unlike `title`, keyboard users reach it;
// icon-only controls also need an `aria-label`, which callers add next to it.
const MARGIN = 8
const MAX_WIDTH = 288
const NEEDS_ROOM = 64
const BUBBLE_ID = 'tip-bubble'

let bubble: HTMLDivElement | null = null
let owner: HTMLElement | null = null

function ensureBubble(): HTMLDivElement {
  if (bubble?.isConnected) return bubble
  bubble = document.createElement('div')
  bubble.id = BUBBLE_ID
  bubble.className = 'tip-bubble'
  bubble.setAttribute('role', 'tooltip')
  document.body.append(bubble)
  return bubble
}

function show(el: HTMLElement, text: string): void {
  const rect = el.getBoundingClientRect()
  const pop = ensureBubble()
  pop.textContent = text
  const left = Math.max(MARGIN, Math.min(rect.left, window.innerWidth - MAX_WIDTH - MARGIN))
  pop.style.left = `${String(left)}px`
  const above = rect.top > NEEDS_ROOM
  pop.style.top = above ? 'auto' : `${String(rect.bottom + MARGIN)}px`
  pop.style.bottom = above ? `${String(window.innerHeight - rect.top + MARGIN)}px` : 'auto'
  pop.hidden = false
  el.setAttribute('aria-describedby', BUBBLE_ID)
  owner = el
}

function hide(el: HTMLElement): void {
  if (owner !== el) return
  if (bubble) bubble.hidden = true
  el.removeAttribute('aria-describedby')
  owner = null
}

const texts = new WeakMap<HTMLElement, string>()
// The text is also left as `data-tip`, so a test (or a stylesheet) can find what an element explains
function remember(el: HTMLElement, value: string | null | undefined): void {
  if (value) {
    texts.set(el, value)
    el.dataset['tip'] = value
  } else {
    texts.delete(el)
    delete el.dataset['tip']
  }
}
const open = (event: Event): void => {
  const el = event.currentTarget
  const text = el instanceof HTMLElement ? texts.get(el) : undefined
  if (el instanceof HTMLElement && text) show(el, text)
}
const close = (event: Event): void => {
  if (event.currentTarget instanceof HTMLElement) hide(event.currentTarget)
}
const closeOnEscape = (event: Event): void => {
  if (event instanceof KeyboardEvent && event.key === 'Escape') close(event)
}
const EVENTS: readonly [string, (event: Event) => void][] = [
  ['mouseenter', open],
  ['focus', open],
  ['mouseleave', close],
  ['blur', close],
  ['click', close],
  ['keydown', closeOnEscape],
]

/** The text to show; an empty or missing value shows nothing. */
export const vTip: Directive<HTMLElement, string | null | undefined> = {
  mounted(el, { value }) {
    remember(el, value)
    for (const [name, handler] of EVENTS) el.addEventListener(name, handler)
  },
  updated(el, { value }) {
    remember(el, value)
  },
  beforeUnmount(el) {
    hide(el)
    texts.delete(el)
    for (const [name, handler] of EVENTS) el.removeEventListener(name, handler)
  },
}

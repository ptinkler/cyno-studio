import { ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import type { Ref } from 'vue'
import type { RefItem } from '../utils/refItems'
import { imagesIn } from '../utils/files'

// ― contenteditable plumbing: [@name] text is the source of truth; a pill is
// just how a known mention is shown. We edit the DOM imperatively (re-rendering
// on every keystroke would fight the caret) and serialize back to [@name]. ―
const MENTION = /\[@([a-zA-Z0-9_]+)\]/g

// Pills are built imperatively, so Vue's scoped CSS can't reach them — style
// them inline (CSS vars resolve against the app root).
const PILL_CSS =
  'display:inline-flex;align-items:center;gap:6px;vertical-align:middle;margin:0 2px;' +
  'padding:1px 8px 1px 3px;border:1px solid var(--sborder);border-radius:8px;' +
  'background:var(--saccent-soft);color:var(--saccent);font-size:0.85em;line-height:1.5;' +
  'user-select:none;white-space:nowrap'

interface MentionHooks {
  /** The current prompt text. */
  draft: () => string
  /** The references that can be mentioned. */
  refItems: Ref<readonly RefItem[]>
  /** Whether "@" opens the picker. */
  canMention: () => boolean
  onUpdate: (text: string) => void
  onFiles: (files: File[]) => void
  onSend: () => void
}

const isPill = (node: Node): node is HTMLElement => node instanceof HTMLElement && node.classList.contains('pill')

/** Text of a DOM node, with each pill written as its [@name]. */
function nodeText(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? ''
  if (node.nodeName === 'BR') return '\n'
  if (isPill(node)) return `[@${node.dataset['name'] ?? ''}]`
  let text = ''
  for (const child of node.childNodes) text += nodeText(child)
  return text
}

function makePill(refItem: RefItem): HTMLElement {
  const span = document.createElement('span')
  span.className = 'pill'
  span.contentEditable = 'false'
  span.dataset['name'] = refItem.name
  span.style.cssText = PILL_CSS
  if (refItem.type === 'image' && refItem.preview) {
    const image = document.createElement('img')
    image.src = refItem.preview
    image.style.cssText = 'width:18px;height:18px;border-radius:4px;object-fit:cover;flex:none'
    span.appendChild(image)
  } else {
    const icon = document.createElement('span')
    icon.textContent = refItem.type === 'audio' ? '🔊' : '🎞'
    icon.style.fontSize = '13px'
    span.appendChild(icon)
  }
  span.appendChild(document.createTextNode(refItem.label))
  return span
}

// The Studio prompt box: a contenteditable where reference mentions ([@name]) show as inline pills while the
// [@name] text stays the source of truth. `draft()` reads the current text; `refItems` is a ref of the
// mentionable references; `canMention()` says whether "@" opens the picker. The rest are the box's outputs.
export function useMentionEditor({ draft, refItems, canMention, onUpdate, onFiles, onSend }: MentionHooks) {
  const ed = ref<HTMLElement | null>(null) // the contenteditable prompt
  const atMenu = ref(false) // the @-mention picker
  const mentionRange = ref<Range | null>(null)

  const closeMenu = (): void => {
    atMenu.value = false
    mentionRange.value = null
  }
  const onEsc = (event: KeyboardEvent): void => {
    if (event.key === 'Escape') closeMenu()
  }
  onMounted(() => {
    document.addEventListener('keydown', onEsc)
  })
  onBeforeUnmount(() => {
    document.removeEventListener('keydown', onEsc)
  })

  // Text → nodes: [@name] becomes a pill when that reference is attached, else stays text
  function draftNodes(text: string): ChildNode[] {
    const nodes: ChildNode[] = []
    let last = 0
    for (const match of text.matchAll(MENTION)) {
      if (match.index > last) nodes.push(document.createTextNode(text.slice(last, match.index)))
      const refItem = refItems.value.find(r => r.name === match[1])
      nodes.push(refItem ? makePill(refItem) : document.createTextNode(match[0]))
      last = match.index + match[0].length
    }
    if (last < text.length) nodes.push(document.createTextNode(text.slice(last)))
    return nodes
  }

  function renderDraft(text: string): void {
    const el = ed.value
    if (!el) return
    el.textContent = ''
    for (const node of draftNodes(text)) el.appendChild(node)
  }

  function serialize(): string {
    let out = ''
    for (const node of ed.value?.childNodes ?? []) out += nodeText(node)
    return out
  }

  function syncDraft(): void {
    onUpdate(serialize())
  }

  function placeCaretEnd(): void {
    const el = ed.value
    const selection = window.getSelection()
    if (!el || !selection) return
    const range = document.createRange()
    range.selectNodeContents(el)
    range.collapse(false)
    selection.removeAllRanges()
    selection.addRange(range)
  }

  function saveMentionRange(): void {
    const selection = window.getSelection()
    if (selection?.rangeCount && selection.anchorNode && ed.value?.contains(selection.anchorNode)) {
      mentionRange.value = selection.getRangeAt(0).cloneRange()
    }
  }

  /** Where an insertion goes: the saved @ position, else the caret, else the end of the box. */
  function insertionRange(el: HTMLElement, selection: Selection): Range {
    const saved = mentionRange.value
    el.focus()
    if (saved && el.contains(saved.commonAncestorContainer)) {
      selection.removeAllRanges()
      selection.addRange(saved)
      mentionRange.value = null
      return selection.getRangeAt(0)
    }
    if (selection.rangeCount && selection.anchorNode && el.contains(selection.anchorNode)) {
      return selection.getRangeAt(0)
    }
    const range = document.createRange()
    range.selectNodeContents(el)
    range.collapse(false)
    return range
  }

  function insertNode(node: ChildNode, trailingSpace = false): void {
    const el = ed.value
    const selection = window.getSelection()
    if (!el || !selection) return
    const range = insertionRange(el, selection)
    range.deleteContents()
    range.insertNode(node)
    let after = node
    if (trailingSpace) {
      const space = document.createTextNode(' ')
      node.after(space)
      after = space
    }
    range.setStartAfter(after)
    range.collapse(true)
    selection.removeAllRanges()
    selection.addRange(range)
    syncDraft()
  }

  function insertMention(refItem: RefItem): void {
    atMenu.value = false
    insertNode(makePill(refItem), true)
  }

  function toggleMentionMenu(): void {
    if (atMenu.value) {
      closeMenu()
    } else {
      saveMentionRange()
      atMenu.value = true
    }
  }

  // Re-render only on external draft changes (enhance, clear, resend) — not our
  // own edits — so the caret isn't disturbed mid-type.
  watch(
    () => draft(),
    text => {
      if (ed.value && text !== serialize()) {
        renderDraft(text)
        void nextTick(placeCaretEnd)
      }
    },
  )
  // Attachments changed: stale pills may need to re-pill or drop back to text.
  watch(
    () => refItems.value.map(r => `${r.name}:${r.key}`).join(','),
    () => {
      if (ed.value) {
        renderDraft(serialize())
        syncDraft()
      }
    },
  )
  onMounted(() => {
    renderDraft(draft())
  })

  function onKey(event: KeyboardEvent): void {
    if (event.key === '@' && canMention()) {
      event.preventDefault()
      saveMentionRange()
      atMenu.value = true
    } else if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      onSend()
    } else if (event.key === 'Enter' && event.shiftKey) {
      event.preventDefault()
      insertNode(document.createTextNode('\n'))
    }
  }

  // Copy / cut: put the selection on the clipboard as plain text with each pill
  // written as its [@name] — the browser's own copy drops the pills (they're
  // non-editable elements with no text of their own), leaving blanks.
  function selectionText(): string | null {
    const selection = window.getSelection()
    if (
      !selection?.rangeCount ||
      selection.isCollapsed ||
      !selection.anchorNode ||
      !ed.value?.contains(selection.anchorNode)
    ) {
      return null
    }
    const holder = document.createElement('div')
    holder.appendChild(selection.getRangeAt(0).cloneContents())
    return nodeText(holder)
  }

  function onCopy(event: ClipboardEvent): void {
    const text = selectionText()
    if (text === null) return
    event.clipboardData?.setData('text/plain', text)
    event.preventDefault()
  }

  function onCut(event: ClipboardEvent): void {
    const text = selectionText()
    if (text === null) return
    event.clipboardData?.setData('text/plain', text)
    event.preventDefault()
    window.getSelection()?.getRangeAt(0).deleteContents()
    syncDraft()
  }

  // Pasted screenshots become attachments; everything else pastes as plain text
  // (so copied rich markup can't get into the contenteditable).
  function onPaste(event: ClipboardEvent): void {
    const images = imagesIn(event.clipboardData?.files)
    if (images.length) {
      event.preventDefault()
      onFiles(images)
      return
    }
    const text = event.clipboardData?.getData('text/plain')
    if (text !== undefined) {
      event.preventDefault()
      // [@name] in pasted text turns into pills for the references that are attached
      for (const node of draftNodes(text)) insertNode(node)
    }
  }

  function focusPrompt(): void {
    ed.value?.focus()
  }

  return { ed, atMenu, insertMention, toggleMentionMenu, syncDraft, onKey, onCopy, onCut, onPaste, focusPrompt }
}

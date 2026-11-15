import { ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'

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

// The Studio prompt box: a contenteditable where reference mentions ([@name]) show as inline pills while the
// [@name] text stays the source of truth. `draft()` reads the current text; `refItems` is a ref of the
// mentionable references; `canMention()` says whether "@" opens the picker. The rest are the box's outputs.
export function useMentionEditor({ draft, refItems, canMention, onUpdate, onFiles, onSend }) {
  const ed = ref(null) // the contenteditable prompt
  const atMenu = ref(false) // the @-mention picker
  const mentionRange = ref(null)
  const onEsc = e => {
    if (e.key === 'Escape') {
      atMenu.value = false
      mentionRange.value = null
    }
  }
  onMounted(() => document.addEventListener('keydown', onEsc))
  onBeforeUnmount(() => document.removeEventListener('keydown', onEsc))

  function makePill(refItem) {
    const span = document.createElement('span')
    span.className = 'pill'
    span.contentEditable = 'false'
    span.dataset.name = refItem.name
    span.style.cssText = PILL_CSS
    if (refItem.type === 'image' && refItem.preview) {
      const im = document.createElement('img')
      im.src = refItem.preview
      im.style.cssText = 'width:18px;height:18px;border-radius:4px;object-fit:cover;flex:none'
      span.appendChild(im)
    } else {
      const ic = document.createElement('span')
      ic.textContent = refItem.type === 'audio' ? '🔊' : '🎞'
      ic.style.fontSize = '13px'
      span.appendChild(ic)
    }
    span.appendChild(document.createTextNode(refItem.label))
    return span
  }

  // Text → nodes: [@name] becomes a pill when that reference is attached, else stays text
  function draftNodes(text) {
    const nodes = []
    let last = 0
    let m
    MENTION.lastIndex = 0
    while ((m = MENTION.exec(text))) {
      if (m.index > last) nodes.push(document.createTextNode(text.slice(last, m.index)))
      const refItem = refItems.value.find(r => r.name === m[1])
      nodes.push(refItem ? makePill(refItem) : document.createTextNode(m[0]))
      last = MENTION.lastIndex
    }
    if (last < text.length) nodes.push(document.createTextNode(text.slice(last)))
    return nodes
  }
  function renderDraft(text) {
    const el = ed.value
    if (!el) return
    el.textContent = ''
    for (const node of draftNodes(text)) el.appendChild(node)
  }

  function nodeText(node) {
    if (node.nodeType === Node.TEXT_NODE) return node.textContent
    if (node.nodeName === 'BR') return '\n'
    if (node.classList?.contains('pill')) return `[@${node.dataset.name}]`
    let t = ''
    for (const c of node.childNodes) t += nodeText(c)
    return t
  }
  function serialize() {
    let out = ''
    for (const node of ed.value?.childNodes || []) out += nodeText(node)
    return out
  }
  function syncDraft() {
    onUpdate(serialize())
  }

  function placeCaretEnd() {
    const el = ed.value
    if (!el) return
    const range = document.createRange()
    range.selectNodeContents(el)
    range.collapse(false)
    const sel = window.getSelection()
    sel.removeAllRanges()
    sel.addRange(range)
  }

  function saveMentionRange() {
    const sel = window.getSelection()
    if (sel?.rangeCount && ed.value?.contains(sel.anchorNode)) mentionRange.value = sel.getRangeAt(0).cloneRange()
  }

  function insertNode(node, trailingSpace = false) {
    const el = ed.value
    const sel = window.getSelection()
    let range
    const savedRange = mentionRange.value
    if (savedRange && el.contains(savedRange.commonAncestorContainer)) {
      el.focus()
      sel.removeAllRanges()
      sel.addRange(savedRange)
      mentionRange.value = null
      range = sel.getRangeAt(0)
    } else if (sel.rangeCount && el.contains(sel.anchorNode)) {
      el.focus()
      range = sel.getRangeAt(0)
    } else {
      el.focus()
      range = document.createRange()
      range.selectNodeContents(el)
      range.collapse(false)
    }
    range.deleteContents()
    range.insertNode(node)
    let after = node
    if (trailingSpace) {
      const space = document.createTextNode(' ')
      node.after(space)
      after = space
    }
    range.setStartAfter(after)
    range.collapse(true)
    sel.removeAllRanges()
    sel.addRange(range)
    syncDraft()
  }

  function insertMention(refItem) {
    atMenu.value = false
    insertNode(makePill(refItem), true)
  }
  function toggleMentionMenu() {
    if (atMenu.value) {
      atMenu.value = false
      mentionRange.value = null
    } else {
      saveMentionRange()
      atMenu.value = true
    }
  }

  // Re-render only on external draft changes (enhance, clear, resend) — not our
  // own edits — so the caret isn't disturbed mid-type.
  watch(
    () => draft(),
    v => {
      if (ed.value && v !== serialize()) {
        renderDraft(v)
        nextTick(placeCaretEnd)
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
  onMounted(() => renderDraft(draft()))

  function onKey(e) {
    if (e.key === '@' && canMention()) {
      e.preventDefault()
      saveMentionRange()
      atMenu.value = true
    } else if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      onSend()
    } else if (e.key === 'Enter' && e.shiftKey) {
      e.preventDefault()
      insertNode(document.createTextNode('\n'))
    }
  }
  // Copy / cut: put the selection on the clipboard as plain text with each pill
  // written as its [@name] — the browser's own copy drops the pills (they're
  // non-editable elements with no text of their own), leaving blanks.
  function selectionText() {
    const sel = window.getSelection()
    if (!sel?.rangeCount || sel.isCollapsed || !ed.value?.contains(sel.anchorNode)) return null
    const holder = document.createElement('div')
    holder.appendChild(sel.getRangeAt(0).cloneContents())
    return nodeText(holder)
  }
  function onCopy(e) {
    const text = selectionText()
    if (text == null) return
    e.clipboardData.setData('text/plain', text)
    e.preventDefault()
  }
  function onCut(e) {
    const text = selectionText()
    if (text == null) return
    e.clipboardData.setData('text/plain', text)
    e.preventDefault()
    window.getSelection().getRangeAt(0).deleteContents()
    syncDraft()
  }
  // Pasted screenshots become attachments; everything else pastes as plain text
  // (so copied rich markup can't get into the contenteditable).
  function onPaste(e) {
    const imgs = [...(e.clipboardData?.files || [])].filter(f => f.type.startsWith('image/'))
    if (imgs.length) {
      e.preventDefault()
      return onFiles(imgs)
    }
    const text = e.clipboardData?.getData('text/plain')
    if (text != null) {
      e.preventDefault()
      // [@name] in pasted text turns into pills for the references that are attached
      for (const node of draftNodes(text)) insertNode(node)
    }
  }

  function focusPrompt() {
    ed.value?.focus()
  }
  return { ed, atMenu, insertMention, toggleMentionMenu, syncDraft, onKey, onCopy, onCut, onPaste, focusPrompt }
}

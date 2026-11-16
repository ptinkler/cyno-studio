import { describe, it, expect } from 'vitest'
import { TAG_LABELS } from '../composables/modelTags'
import source from '../../../py/web/providers/model_tags.py?raw'

// TAG_LABELS hand-mirrors TAGS in the backend (src/py/web/providers/model_tags.py): same slugs, labels and order.
// This reads the Python source, so the two can't drift apart unnoticed.

function backendTags(): string[][] {
  const block = /^TAGS: dict\[str, str\] = \{\n([\s\S]*?)^\}/m.exec(source)?.[1] ?? ''
  return [...block.matchAll(/^\s+"(\w+)": "([^"]+)",/gm)].map(m => [m[1] ?? '', m[2] ?? ''])
}

describe('model tag labels', () => {
  it('match the backend TAGS, in the same order', () => {
    const backend = backendTags()
    expect(backend.length).toBeGreaterThan(10)
    expect(Object.entries(TAG_LABELS)).toEqual(backend)
  })
})

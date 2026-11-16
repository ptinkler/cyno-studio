import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

// The colour tokens in style.css, judged against WCAG AA (4.5:1 for text). Quiet text, the status colours and
// the colours behind white button text each failed it before; this keeps them from drifting back.
const css = readFileSync(join(process.cwd(), 'src', 'style.css'), 'utf8')

function tokens(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`)
  const block = css.slice(start, css.indexOf('\n}', start))
  return Object.fromEntries(
    [...block.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-f]{6})\b/gi)].map(m => [m[1] ?? '', m[2] ?? '']),
  )
}

function luminance(hex: string): number {
  const [r = 0, g = 0, b = 0] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}

function ratio(a: string, b: string): number {
  const [hi = 0, lo = 0] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const AA = 4.5
const surfaces = ['sbg', 'sbg2', 'spanel2', 'shover']
const textColours = [
  'sfg',
  'smuted',
  'sfaint',
  'saccent',
  'sdanger',
  'ssuccess',
  'swarn',
  'p-pollo',
  'p-venice',
  'p-openrouter',
]

describe.each([
  ['dark', ':root'],
  ['light', "[data-theme='light']"],
])('%s theme colours', (_name, selector) => {
  const t = tokens(selector)
  const all = { ...tokens(':root'), ...t }

  it.each(textColours)('%s is readable on every surface', colour => {
    for (const surface of surfaces) {
      expect(ratio(all[colour] ?? '', all[surface] ?? ''), `${colour} on ${surface}`).toBeGreaterThanOrEqual(AA)
    }
  })

  it.each(['saccent-fill', 'sdanger-fill'])('white text on %s is readable', fill => {
    expect(ratio('#ffffff', all[fill] ?? '')).toBeGreaterThanOrEqual(AA)
  })
})

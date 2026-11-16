import { describe, expect, it } from 'vitest'
import { costRows } from '../utils/format'

const rows = (...pairs: [string, string][]) => pairs.map(([label, value]) => ({ label, value }))

describe('costRows', () => {
  it('splits the one total into the text and each picture', () => {
    expect(costRows(0.07, [{ model: 'venice/seedream-v5-pro', cost: 0.06 }])).toEqual(
      rows(['Text', '$0.01'], ['seedream-v5-pro', '$0.06']),
    )
  })

  it('leaves out the text when the pictures account for everything', () => {
    expect(costRows(0.06, [{ model: 'a/img', cost: 0.06 }])).toEqual(rows(['img', '$0.06']))
  })

  it('counts the earlier versions of a picture that were paid for, and credits as their own row', () => {
    expect(
      costRows(0.2, [
        { model: 'a/img', cost: 0.05, versions: [{ cost: 0.04 }, { cost: 0.03 }] },
        { model: 'pollo/vid', credits: 3 },
      ]),
    ).toEqual(rows(['Text', '$0.08'], ['img', '$0.05'], ['img, earlier versions', '$0.07'], ['vid', '3 credits']))
  })

  it('treats a cent-fraction of rounding as nothing', () => {
    expect(costRows(0.06000001, [{ model: 'a/img', cost: 0.06 }])).toEqual(rows(['img', '$0.06']))
  })

  it('is just the text for a reply with no pictures', () => {
    expect(costRows(0.0021, [])).toEqual(rows(['Text', '$0.0021']))
  })
})

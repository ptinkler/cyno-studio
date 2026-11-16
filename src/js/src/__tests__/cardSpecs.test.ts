import { describe, expect, it } from 'vitest'
import { cardParams, cardRefFiles, cardSpecs, refUrl, refsLabel, refsTitle } from '../utils/cardSpecs'

describe('cardParams', () => {
  it('reads each field for the type it should have and drops the rest', () => {
    const p = cardParams({
      duration: '5',
      resolution: 720,
      aspect_ratio: '16:9',
      refs: ['a.png', 7, 'b.png'],
      context: 1,
    })
    expect(p.duration).toBeNull()
    expect(p.resolution).toBe('')
    expect(p.aspect_ratio).toBe('16:9')
    expect(p.refs).toEqual(['a.png', 'b.png'])
    expect(p.context).toBe(true)
  })

  it('is empty for nothing', () => {
    expect(cardParams(null).refs).toEqual([])
    expect(cardParams(undefined).generate_audio).toBeNull()
  })
})

describe('cardSpecs', () => {
  it('lists a video by what it was made from, length, size and audio', () => {
    const p = cardParams({
      first_frame: 'f.png',
      duration: 5,
      resolution: '720p',
      aspect_ratio: '16:9',
      generate_audio: false,
    })
    expect(cardSpecs('video', p)).toEqual(['from image', '5s', '720p', '16:9', 'no audio'])
  })

  it('says first+last frame, and from video, when it was', () => {
    expect(cardSpecs('video', cardParams({ last_frame: 'l.png' }))).toEqual(['first+last frame'])
    expect(cardSpecs('video', cardParams({ source_video: 'v.mp4' }))).toEqual(['from video'])
  })

  it('does not call a video made from refs "from image"', () => {
    expect(cardSpecs('video', cardParams({ first_frame: 'f.png', refs: ['r.png'] }))).toEqual([])
  })

  it('leaves video-only details off an image', () => {
    const p = cardParams({ duration: 5, generate_audio: true, resolution: '1K', character_names: ['Linh', 'Bao'] })
    expect(cardSpecs('image', p)).toEqual(['1K', '👤 Linh, Bao'])
  })
})

describe('references', () => {
  it('counts them, and says when the model took fewer', () => {
    expect(refsLabel(cardParams({ refs: ['a'] }))).toBe('1 ref')
    expect(refsLabel(cardParams({ refs: ['a', 'b', 'c', 'd'] }))).toBe('4 refs')
    expect(refsLabel(cardParams({ refs: ['a', 'b', 'c', 'd'], refs_used: 2 }))).toBe('2 of 4 refs')
    expect(refsTitle(cardParams({ refs: ['a', 'b'], refs_used: 1 }))).toContain('only the first 1 of these')
    expect(refsTitle(cardParams({ refs: ['a'] }))).toBe('Based on these images:')
  })

  it('serves a character image or a chat file', () => {
    expect(refUrl('c1', 'char:7/img 1.png')).toBe('/api/characters/7/images/img%201.png')
    expect(refUrl('c1', 'up_a.png')).toBe('/api/chat/media/c1/up_a.png')
  })
})

describe('cardRefFiles', () => {
  it('lists the frames, references and named images once each, leaving characters out', () => {
    expect(
      cardRefFiles({
        first_frame: 'a.png',
        last_frame: 'b.png',
        refs: ['a.png', 'char:3/c.png', 'd.png'],
        ref_items: [
          { file: 'e.png', type: 'image' },
          { file: 'v.mp4', type: 'video' },
        ],
      }),
    ).toEqual(['a.png', 'b.png', 'd.png', 'e.png'])
  })

  it('is empty for a card made from words alone', () => {
    expect(cardRefFiles(null)).toEqual([])
    expect(cardRefFiles({ first_frame: null, refs: [] })).toEqual([])
  })
})

describe('refsLabel with images that no longer exist', () => {
  const p = cardParams({ refs: ['a.png', 'char:7/b.png', 'char:7/c.png'] })

  it("doesn't count them", () => {
    expect(refsLabel(p, 2)).toBe('1 ref')
    expect(refsLabel(p, 1)).toBe('2 refs')
  })

  it('says so when none are left', () => {
    expect(refsLabel(p, 3)).toBe('refs unavailable')
  })

  it('names how many are gone in the hover title', () => {
    expect(refsTitle(p, 2)).toBe('Based on these images (2 no longer available):')
    expect(refsTitle(p)).toBe('Based on these images:')
  })

  it('still reports the model taking fewer than there are', () => {
    expect(refsLabel(cardParams({ refs: ['a', 'b', 'c', 'd'], refs_used: 2 }), 1)).toBe('2 of 3 refs')
  })
})

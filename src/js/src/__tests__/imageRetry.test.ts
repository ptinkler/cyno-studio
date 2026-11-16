import { describe, it, expect, vi, afterEach } from 'vitest'
import { reloadImageLater } from '../utils/imageRetry'

describe('reloadImageLater', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('reloads the image after the delay, not before', () => {
    vi.useFakeTimers()
    const img = { src: '/thumb/1' }
    reloadImageLater(img, '/thumb/1', 2000)
    vi.advanceTimersByTime(1999)
    expect(img.src).toBe('/thumb/1')
    vi.advanceTimersByTime(1)
    expect(img.src).toBe('/thumb/1?retry=1')
  })

  it('appends to a URL that already has a query string', () => {
    vi.useFakeTimers()
    const img = { src: '' }
    reloadImageLater(img, '/image/a.png?w=320', 10)
    vi.advanceTimersByTime(10)
    expect(img.src).toBe('/image/a.png?w=320&retry=1')
  })
})

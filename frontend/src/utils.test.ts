import { describe, expect, it } from 'vitest'
import { formatTime, initials, markerFilename } from './utils'

describe('chat display helpers', () => {
  it('formats a timestamp and falls back for invalid values', () => {
    expect(formatTime(0)).toBe('--:--')
    expect(formatTime('not-a-date')).toBe('not-a-date')
  })

  it('creates compact initials', () => {
    expect(initials('admin')).toBe('AD')
    expect(initials('')).toBe('?')
  })

  it('extracts legacy attachment markers without changing names', () => {
    expect(markerFilename('::img::photo.png', '::img::')).toBe('photo.png')
    expect(markerFilename('plain text', '::img::')).toBeNull()
  })
})

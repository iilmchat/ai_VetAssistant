import { describe, expect, it } from 'vitest'
import { isAccessRequestMode } from './access'

describe('isAccessRequestMode', () => {
  it('распознаёт mode=request', () => {
    expect(isAccessRequestMode('?mode=request')).toBe(true)
    expect(isAccessRequestMode('?utm_source=landing&mode=request')).toBe(true)
  })

  it('игнорирует другие режимы и пустой query', () => {
    expect(isAccessRequestMode('?mode=login')).toBe(false)
    expect(isAccessRequestMode('?mode=REQUEST')).toBe(false)
    expect(isAccessRequestMode('')).toBe(false)
  })
})

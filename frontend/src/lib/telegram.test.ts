import { describe, expect, it } from 'vitest'
import {
  codeSecondsLeft,
  formatCountdown,
  formatTelegramCode,
} from './telegram'

const NOW = Date.parse('2026-11-05T20:00:00+00:00')

describe('codeSecondsLeft', () => {
  it('считает секунды до истечения', () => {
    const expiresAt = new Date(NOW + 90_000).toISOString()

    expect(codeSecondsLeft(expiresAt, NOW)).toBe(90)
  })

  it('не уходит в минус для истёкшего кода', () => {
    const expiresAt = new Date(NOW - 5_000).toISOString()

    expect(codeSecondsLeft(expiresAt, NOW)).toBe(0)
  })

  it('возвращает 0 для некорректной даты', () => {
    expect(codeSecondsLeft('not-a-date', NOW)).toBe(0)
  })
})

describe('formatCountdown', () => {
  it('форматирует минуты и секунды', () => {
    expect(formatCountdown(600)).toBe('10:00')
    expect(formatCountdown(61)).toBe('1:01')
    expect(formatCountdown(59)).toBe('0:59')
  })

  it('не показывает отрицательные значения', () => {
    expect(formatCountdown(-3)).toBe('0:00')
  })
})

describe('formatTelegramCode', () => {
  it('делит код на две группы', () => {
    expect(formatTelegramCode('ABCD2345')).toBe('ABCD 2345')
  })

  it('оставляет короткий код и обрезает пробелы', () => {
    expect(formatTelegramCode(' ABC ')).toBe('ABC')
  })
})

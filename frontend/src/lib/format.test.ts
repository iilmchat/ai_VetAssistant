import { describe, expect, it } from 'vitest'
import {
  formatAppointmentMoment,
  formatDate,
  formatDateTime,
} from './format'

describe('formatDate', () => {
  it('превращает ISO-дату в ДД.ММ', () => {
    expect(formatDate('2026-11-04')).toBe('04.11')
  })

  it('оставляет нестандартную дату как есть', () => {
    expect(formatDate('завтра')).toBe('завтра')
  })
})

describe('formatDateTime', () => {
  it('добавляет время к дате регистрации', () => {
    const formatted = formatDateTime('2026-11-04T10:00:00')
    expect(formatted).toContain('04.11.2026')
    expect(formatted).toContain('10:00')
  })

  it('оставляет нестандартную дату как есть', () => {
    expect(formatDateTime('не дата')).toBe('не дата')
  })
})

describe('formatAppointmentMoment', () => {
  it('собирает дату и время', () => {
    expect(formatAppointmentMoment('2026-11-04', '10:00')).toBe(
      '04.11 в 10:00',
    )
  })

  it('не добавляет лишний разделитель без времени', () => {
    expect(formatAppointmentMoment('2026-11-04', '')).toBe('04.11')
  })
})

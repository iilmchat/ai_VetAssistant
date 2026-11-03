import { describe, expect, it } from 'vitest'
import { formatAppointmentMoment, formatDate } from './format'

describe('formatDate', () => {
  it('превращает ISO-дату в ДД.ММ', () => {
    expect(formatDate('2026-11-04')).toBe('04.11')
  })

  it('оставляет нестандартную дату как есть', () => {
    expect(formatDate('завтра')).toBe('завтра')
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

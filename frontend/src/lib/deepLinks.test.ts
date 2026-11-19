import { describe, expect, it } from 'vitest'
import { buildPatientDeepLink, parseAppRoute } from './deepLinks'

describe('parseAppRoute', () => {
  it('разбирает vetassistant://patient/{id}', () => {
    expect(parseAppRoute('vetassistant://patient/7')).toEqual({
      type: 'patient',
      patientId: 7,
    })
  })

  it('разбирает vetassistant://open?patient=7', () => {
    expect(parseAppRoute('vetassistant://open?patient=7')).toEqual({
      type: 'patient',
      patientId: 7,
    })
  })

  it('разбирает HTTPS-путь /patient/7', () => {
    expect(parseAppRoute('https://app.ai-pets.ru/patient/7')).toEqual({
      type: 'patient',
      patientId: 7,
    })
  })

  it('возвращает chat для корня и vetassistant://', () => {
    expect(parseAppRoute('https://app.ai-pets.ru/')).toEqual({ type: 'chat' })
    expect(parseAppRoute('vetassistant://open')).toEqual({ type: 'chat' })
  })

  it('отвергает некорректные ссылки', () => {
    expect(parseAppRoute('')).toBeNull()
    expect(parseAppRoute('not a url')).toBeNull()
    expect(parseAppRoute('vetassistant://patient/abc')).toEqual({
      type: 'chat',
    })
    expect(parseAppRoute('https://other.ru/patient/7')).toBeNull()
  })

  it('строит ссылку на карточку', () => {
    expect(buildPatientDeepLink(12)).toBe('vetassistant://patient/12')
  })
})

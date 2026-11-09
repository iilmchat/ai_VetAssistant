import { describe, expect, it } from 'vitest'
import {
  DEFAULT_THEME,
  parseTheme,
  readStoredTheme,
  resolveTheme,
} from './theme'

describe('тема оформления', () => {
  it('разбирает сохранённые значения и игнорирует мусор', () => {
    expect(parseTheme('light')).toBe('light')
    expect(parseTheme('dark')).toBe('dark')
    expect(parseTheme('system')).toBe('system')
    expect(parseTheme('sepia')).toBe(DEFAULT_THEME)
    expect(parseTheme(null)).toBe(DEFAULT_THEME)
  })

  it('по умолчанию использует тёмную тему без window', () => {
    expect(readStoredTheme()).toBe(DEFAULT_THEME)
  })

  it('разрешает системный режим по prefers-color-scheme', () => {
    expect(resolveTheme('system', true)).toBe('dark')
    expect(resolveTheme('system', false)).toBe('light')
  })

  it('явный выбор важнее системной настройки', () => {
    expect(resolveTheme('light', true)).toBe('light')
    expect(resolveTheme('dark', false)).toBe('dark')
  })
})

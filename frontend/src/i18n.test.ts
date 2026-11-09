import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n, {
  LANGUAGE_STORAGE_KEY,
  SUPPORTED_LANGUAGES,
  setLanguage,
} from './i18n'
import en from './locales/en.json'
import ru from './locales/ru.json'
import { formatDate, formatDateTime } from './lib/format'
import {
  ADMIN_LANGUAGE_STORAGE_KEY,
  adminI18n,
  changeAdminLanguage,
  getStoredAdminLanguage,
  resolveAdminLanguage,
  setAdminLanguage,
} from './lib/adminI18n'

function collectKeys(value: unknown, prefix = ''): string[] {
  if (typeof value !== 'object' || value === null) {
    return [prefix]
  }
  return Object.entries(value as Record<string, unknown>).flatMap(
    ([key, child]) => collectKeys(child, prefix ? `${prefix}.${key}` : key),
  )
}

describe('i18n-словари', () => {
  it('содержат одинаковый набор ключей', () => {
    expect(collectKeys(en).sort()).toEqual(collectKeys(ru).sort())
  })

  it('не содержат пустых переводов', () => {
    for (const dictionary of [ru, en]) {
      for (const value of Object.values(dictionary)) {
        expect(JSON.stringify(value).length).toBeGreaterThan(2)
      }
    }
  })

  it('поддерживают только RU и EN', () => {
    expect([...SUPPORTED_LANGUAGES]).toEqual(['ru', 'en'])
  })
})

describe('переключение языка', () => {
  afterAll(async () => {
    await i18n.changeLanguage('ru')
  })

  it('по умолчанию использует русский', () => {
    expect(i18n.t('auth.signIn')).toBe('Войти')
  })

  it('мгновенно меняет перевод на английский', async () => {
    await i18n.changeLanguage('en')
    expect(i18n.t('auth.signIn')).toBe('Sign in')
    expect(i18n.t('app.documentTitle')).toContain('AI veterinarian')
  })

  it('setLanguage переключает язык без перезагрузки', () => {
    setLanguage('ru')
    expect(i18n.language).toBe('ru')
  })
})

describe('независимый язык админ-панели (T-154.5)', () => {
  const storage = new Map<string, string>()

  beforeEach(() => {
    storage.clear()
    vi.stubGlobal('window', {
      localStorage: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => {
          storage.set(key, value)
        },
        removeItem: (key: string) => {
          storage.delete(key)
        },
      },
      addEventListener: () => {},
      removeEventListener: () => {},
    })
  })

  afterEach(async () => {
    vi.unstubAllGlobals()
    storage.clear()
    await i18n.changeLanguage('ru')
    await adminI18n.changeLanguage('ru')
  })

  it('без своего выбора использует глобальный язык', () => {
    setLanguage('en')
    expect(getStoredAdminLanguage()).toBeNull()
    expect(resolveAdminLanguage()).toBe('en')
  })

  it('переключение в админке не меняет глобальный язык и его ключ', async () => {
    setLanguage('ru')
    setAdminLanguage('en')
    await changeAdminLanguage('en')

    expect(adminI18n.t('auth.signIn')).toBe('Sign in')
    expect(i18n.language).toBe('ru')
    expect(i18n.t('auth.signIn')).toBe('Войти')
    expect(storage.get(LANGUAGE_STORAGE_KEY)).toBe('ru')
    expect(storage.get(ADMIN_LANGUAGE_STORAGE_KEY)).toBe('en')
  })

  it('собственный язык админки важнее глобального', () => {
    setAdminLanguage('en')
    setLanguage('ru')
    expect(resolveAdminLanguage()).toBe('en')
  })

  it('сброс выбора возвращает fallback на глобальный язык', async () => {
    setAdminLanguage('en')
    setAdminLanguage(null)
    setLanguage('en')

    expect(getStoredAdminLanguage()).toBeNull()
    expect(resolveAdminLanguage()).toBe('en')
    await changeAdminLanguage(resolveAdminLanguage())
    expect(adminI18n.t('auth.signIn')).toBe('Sign in')
  })

  it('игнорирует неизвестное значение в хранилище', () => {
    storage.set(ADMIN_LANGUAGE_STORAGE_KEY, 'de')
    expect(getStoredAdminLanguage()).toBeNull()
  })
})

describe('форматирование дат по языку', () => {
  it('форматирует дату в русской и английской локали', () => {
    expect(formatDate('2026-11-04', 'ru-RU')).toBe('04.11')
    expect(formatDate('2026-11-04', 'en-US')).toBe('11/04')
  })

  it('форматирует дату и время через Intl', () => {
    expect(formatDateTime('2026-11-04T10:00:00', 'ru-RU')).toContain(
      '04.11.2026',
    )
    expect(formatDateTime('2026-11-04T10:00:00', 'en-US')).toContain(
      '11/04/2026',
    )
  })
})

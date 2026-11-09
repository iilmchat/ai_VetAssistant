import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './locales/en.json'
import ru from './locales/ru.json'

/** Ключ localStorage, в котором хранится выбранный язык. */
export const LANGUAGE_STORAGE_KEY = 'vetassistant.language'

export const SUPPORTED_LANGUAGES = ['ru', 'en'] as const
export type Language = (typeof SUPPORTED_LANGUAGES)[number]

export function isLanguage(value: unknown): value is Language {
  return value === 'ru' || value === 'en'
}

/** Прочитать сохранённый язык; по умолчанию — русский. */
export function readStoredLanguage(): Language {
  if (typeof window === 'undefined') {
    return 'ru'
  }
  try {
    const value = window.localStorage.getItem(LANGUAGE_STORAGE_KEY)
    if (isLanguage(value)) {
      return value
    }
  } catch {
    // Приватный режим или недоступное хранилище — используем язык по умолчанию.
  }
  return 'ru'
}

/** Текущий язык интерфейса (нормализованный до ru/en). */
export function currentLanguage(): Language {
  return i18n.language?.startsWith('en') ? 'en' : 'ru'
}

const initialLanguage = readStoredLanguage()

void i18n.use(initReactI18next).init({
  resources: {
    ru: { translation: ru },
    en: { translation: en },
  },
  lng: initialLanguage,
  fallbackLng: 'en',
  supportedLngs: SUPPORTED_LANGUAGES,
  interpolation: {
    escapeValue: false,
  },
  returnNull: false,
})

/** Обновить атрибуты документа под текущий язык. */
function applyDocumentLanguage(language: Language): void {
  if (typeof document === 'undefined') {
    return
  }
  document.documentElement.lang = language
  document.title = i18n.t('app.documentTitle') as string
  const description = document.querySelector('meta[name="description"]')
  description?.setAttribute('content', i18n.t('app.description') as string)
}

/** Переключить язык мгновенно и сохранить выбор в localStorage. */
export function setLanguage(language: Language): void {
  void i18n.changeLanguage(language)
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language)
  } catch {
    // Хранилище недоступно — язык всё равно применится до перезагрузки.
  }
  applyDocumentLanguage(language)
}

applyDocumentLanguage(initialLanguage)

export default i18n

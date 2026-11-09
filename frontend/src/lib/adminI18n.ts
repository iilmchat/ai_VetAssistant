import i18n from 'i18next'
import { currentLanguage, isLanguage } from '../i18n'
import type { Language } from '../i18n'
import en from '../locales/en.json'
import ru from '../locales/ru.json'

/**
 * Ключ localStorage для языка админ-панели.
 *
 * Хранится отдельно от `vetassistant.language` (T-154.5): переключатель
 * в админке не должен менять язык чата, и наоборот.
 */
export const ADMIN_LANGUAGE_STORAGE_KEY = 'vetassistant.admin.language'

/** Сохранённый язык админки или `null`, если выбор не задан. */
export function getStoredAdminLanguage(): Language | null {
  if (typeof window === 'undefined') {
    return null
  }
  try {
    const value = window.localStorage.getItem(ADMIN_LANGUAGE_STORAGE_KEY)
    return isLanguage(value) ? value : null
  } catch {
    // Приватный режим или недоступное хранилище — работаем без override.
    return null
  }
}

/**
 * Запомнить язык админки. `null` сбрасывает override — админка снова
 * следует за глобальным языком интерфейса.
 */
export function setAdminLanguage(language: Language | null): void {
  try {
    if (language === null) {
      window.localStorage.removeItem(ADMIN_LANGUAGE_STORAGE_KEY)
    } else {
      window.localStorage.setItem(ADMIN_LANGUAGE_STORAGE_KEY, language)
    }
  } catch {
    // Хранилище недоступно — язык всё равно применится до перезагрузки.
  }
}

/**
 * Язык админки: собственный выбор, а если его нет — глобальный язык.
 * Глобальный `setLanguage` здесь намеренно не вызывается.
 */
export function resolveAdminLanguage(): Language {
  return getStoredAdminLanguage() ?? currentLanguage()
}

/**
 * Отдельный инстанс i18next для админ-панели.
 *
 * Не подключаем `initReactI18next`: он переключает глобальный инстанс
 * react-i18next, из-за чего админка снова влияла бы на чат. Контекст
 * экземпляра задаёт `I18nextProvider` в `AdminI18nProvider`.
 */
export const adminI18n = i18n.createInstance()

void adminI18n.init({
  resources: {
    ru: { translation: ru },
    en: { translation: en },
  },
  lng: resolveAdminLanguage(),
  fallbackLng: 'ru',
  supportedLngs: ['ru', 'en'],
  interpolation: {
    escapeValue: false,
  },
  returnNull: false,
  initAsync: false,
})

/** Применить язык только к инстансу админки. */
export async function changeAdminLanguage(language: Language): Promise<void> {
  await adminI18n.changeLanguage(language)
}

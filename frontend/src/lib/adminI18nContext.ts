import { createContext, useContext } from 'react'
import type { Language } from '../i18n'

export interface AdminI18nContextValue {
  /** Текущий язык админки (с учётом fallback на глобальный). */
  language: Language
  /** Переключить язык только в админке — глобальный язык чата не меняется. */
  chooseLanguage: (language: Language) => void
  /** Сбросить собственный выбор и снова следовать глобальному языку. */
  followGlobalLanguage: () => void
}

export const AdminI18nContext = createContext<AdminI18nContextValue | null>(
  null,
)

/** Доступ к независимому языку админ-панели. */
export function useAdminI18n(): AdminI18nContextValue {
  const value = useContext(AdminI18nContext)
  if (!value) {
    throw new Error('useAdminI18n must be used within AdminI18nProvider')
  }
  return value
}

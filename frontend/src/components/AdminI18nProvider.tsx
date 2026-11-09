import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { I18nextProvider } from 'react-i18next'
import {
  adminI18n,
  changeAdminLanguage,
  resolveAdminLanguage,
  setAdminLanguage,
} from '../lib/adminI18n'
import { AdminI18nContext } from '../lib/adminI18nContext'
import type { Language } from '../i18n'

interface AdminI18nProviderProps {
  children: ReactNode
}

/**
 * Провайдер отдельного i18n-инстанса для админки (T-154.5).
 *
 * Внутри него `useTranslation()` читает язык админки, а не глобальный.
 */
export function AdminI18nProvider({ children }: AdminI18nProviderProps) {
  const [language, setLanguageState] = useState<Language>(() =>
    resolveAdminLanguage(),
  )

  useEffect(() => {
    void changeAdminLanguage(language)
  }, [language])

  useEffect(() => {
    // Если язык поменяли в другой вкладке (глобальный или админский),
    // пересчитываем действующий язык админки.
    function syncFromStorage() {
      setLanguageState(resolveAdminLanguage())
    }
    window.addEventListener('storage', syncFromStorage)
    return () => window.removeEventListener('storage', syncFromStorage)
  }, [])

  const chooseLanguage = useCallback((next: Language) => {
    setAdminLanguage(next)
    setLanguageState(next)
  }, [])

  const followGlobalLanguage = useCallback(() => {
    setAdminLanguage(null)
    setLanguageState(resolveAdminLanguage())
  }, [])

  const value = useMemo(
    () => ({ language, chooseLanguage, followGlobalLanguage }),
    [chooseLanguage, followGlobalLanguage, language],
  )

  return (
    <AdminI18nContext.Provider value={value}>
      <I18nextProvider i18n={adminI18n}>{children}</I18nextProvider>
    </AdminI18nContext.Provider>
  )
}

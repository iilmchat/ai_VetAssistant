import { useTranslation } from 'react-i18next'
import { Globe } from 'lucide-react'
import { useAdminI18n } from '../lib/adminI18nContext'
import type { Language } from '../i18n'

const LANGUAGES: Language[] = ['ru', 'en']

interface AdminLanguageSwitcherProps {
  className?: string
}

/**
 * Переключатель RU/EN только для админ-панели (T-154.5).
 *
 * Пишет в `vetassistant.admin.language`, не трогая глобальный
 * `vetassistant.language`: чат сохраняет свой язык.
 */
export function AdminLanguageSwitcher({
  className,
}: AdminLanguageSwitcherProps) {
  const { t } = useTranslation()
  const { language: active, chooseLanguage, followGlobalLanguage } =
    useAdminI18n()

  return (
    <div
      role="group"
      aria-label={t('adminLanguage.label')}
      title={t('adminLanguage.independent')}
      className={`inline-flex items-center gap-0.5 rounded-lg border border-line bg-tint p-0.5 ${className ?? ''}`}
    >
      {LANGUAGES.map((language) => (
        <button
          key={language}
          type="button"
          onClick={() => chooseLanguage(language)}
          aria-pressed={active === language}
          title={t(`language.${language}`)}
          className={`rounded-md px-2 py-1 text-[10.5px] font-semibold uppercase tracking-wide transition-colors ${
            active === language
              ? 'bg-emerald-500 text-emerald-950'
              : 'text-ink-soft hover:bg-hover hover:text-ink'
          }`}
        >
          {language}
        </button>
      ))}
      <button
        type="button"
        onClick={followGlobalLanguage}
        aria-label={t('adminLanguage.followGlobal')}
        title={t('adminLanguage.followGlobal')}
        className="rounded-md p-1 text-ink-muted transition-colors hover:bg-hover hover:text-ink"
      >
        <Globe className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}

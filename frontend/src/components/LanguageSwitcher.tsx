import { useTranslation } from 'react-i18next'
import { currentLanguage, setLanguage } from '../i18n'
import type { Language } from '../i18n'

const LANGUAGES: Language[] = ['ru', 'en']

interface LanguageSwitcherProps {
  className?: string
}

/** Переключатель RU/EN: меняет язык мгновенно и сохраняет выбор. */
export function LanguageSwitcher({ className }: LanguageSwitcherProps) {
  const { t } = useTranslation()
  const active = currentLanguage()

  return (
    <div
      role="group"
      aria-label={t('language.label')}
      className={`inline-flex items-center gap-0.5 rounded-lg border border-white/10 bg-white/[0.03] p-0.5 ${className ?? ''}`}
    >
      {LANGUAGES.map((language) => (
        <button
          key={language}
          type="button"
          onClick={() => setLanguage(language)}
          aria-pressed={active === language}
          title={t(`language.${language}`)}
          className={`rounded-md px-2 py-1 text-[10.5px] font-semibold uppercase tracking-wide transition-colors ${
            active === language
              ? 'bg-emerald-500 text-emerald-950'
              : 'text-zinc-400 hover:bg-white/5 hover:text-zinc-200'
          }`}
        >
          {language}
        </button>
      ))}
    </div>
  )
}

import { useEffect, useState } from 'react'
import { Monitor, Moon, Sun } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { readStoredTheme, setTheme } from '../lib/theme'
import type { ThemeMode } from '../lib/theme'

interface ThemeSwitcherProps {
  className?: string
}

const MODES: { value: ThemeMode; icon: typeof Sun; labelKey: string }[] = [
  { value: 'light', icon: Sun, labelKey: 'theme.light' },
  { value: 'dark', icon: Moon, labelKey: 'theme.dark' },
  { value: 'system', icon: Monitor, labelKey: 'theme.system' },
]

/** Переключатель Light / Dark / System: применяет тему и сохраняет выбор. */
export function ThemeSwitcher({ className }: ThemeSwitcherProps) {
  const { t } = useTranslation()
  const [mode, setMode] = useState<ThemeMode>(() => readStoredTheme())

  useEffect(() => {
    function syncFromStorage() {
      setMode(readStoredTheme())
    }
    // Синхронизируем активную кнопку при смене темы в другой вкладке.
    // Саму тему применяет глобальный watchTheme() в App.
    window.addEventListener('storage', syncFromStorage)
    return () => window.removeEventListener('storage', syncFromStorage)
  }, [])

  function choose(next: ThemeMode) {
    setTheme(next)
    setMode(next)
  }

  return (
    <div
      role="group"
      aria-label={t('theme.label')}
      className={`inline-flex items-center gap-0.5 rounded-lg border border-line bg-tint p-0.5 ${className ?? ''}`}
    >
      {MODES.map(({ value, icon: Icon, labelKey }) => (
        <button
          key={value}
          type="button"
          onClick={() => choose(value)}
          aria-pressed={mode === value}
          aria-label={t(labelKey)}
          title={t(labelKey)}
          className={`rounded-md p-1.5 transition-colors ${
            mode === value
              ? 'bg-emerald-500 text-emerald-950'
              : 'text-ink-muted hover:bg-hover hover:text-ink'
          }`}
        >
          <Icon className="h-3.5 w-3.5" />
        </button>
      ))}
    </div>
  )
}

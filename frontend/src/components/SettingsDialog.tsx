import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { KeyRound, Settings, X } from 'lucide-react'
import { LanguageSwitcher } from './LanguageSwitcher'
import { TelegramLinkSection } from './TelegramLinkSection'

interface SettingsDialogProps {
  onClose: () => void
  onOpenPasswordChange: () => void
}

export function SettingsDialog({
  onClose,
  onOpenPasswordChange,
}: SettingsDialogProps) {
  const { t } = useTranslation()

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-overlay px-4 py-8 backdrop-blur-sm"
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose()
        }
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        className="relative max-h-[85vh] w-full max-w-[460px] overflow-y-auto rounded-2xl border border-line bg-panel-2 p-5 shadow-2xl shadow-black/50"
      >
        <div className="mb-5 flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-tint-2 text-ink-soft">
            <Settings className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 id="settings-title" className="text-[15px] font-semibold text-ink-strong">
              {t('settings.title')}
            </h2>
            <p className="mt-0.5 text-[11.5px] leading-4 text-ink-muted">
              {t('settings.subtitle')}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('settings.close')}
            className="rounded-lg p-1.5 text-ink-muted transition-colors hover:bg-hover hover:text-ink"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-5">
          <div className="flex items-center justify-between gap-3">
            <span className="text-[11px] font-medium uppercase tracking-wide text-ink-muted">
              {t('language.label')}
            </span>
            <LanguageSwitcher />
          </div>

          <TelegramLinkSection />

          <div className="border-t border-line pt-4">
            <div className="flex items-center gap-2.5">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-500/15 text-warn">
                <KeyRound className="h-4 w-4" />
              </div>
              <div className="min-w-0">
                <h3 className="text-[13px] font-semibold text-ink-strong">
                  {t('settings.security')}
                </h3>
                <p className="text-[11px] text-ink-muted">
                  {t('settings.securityHint')}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={onOpenPasswordChange}
              className="mt-2.5 w-full rounded-xl border border-line px-3 py-2 text-[12px] font-medium text-ink-soft transition-colors hover:bg-hover"
            >
              {t('settings.changePassword')}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

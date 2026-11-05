import { useEffect } from 'react'
import { KeyRound, Settings, X } from 'lucide-react'
import { TelegramLinkSection } from './TelegramLinkSection'

interface SettingsDialogProps {
  onClose: () => void
  onOpenPasswordChange: () => void
}

export function SettingsDialog({
  onClose,
  onOpenPasswordChange,
}: SettingsDialogProps) {
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4 py-8 backdrop-blur-sm"
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
        className="relative max-h-[85vh] w-full max-w-[460px] overflow-y-auto rounded-2xl border border-white/10 bg-[#1b1b1b] p-5 shadow-2xl shadow-black/50"
      >
        <div className="mb-5 flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/[0.06] text-zinc-300">
            <Settings className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 id="settings-title" className="text-[15px] font-semibold text-white">
              Настройки
            </h2>
            <p className="mt-0.5 text-[11.5px] leading-4 text-zinc-500">
              Привязка Telegram и безопасность аккаунта.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="rounded-lg p-1.5 text-zinc-500 transition-colors hover:bg-white/5 hover:text-zinc-200"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-5">
          <TelegramLinkSection />

          <div className="border-t border-white/10 pt-4">
            <div className="flex items-center gap-2.5">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-500/15 text-amber-300">
                <KeyRound className="h-4 w-4" />
              </div>
              <div className="min-w-0">
                <h3 className="text-[13px] font-semibold text-white">
                  Безопасность
                </h3>
                <p className="text-[11px] text-zinc-500">
                  Пароль хранится только в виде bcrypt-хэша
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={onOpenPasswordChange}
              className="mt-2.5 w-full rounded-xl border border-white/10 px-3 py-2 text-[12px] font-medium text-zinc-300 transition-colors hover:bg-white/5"
            >
              Сменить пароль
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

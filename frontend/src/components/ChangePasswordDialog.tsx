import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { KeyRound, Loader2, ShieldCheck, X } from 'lucide-react'
import { changePassword } from '../lib/api'
import { errorMessage } from '../lib/utils'

interface ChangePasswordDialogProps {
  onClose: () => void
  onPasswordChanged: () => void
}

export function ChangePasswordDialog({
  onClose,
  onPasswordChanged,
}: ChangePasswordDialogProps) {
  const { t } = useTranslation()
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && !loading) {
        onClose()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [loading, onClose])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!oldPassword || !newPassword || !confirmPassword) {
      setError(t('changePassword.fillAll'))
      return
    }
    if (newPassword.length < 8) {
      setError(t('changePassword.tooShort'))
      return
    }
    if (newPassword !== confirmPassword) {
      setError(t('changePassword.mismatch'))
      return
    }
    if (newPassword === oldPassword) {
      setError(t('changePassword.same'))
      return
    }

    setLoading(true)
    setError(null)
    try {
      await changePassword(oldPassword, newPassword, confirmPassword)
      onPasswordChanged()
    } catch (requestError) {
      setError(errorMessage(requestError))
      setLoading(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-overlay px-4 py-8 backdrop-blur-sm"
      onClick={(event) => {
        if (event.target === event.currentTarget && !loading) {
          onClose()
        }
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="change-password-title"
        className="relative w-full max-w-[420px] rounded-2xl border border-line bg-panel-2 p-5 shadow-2xl shadow-black/50"
      >
        <div className="mb-5 flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-500/15 text-accent">
            <KeyRound className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h2
              id="change-password-title"
              className="text-[15px] font-semibold text-ink-strong"
            >
              {t('changePassword.title')}
            </h2>
            <p className="mt-0.5 text-[11.5px] leading-4 text-ink-muted">
              {t('changePassword.subtitle')}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            aria-label={t('changePassword.close')}
            className="rounded-lg p-1.5 text-ink-muted transition-colors hover:bg-hover hover:text-ink disabled:opacity-50"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form
          onSubmit={(event) => void handleSubmit(event)}
          className="space-y-3.5"
        >
          <label className="block">
            <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-ink-muted">
              {t('changePassword.old')}
            </span>
            <input
              type="password"
              autoComplete="current-password"
              autoFocus
              required
              disabled={loading}
              value={oldPassword}
              onChange={(event) => setOldPassword(event.target.value)}
              placeholder={t('changePassword.oldPlaceholder')}
              className="w-full rounded-xl border border-line bg-field px-3 py-2.5 text-[14px] text-ink outline-none transition-colors placeholder:text-ink-faint focus:border-emerald-500/40 disabled:opacity-60"
            />
          </label>

          <label className="block">
            <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-ink-muted">
              {t('changePassword.new')}
            </span>
            <input
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              disabled={loading}
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              placeholder={t('changePassword.newPlaceholder')}
              className="w-full rounded-xl border border-line bg-field px-3 py-2.5 text-[14px] text-ink outline-none transition-colors placeholder:text-ink-faint focus:border-emerald-500/40 disabled:opacity-60"
            />
          </label>

          <label className="block">
            <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-ink-muted">
              {t('changePassword.confirm')}
            </span>
            <input
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              disabled={loading}
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              placeholder={t('changePassword.confirmPlaceholder')}
              className="w-full rounded-xl border border-line bg-field px-3 py-2.5 text-[14px] text-ink outline-none transition-colors placeholder:text-ink-faint focus:border-emerald-500/40 disabled:opacity-60"
            />
          </label>

          {error && (
            <div
              role="alert"
              className="rounded-xl border border-rose-500/20 bg-rose-500/[0.07] px-3 py-2.5 text-[12px] leading-5 text-danger"
            >
              {error}
            </div>
          )}

          <div className="flex gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              disabled={loading}
              className="flex-1 rounded-xl border border-line px-4 py-2.5 text-[13px] font-medium text-ink-soft transition-colors hover:bg-hover disabled:opacity-50"
            >
              {t('changePassword.cancel')}
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-emerald-500 px-4 py-2.5 text-[13px] font-semibold text-emerald-950 transition-colors hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading && <Loader2 className="h-4 w-4 animate-spin" />}
              {loading
                ? t('changePassword.saving')
                : t('changePassword.submit')}
            </button>
          </div>
        </form>

        <p className="mt-4 flex items-start gap-2 text-[10.5px] leading-4 text-ink-faint">
          <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {t('changePassword.hint')}
        </p>
      </div>
    </div>
  )
}

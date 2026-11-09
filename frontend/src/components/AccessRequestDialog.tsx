import { useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, Loader2, Mail, MessageSquare, X } from 'lucide-react'
import { requestAccess } from '../lib/api'
import { errorMessage } from '../lib/utils'

interface AccessRequestDialogProps {
  initialEmail?: string
  onClose: () => void
}

export function AccessRequestDialog({
  initialEmail = '',
  onClose,
}: AccessRequestDialogProps) {
  const { t } = useTranslation()
  const [email, setEmail] = useState(initialEmail)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [sent, setSent] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const normalizedEmail = email.trim()
    const normalizedReason = reason.trim()
    if (!normalizedEmail || !normalizedReason) {
      setError(t('accessRequest.fillFields'))
      return
    }

    setLoading(true)
    setError(null)
    try {
      await requestAccess(normalizedEmail, normalizedReason)
      setSent(true)
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4 py-8 backdrop-blur-sm"
      onClick={(event) => {
        if (event.target === event.currentTarget && !loading) {
          onClose()
        }
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="access-request-title"
        className="relative w-full max-w-[440px] rounded-2xl border border-white/10 bg-[#1b1b1b] p-5 shadow-2xl shadow-black/50"
      >
        <div className="mb-5 flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-300">
            <Mail className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h2
              id="access-request-title"
              className="text-[15px] font-semibold text-white"
            >
              {t('accessRequest.title')}
            </h2>
            <p className="mt-0.5 text-[11.5px] leading-4 text-zinc-500">
              {t('accessRequest.subtitle')}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            aria-label={t('accessRequest.close')}
            className="rounded-lg p-1.5 text-zinc-500 transition-colors hover:bg-white/5 hover:text-zinc-200 disabled:opacity-50"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {sent ? (
          <div className="space-y-4">
            <div
              role="status"
              className="flex items-start gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.08] px-3 py-3 text-[12.5px] leading-5 text-emerald-300"
            >
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{t('accessRequest.sent')}</span>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="w-full rounded-xl bg-emerald-500 px-4 py-2.5 text-[13px] font-semibold text-emerald-950 transition-colors hover:bg-emerald-400"
            >
              {t('accessRequest.close')}
            </button>
          </div>
        ) : (
          <form
            onSubmit={(event) => void handleSubmit(event)}
            className="space-y-3.5"
          >
            <label className="block">
              <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-zinc-500">
                {t('accessRequest.email')}
              </span>
              <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-black/25 px-3 py-2.5 focus-within:border-emerald-500/40">
                <Mail className="h-4 w-4 shrink-0 text-zinc-500" />
                <input
                  type="email"
                  autoComplete="email"
                  required
                  autoFocus
                  disabled={loading}
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="you@example.com"
                  className="w-full bg-transparent text-[14px] text-zinc-100 outline-none placeholder:text-zinc-600 disabled:opacity-60"
                />
              </div>
            </label>

            <label className="block">
              <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-zinc-500">
                {t('accessRequest.reason')}
              </span>
              <div className="flex items-start gap-2 rounded-xl border border-white/10 bg-black/25 px-3 py-2.5 focus-within:border-emerald-500/40">
                <MessageSquare className="mt-0.5 h-4 w-4 shrink-0 text-zinc-500" />
                <textarea
                  required
                  rows={4}
                  maxLength={1000}
                  disabled={loading}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder={t('accessRequest.reasonPlaceholder')}
                  className="w-full resize-none bg-transparent text-[14px] leading-5 text-zinc-100 outline-none placeholder:text-zinc-600 disabled:opacity-60"
                />
              </div>
            </label>

            {error && (
              <div
                role="alert"
                className="rounded-xl border border-rose-500/20 bg-rose-500/[0.07] px-3 py-2.5 text-[12px] leading-5 text-rose-300"
              >
                {error}
              </div>
            )}

            <div className="flex gap-2 pt-1">
              <button
                type="button"
                onClick={onClose}
                disabled={loading}
                className="flex-1 rounded-xl border border-white/10 px-4 py-2.5 text-[13px] font-medium text-zinc-300 transition-colors hover:bg-white/5 disabled:opacity-50"
              >
                {t('accessRequest.cancel')}
              </button>
              <button
                type="submit"
                disabled={loading}
                className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-emerald-500 px-4 py-2.5 text-[13px] font-semibold text-emerald-950 transition-colors hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                {loading
                  ? t('accessRequest.sending')
                  : t('accessRequest.submit')}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

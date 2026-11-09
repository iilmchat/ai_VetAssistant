import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Check,
  ClipboardCopy,
  Link2,
  Loader2,
  MessageCircle,
  ShieldCheck,
  Unlink,
} from 'lucide-react'
import {
  createTelegramLinkCode,
  fetchTelegramLink,
  unlinkTelegram,
} from '../lib/api'
import {
  codeSecondsLeft,
  formatCountdown,
  formatTelegramCode,
} from '../lib/telegram'
import { errorMessage } from '../lib/utils'
import type { TelegramLinkCode, TelegramLinkStatus } from '../types'

function formatLinkedAt(value: string | null, locale: string): string | null {
  if (!value) {
    return null
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return null
  }
  return new Intl.DateTimeFormat(locale, {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(date)
}

export function TelegramLinkSection() {
  const { t, i18n } = useTranslation()
  const [status, setStatus] = useState<TelegramLinkStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [code, setCode] = useState<TelegramLinkCode | null>(null)
  const [remaining, setRemaining] = useState(0)
  const [creating, setCreating] = useState(false)
  const [unlinking, setUnlinking] = useState(false)
  const [confirmingUnlink, setConfirmingUnlink] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    let active = true

    void fetchTelegramLink()
      .then((next) => {
        if (!active) {
          return
        }
        setStatus(next)
        setError(null)
      })
      .catch((requestError: unknown) => {
        if (active) {
          setError(errorMessage(requestError))
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false)
        }
      })

    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (!code) {
      return
    }
    const interval = window.setInterval(() => {
      setRemaining(codeSecondsLeft(code.expires_at))
    }, 1000)
    return () => window.clearInterval(interval)
  }, [code])

  async function handleCreate() {
    setCreating(true)
    setError(null)
    setCopied(false)
    try {
      const next = await createTelegramLinkCode()
      setCode(next)
      setRemaining(codeSecondsLeft(next.expires_at))
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setCreating(false)
    }
  }

  async function handleUnlink() {
    if (!confirmingUnlink) {
      setConfirmingUnlink(true)
      return
    }

    setUnlinking(true)
    setError(null)
    try {
      await unlinkTelegram()
      setStatus((previous) =>
        previous
          ? { ...previous, linked: false, telegram_id: null, linked_at: null }
          : previous,
      )
      setCode(null)
      setConfirmingUnlink(false)
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setUnlinking(false)
    }
  }

  async function handleCopy() {
    if (!code) {
      return
    }
    if (!navigator.clipboard) {
      setError(t('telegram.copyError'))
      return
    }
    try {
      await navigator.clipboard.writeText(code.code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setError(t('telegram.copyError'))
    }
  }

  const linkedAt = formatLinkedAt(status?.linked_at ?? null, i18n.language)

  return (
    <section aria-labelledby="telegram-link-title" className="space-y-3">
      <div className="flex items-center gap-2.5">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-sky-500/15 text-sky-text">
          <MessageCircle className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <h3
            id="telegram-link-title"
            className="text-[13px] font-semibold text-ink-strong"
          >
            Telegram
          </h3>
          <p className="text-[11px] text-ink-muted">
            {t('telegram.subtitle')}
          </p>
        </div>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-[12px] text-ink-muted">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          {t('telegram.checking')}
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="rounded-xl border border-rose-500/20 bg-rose-500/[0.07] px-3 py-2.5 text-[12px] leading-5 text-danger"
        >
          {error}
        </div>
      )}

      {!loading && status?.linked && (
        <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/[0.06] p-3">
          <p className="flex items-center gap-1.5 text-[12.5px] font-medium text-accent">
            <ShieldCheck className="h-4 w-4" />
            {t('telegram.linked')}
          </p>
          <p className="mt-1 text-[11.5px] text-ink-soft">
            {status.email ?? t('telegram.webAccount')}
            {status.telegram_id !== null && (
              <span className="text-ink-faint"> · ID {status.telegram_id}</span>
            )}
          </p>
          {linkedAt && (
            <p className="mt-0.5 text-[10.5px] text-ink-faint">
              {t('telegram.since', { date: linkedAt })}
            </p>
          )}

          <div className="mt-2.5 flex gap-2">
            {!confirmingUnlink ? (
              <button
                type="button"
                onClick={() => void handleUnlink()}
                className="inline-flex items-center gap-1.5 rounded-lg border border-rose-500/25 bg-rose-500/[0.08] px-3 py-1.5 text-[11.5px] font-medium text-danger transition-colors hover:bg-rose-500/15"
              >
                <Unlink className="h-3.5 w-3.5" />
                {t('telegram.unlink')}
              </button>
            ) : (
              <>
                <button
                  type="button"
                  onClick={() => void handleUnlink()}
                  disabled={unlinking}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-rose-500 px-3 py-1.5 text-[11.5px] font-semibold text-rose-950 transition-colors hover:bg-rose-400 disabled:opacity-60"
                >
                  {unlinking && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  {t('telegram.confirmUnlink')}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmingUnlink(false)}
                  disabled={unlinking}
                  className="rounded-lg border border-line px-3 py-1.5 text-[11.5px] text-ink-soft transition-colors hover:bg-hover disabled:opacity-50"
                >
                  {t('telegram.cancel')}
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {!loading && status && !status.linked && (
        <div className="space-y-2.5">
          <p className="text-[12px] leading-5 text-ink-soft">
            {t('telegram.description')}
          </p>

          {!code && (
            <button
              type="button"
              onClick={() => void handleCreate()}
              disabled={creating}
              className="inline-flex items-center gap-2 rounded-xl bg-sky-500 px-3.5 py-2 text-[12px] font-semibold text-sky-950 transition-colors hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {creating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Link2 className="h-4 w-4" />
              )}
              {creating ? t('telegram.creating') : t('telegram.link')}
            </button>
          )}

          {code && (
            <div className="rounded-xl border border-line bg-field p-3">
              {remaining > 0 ? (
                <>
                  <p className="text-[10.5px] font-medium uppercase tracking-wide text-ink-muted">
                    {t('telegram.codeLabel')}
                  </p>
                  <div className="mt-1 flex items-center gap-2">
                    <code className="select-all rounded-lg bg-tint-2 px-2.5 py-1.5 font-mono text-[20px] font-semibold tracking-[0.12em] text-ink-strong">
                      {formatTelegramCode(code.code)}
                    </code>
                    <button
                      type="button"
                      onClick={() => void handleCopy()}
                      aria-label={t('telegram.copyCode')}
                      className="rounded-lg border border-line p-1.5 text-ink-soft transition-colors hover:bg-hover hover:text-ink"
                    >
                      {copied ? (
                        <Check className="h-3.5 w-3.5 text-accent-icon" />
                      ) : (
                        <ClipboardCopy className="h-3.5 w-3.5" />
                      )}
                    </button>
                  </div>
                  <p className="mt-1.5 text-[11px] text-ink-muted">
                    {t('telegram.remaining', {
                      time: formatCountdown(remaining),
                    })}
                  </p>
                  <p className="mt-2 text-[11.5px] leading-5 text-ink-soft">
                    {code.instructions}
                  </p>
                </>
              ) : (
                <div className="space-y-2">
                  <p className="text-[12px] text-warn">
                    {t('telegram.expired')}
                  </p>
                  <button
                    type="button"
                    onClick={() => void handleCreate()}
                    disabled={creating}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-sky-500 px-3 py-1.5 text-[11.5px] font-semibold text-sky-950 transition-colors hover:bg-sky-400 disabled:opacity-60"
                  >
                    {creating && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                    {t('telegram.newCode')}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

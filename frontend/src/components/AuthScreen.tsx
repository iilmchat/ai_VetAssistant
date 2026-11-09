import { useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, Lock, Mail, PawPrint, ShieldCheck, UserPlus } from 'lucide-react'
import type { AuthSession } from '../lib/auth'
import { login } from '../lib/api'
import { isAccessRequestMode } from '../lib/access'
import { errorMessage } from '../lib/utils'
import { AccessRequestDialog } from './AccessRequestDialog'
import { LanguageSwitcher } from './LanguageSwitcher'

interface AuthScreenProps {
  onAuthenticated: (session: AuthSession) => void
  notice?: string | null
}

export function AuthScreen({ onAuthenticated, notice }: AuthScreenProps) {
  const { t } = useTranslation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [accessDialogOpen, setAccessDialogOpen] = useState(() =>
    isAccessRequestMode(window.location.search),
  )

  function closeAccessDialog() {
    setAccessDialogOpen(false)
    const url = new URL(window.location.href)
    if (url.searchParams.get('mode') === 'request') {
      url.searchParams.delete('mode')
      window.history.replaceState(
        {},
        '',
        `${url.pathname}${url.search}${url.hash}`,
      )
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const normalizedEmail = email.trim()
    if (!normalizedEmail || !password) {
      setError(t('auth.fillCredentials'))
      return
    }

    setLoading(true)
    setError(null)
    try {
      const session = await login(normalizedEmail, password)
      onAuthenticated(session)
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden bg-[#141414] px-4 py-10 text-zinc-100">
      <div className="pointer-events-none absolute -top-40 left-1/2 h-96 w-[42rem] -translate-x-1/2 rounded-full bg-emerald-500/10 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-52 right-[-10rem] h-96 w-96 rounded-full bg-teal-500/[0.07] blur-3xl" />

      <div className="absolute right-4 top-4 z-10 sm:right-6 sm:top-6">
        <LanguageSwitcher />
      </div>

      <div className="relative w-full max-w-[420px]">
        <div className="mb-7 flex flex-col items-center text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-400 to-teal-600 text-zinc-950 shadow-[0_12px_36px_rgba(16,185,129,0.35)]">
            <PawPrint className="h-7 w-7" strokeWidth={2.4} />
          </div>
          <h1 className="mt-4 text-2xl font-semibold tracking-tight text-white">
            VetAssistant
          </h1>
          <p className="mt-1 text-[13px] text-zinc-500">
            {t('auth.tagline')}
          </p>
        </div>

        <div className="rounded-2xl border border-white/10 bg-[#1b1b1b]/95 p-5 shadow-2xl shadow-black/40 backdrop-blur">
          {notice && (
            <div
              role="status"
              className="mb-4 flex items-start gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.08] px-3 py-2.5 text-[12px] leading-5 text-emerald-300"
            >
              <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{notice}</span>
            </div>
          )}

          <div className="mb-5">
            <h2 className="text-[15px] font-semibold text-white">
              {t('auth.login')}
            </h2>
            <p className="mt-0.5 text-[11.5px] text-zinc-500">
              {t('auth.inviteOnly')}
            </p>
          </div>

          <form
            onSubmit={(event) => void handleSubmit(event)}
            className="space-y-3.5"
          >
            <label className="block">
              <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-zinc-500">
                {t('auth.email')}
              </span>
              <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-black/25 px-3 py-2.5 focus-within:border-emerald-500/40">
                <Mail className="h-4 w-4 shrink-0 text-zinc-500" />
                <input
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="you@example.com"
                  className="w-full bg-transparent text-[14px] text-zinc-100 outline-none placeholder:text-zinc-600"
                />
              </div>
            </label>

            <label className="block">
              <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-zinc-500">
                {t('auth.password')}
              </span>
              <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-black/25 px-3 py-2.5 focus-within:border-emerald-500/40">
                <Lock className="h-4 w-4 shrink-0 text-zinc-500" />
                <input
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder={t('auth.passwordPlaceholder')}
                  className="w-full bg-transparent text-[14px] text-zinc-100 outline-none placeholder:text-zinc-600"
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

            <button
              type="submit"
              disabled={loading}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-500 px-4 py-2.5 text-[13.5px] font-semibold text-emerald-950 transition-colors hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading && <Loader2 className="h-4 w-4 animate-spin" />}
              {t('auth.signIn')}
            </button>
          </form>

          <div className="mt-4 border-t border-white/10 pt-4 text-center">
            <p className="text-[11.5px] text-zinc-500">
              {t('auth.noAccount')}
            </p>
            <button
              type="button"
              onClick={() => setAccessDialogOpen(true)}
              className="mt-1.5 inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[12.5px] font-medium text-emerald-300 transition-colors hover:bg-emerald-500/10 hover:text-emerald-200"
            >
              <UserPlus className="h-3.5 w-3.5" />
              {t('auth.requestAccess')}
            </button>
          </div>

          <p className="mt-4 flex items-start gap-2 text-[10.5px] leading-4 text-zinc-600">
            <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {t('auth.privacy')}
          </p>
        </div>
      </div>

      {accessDialogOpen && (
        <AccessRequestDialog
          initialEmail={email.trim()}
          onClose={closeAccessDialog}
        />
      )}
    </div>
  )
}

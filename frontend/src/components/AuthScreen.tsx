import { useState } from 'react'
import type { FormEvent } from 'react'
import { Loader2, Lock, Mail, PawPrint, ShieldCheck } from 'lucide-react'
import type { AuthSession } from '../lib/auth'
import { login, register } from '../lib/api'
import { errorMessage } from '../lib/utils'

type AuthMode = 'login' | 'register'

interface AuthScreenProps {
  onAuthenticated: (session: AuthSession) => void
}

export function AuthScreen({ onAuthenticated }: AuthScreenProps) {
  const [mode, setMode] = useState<AuthMode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const isRegister = mode === 'register'

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const normalizedEmail = email.trim()
    if (!normalizedEmail || !password) {
      setError('Введите email и пароль.')
      return
    }
    if (isRegister && password.length < 8) {
      setError('Пароль должен содержать минимум 8 символов.')
      return
    }

    setLoading(true)
    setError(null)
    try {
      const session = isRegister
        ? await register(normalizedEmail, password)
        : await login(normalizedEmail, password)
      onAuthenticated(session)
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setLoading(false)
    }
  }

  function switchMode(next: AuthMode) {
    setMode(next)
    setError(null)
    setPassword('')
  }

  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden bg-[#141414] px-4 py-10 text-zinc-100">
      <div className="pointer-events-none absolute -top-40 left-1/2 h-96 w-[42rem] -translate-x-1/2 rounded-full bg-emerald-500/10 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-52 right-[-10rem] h-96 w-96 rounded-full bg-teal-500/[0.07] blur-3xl" />

      <div className="relative w-full max-w-[420px]">
        <div className="mb-7 flex flex-col items-center text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-400 to-teal-600 text-zinc-950 shadow-[0_12px_36px_rgba(16,185,129,0.35)]">
            <PawPrint className="h-7 w-7" strokeWidth={2.4} />
          </div>
          <h1 className="mt-4 text-2xl font-semibold tracking-tight text-white">
            VetAssistant
          </h1>
          <p className="mt-1 text-[13px] text-zinc-500">
            Личный ветеринарный ассистент для ваших питомцев
          </p>
        </div>

        <div className="rounded-2xl border border-white/10 bg-[#1b1b1b]/95 p-5 shadow-2xl shadow-black/40 backdrop-blur">
          <div className="mb-5 grid grid-cols-2 gap-1 rounded-xl border border-white/[0.06] bg-black/25 p-1">
            <button
              type="button"
              onClick={() => switchMode('login')}
              className={`rounded-lg px-3 py-2 text-[13px] font-medium transition-colors ${
                !isRegister
                  ? 'bg-white/10 text-white'
                  : 'text-zinc-500 hover:text-zinc-300'
              }`}
            >
              Вход
            </button>
            <button
              type="button"
              onClick={() => switchMode('register')}
              className={`rounded-lg px-3 py-2 text-[13px] font-medium transition-colors ${
                isRegister
                  ? 'bg-white/10 text-white'
                  : 'text-zinc-500 hover:text-zinc-300'
              }`}
            >
              Регистрация
            </button>
          </div>

          <form onSubmit={(event) => void handleSubmit(event)} className="space-y-3.5">
            <label className="block">
              <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-zinc-500">
                Email
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
                Пароль
              </span>
              <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-black/25 px-3 py-2.5 focus-within:border-emerald-500/40">
                <Lock className="h-4 w-4 shrink-0 text-zinc-500" />
                <input
                  type="password"
                  autoComplete={isRegister ? 'new-password' : 'current-password'}
                  required
                  minLength={isRegister ? 8 : undefined}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder={isRegister ? 'Минимум 8 символов' : 'Ваш пароль'}
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
              {isRegister ? 'Создать аккаунт' : 'Войти'}
            </button>
          </form>

          <p className="mt-4 flex items-start gap-2 text-[10.5px] leading-4 text-zinc-600">
            <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            Данные питомцев, записи и напоминания видны только вам. Пароль
            хранится в виде bcrypt-хэша.
          </p>
        </div>
      </div>
    </div>
  )
}

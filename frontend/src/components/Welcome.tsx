import { useTranslation } from 'react-i18next'
import {
  Activity,
  ArrowUpRight,
  BookOpen,
  CalendarPlus,
  PawPrint,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

interface WelcomeProps {
  onSuggestion: (text: string) => void
}

type SuggestionKey = 'catAppetite' | 'dogLimping' | 'bookAppointment' | 'vaccination'

interface Suggestion {
  icon: LucideIcon
  key: SuggestionKey
}

const suggestions: Suggestion[] = [
  { icon: PawPrint, key: 'catAppetite' },
  { icon: Activity, key: 'dogLimping' },
  { icon: CalendarPlus, key: 'bookAppointment' },
  { icon: BookOpen, key: 'vaccination' },
]

export function Welcome({ onSuggestion }: WelcomeProps) {
  const { t } = useTranslation()

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col items-center px-1 pb-6 pt-6 text-center sm:pt-14">
      <div className="relative">
        <div className="absolute inset-0 -z-10 rounded-full bg-emerald-500/20 blur-2xl" />
        <div className="flex h-16 w-16 items-center justify-center rounded-[1.4rem] bg-gradient-to-br from-emerald-400 via-emerald-500 to-teal-600 text-zinc-950 shadow-[0_18px_45px_rgba(16,185,129,0.3)] ring-1 ring-line-strong">
          <PawPrint className="h-8 w-8" strokeWidth={2.2} />
        </div>
      </div>

      <h1 className="mt-6 text-balance text-2xl font-semibold tracking-[-0.02em] text-ink-strong sm:text-3xl">
        {t('welcome.title')}
      </h1>
      <p className="mt-2.5 max-w-lg text-pretty text-[13.5px] leading-6 text-ink-soft sm:text-sm">
        {t('welcome.description')}
      </p>

      <div className="mt-4 flex flex-wrap items-center justify-center gap-1.5">
        <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/15 bg-emerald-500/[0.07] px-2.5 py-1 text-[10px] font-medium text-accent">
          <Sparkles className="h-3 w-3" />
          {t('welcome.localModel')}
        </span>
        <span className="inline-flex items-center gap-1 rounded-full border border-line bg-tint px-2.5 py-1 text-[10px] font-medium text-ink-soft">
          <BookOpen className="h-3 w-3" />
          RAG
        </span>
        <span className="inline-flex items-center gap-1 rounded-full border border-line bg-tint px-2.5 py-1 text-[10px] font-medium text-ink-soft">
          <CalendarPlus className="h-3 w-3" />
          Function Calling
        </span>
      </div>

      <div className="mt-8 grid w-full gap-2.5 text-left sm:grid-cols-2">
        {suggestions.map((suggestion) => {
          const Icon = suggestion.icon
          const base = `welcome.suggestions.${suggestion.key}`
          return (
            <button
              key={suggestion.key}
              type="button"
              onClick={() => onSuggestion(t(`${base}.prompt`))}
              className="group flex items-start gap-3 rounded-2xl border border-line-soft bg-tint p-3.5 text-left transition-all hover:-translate-y-0.5 hover:border-emerald-500/30 hover:bg-emerald-500/[0.05]"
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-line-soft bg-tint-2 text-ink-soft transition-colors group-hover:text-accent">
                <Icon className="h-4 w-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[12.5px] font-medium leading-5 text-ink">
                  {t(`${base}.title`)}
                </span>
                <span className="mt-0.5 block text-[10.5px] text-ink-muted">
                  {t(`${base}.subtitle`)}
                </span>
              </span>
              <ArrowUpRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-faint transition-colors group-hover:text-accent-icon" />
            </button>
          )
        })}
      </div>

      <div className="mt-7 flex max-w-lg items-start gap-2 rounded-xl border border-amber-500/10 bg-amber-500/[0.035] px-3 py-2.5 text-left text-[10.5px] leading-4 text-ink-muted">
        <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warn-icon/70" />
        <span>{t('welcome.disclaimer')}</span>
      </div>
    </div>
  )
}

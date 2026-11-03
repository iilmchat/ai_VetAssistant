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

interface Suggestion {
  icon: LucideIcon
  title: string
  subtitle: string
  prompt: string
}

const suggestions: Suggestion[] = [
  {
    icon: PawPrint,
    title: 'Кот не ест второй день',
    subtitle: 'Оценить аппетит и состояние',
    prompt: 'Кот не ест второй день. Что делать и когда ехать к врачу?',
  },
  {
    icon: Activity,
    title: 'Собака хромает после прогулки',
    subtitle: 'Проверить возможные причины',
    prompt:
      'Собака хромает на заднюю лапу после прогулки. Как оценить состояние?',
  },
  {
    icon: CalendarPlus,
    title: 'Запиши питомца на приём',
    subtitle: 'Function Calling создаст запись',
    prompt: 'Запиши моего кота Мурзика на приём завтра в 10:00.',
  },
  {
    icon: BookOpen,
    title: 'Что проверить перед прививкой?',
    subtitle: 'Подготовка к вакцинации',
    prompt: 'Что нужно проверить и сделать перед прививкой собаки?',
  },
]

export function Welcome({ onSuggestion }: WelcomeProps) {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col items-center px-1 pb-6 pt-6 text-center sm:pt-14">
      <div className="relative">
        <div className="absolute inset-0 -z-10 rounded-full bg-emerald-500/20 blur-2xl" />
        <div className="flex h-16 w-16 items-center justify-center rounded-[1.4rem] bg-gradient-to-br from-emerald-400 via-emerald-500 to-teal-600 text-zinc-950 shadow-[0_18px_45px_rgba(16,185,129,0.3)] ring-1 ring-white/20">
          <PawPrint className="h-8 w-8" strokeWidth={2.2} />
        </div>
      </div>

      <h1 className="mt-6 text-balance text-2xl font-semibold tracking-[-0.02em] text-white sm:text-3xl">
        Чем помочь вашему питомцу?
      </h1>
      <p className="mt-2.5 max-w-lg text-pretty text-[13.5px] leading-6 text-zinc-400 sm:text-sm">
        Опишите симптомы или задайте вопрос. Я опираюсь на базу знаний MSD Vet
        Manual, помню контекст беседы и могу записать питомца на приём.
      </p>

      <div className="mt-4 flex flex-wrap items-center justify-center gap-1.5">
        <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/15 bg-emerald-500/[0.07] px-2.5 py-1 text-[10px] font-medium text-emerald-300">
          <Sparkles className="h-3 w-3" />
          Локальная модель
        </span>
        <span className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[10px] font-medium text-zinc-400">
          <BookOpen className="h-3 w-3" />
          RAG
        </span>
        <span className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[10px] font-medium text-zinc-400">
          <CalendarPlus className="h-3 w-3" />
          Function Calling
        </span>
      </div>

      <div className="mt-8 grid w-full gap-2.5 text-left sm:grid-cols-2">
        {suggestions.map((suggestion) => {
          const Icon = suggestion.icon
          return (
            <button
              key={suggestion.title}
              type="button"
              onClick={() => onSuggestion(suggestion.prompt)}
              className="group flex items-start gap-3 rounded-2xl border border-white/[0.08] bg-white/[0.025] p-3.5 text-left transition-all hover:-translate-y-0.5 hover:border-emerald-500/30 hover:bg-emerald-500/[0.05]"
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/[0.07] bg-white/[0.04] text-zinc-400 transition-colors group-hover:text-emerald-300">
                <Icon className="h-4 w-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[12.5px] font-medium leading-5 text-zinc-200">
                  {suggestion.title}
                </span>
                <span className="mt-0.5 block text-[10.5px] text-zinc-500">
                  {suggestion.subtitle}
                </span>
              </span>
              <ArrowUpRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-zinc-600 transition-colors group-hover:text-emerald-400" />
            </button>
          )
        })}
      </div>

      <div className="mt-7 flex max-w-lg items-start gap-2 rounded-xl border border-amber-500/10 bg-amber-500/[0.035] px-3 py-2.5 text-left text-[10.5px] leading-4 text-zinc-500">
        <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400/70" />
        <span>
          Ассистент не ставит окончательный диагноз и не заменяет осмотр
          врача. При затруднённом дыхании, судорогах или отравлении — срочно в
          клинику.
        </span>
      </div>
    </div>
  )
}

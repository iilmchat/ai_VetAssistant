import {
  BellRing,
  CalendarCheck2,
  Check,
  Wrench,
} from 'lucide-react'
import type { ToolCall } from '../types'
import { presentToolCall } from '../lib/tools'
import type { ToolKind, ToolTone } from '../lib/tools'

const toneClasses: Record<ToolTone, string> = {
  success: 'border-emerald-500/25 bg-emerald-500/[0.08]',
  warning: 'border-amber-500/25 bg-amber-500/[0.07]',
  neutral: 'border-white/10 bg-white/[0.03]',
}

const iconClasses: Record<ToolTone, string> = {
  success: 'bg-emerald-500/15 text-emerald-300',
  warning: 'bg-amber-500/15 text-amber-300',
  neutral: 'bg-white/[0.06] text-zinc-300',
}

const titleClasses: Record<ToolTone, string> = {
  success: 'text-emerald-200',
  warning: 'text-amber-200',
  neutral: 'text-zinc-200',
}

function ToolIcon({ kind }: { kind: ToolKind }) {
  if (kind === 'calendar') {
    return <CalendarCheck2 className="h-4 w-4" />
  }
  if (kind === 'bell') {
    return <BellRing className="h-4 w-4" />
  }
  return <Wrench className="h-4 w-4" />
}

export function ToolCallBadge({ call }: { call: ToolCall }) {
  const presentation = presentToolCall(call)

  return (
    <div
      className={`flex items-start gap-3 rounded-xl border px-3.5 py-3 ${toneClasses[presentation.tone]}`}
    >
      <div
        className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${iconClasses[presentation.tone]}`}
      >
        <ToolIcon kind={presentation.kind} />
      </div>
      <div className="min-w-0 flex-1">
        <p
          className={`text-[12.5px] font-semibold ${titleClasses[presentation.tone]}`}
        >
          {presentation.title}
        </p>
        <p className="mt-0.5 break-words text-[11.5px] leading-5 text-zinc-400">
          {presentation.details}
        </p>
      </div>
      <Check className="mt-1 h-3.5 w-3.5 shrink-0 text-emerald-400/80" />
    </div>
  )
}

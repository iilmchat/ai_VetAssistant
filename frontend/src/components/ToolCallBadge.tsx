import { useTranslation } from 'react-i18next'
import {
  BellRing,
  CalendarCheck2,
  Check,
  PawPrint,
  Wrench,
} from 'lucide-react'
import type { ToolCall } from '../types'
import { presentToolCall } from '../lib/tools'
import type { ToolKind, ToolTone, Translate } from '../lib/tools'

const toneClasses: Record<ToolTone, string> = {
  success: 'border-emerald-500/25 bg-emerald-500/[0.08]',
  warning: 'border-amber-500/25 bg-amber-500/[0.07]',
  neutral: 'border-line bg-tint',
}

const iconClasses: Record<ToolTone, string> = {
  success: 'bg-emerald-500/15 text-accent',
  warning: 'bg-amber-500/15 text-warn',
  neutral: 'bg-tint-2 text-ink-soft',
}

const titleClasses: Record<ToolTone, string> = {
  success: 'text-accent-strong',
  warning: 'text-warn-strong',
  neutral: 'text-ink',
}

function ToolIcon({ kind }: { kind: ToolKind }) {
  if (kind === 'calendar') {
    return <CalendarCheck2 className="h-4 w-4" />
  }
  if (kind === 'bell') {
    return <BellRing className="h-4 w-4" />
  }
  if (kind === 'paw') {
    return <PawPrint className="h-4 w-4" />
  }
  return <Wrench className="h-4 w-4" />
}

export function ToolCallBadge({ call }: { call: ToolCall }) {
  const { t } = useTranslation()
  const presentation = presentToolCall(call, t as unknown as Translate)

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
        <p className="mt-0.5 break-words text-[11.5px] leading-5 text-ink-soft">
          {presentation.details}
        </p>
      </div>
      <Check className="mt-1 h-3.5 w-3.5 shrink-0 text-accent-icon/80" />
    </div>
  )
}

import type { ReactNode } from 'react'

interface ToggleProps {
  icon: ReactNode
  label: string
  description: string
  checked: boolean
  onChange: (value: boolean) => void
}

export function Toggle({
  icon,
  label,
  description,
  checked,
  onChange,
}: ToggleProps) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-line-soft bg-tint p-3">
      <div className="mt-0.5 text-ink-soft">{icon}</div>
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-medium text-ink">{label}</p>
        <p className="mt-0.5 text-[11px] leading-4 text-ink-muted">
          {description}
        </p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 focus-visible:ring-offset-2 focus-visible:ring-offset-panel ${
          checked ? 'bg-emerald-500' : 'bg-track'
        }`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 ${
            checked ? 'translate-x-[18px]' : 'translate-x-0.5'
          }`}
        />
      </button>
    </div>
  )
}

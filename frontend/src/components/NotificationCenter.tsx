import { useEffect, useState } from 'react'
import { Bell, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { AppRoute } from '../lib/deepLinks'
import {
  dismissNotification,
  getNotifications,
  subscribeNotifications,
} from '../lib/notifications'

interface NotificationCenterProps {
  onOpenRoute: (route: AppRoute) => void
}

/** Всплывающие уведомления внутри приложения (T-184). */
export function NotificationCenter({ onOpenRoute }: NotificationCenterProps) {
  const { t } = useTranslation()
  const [items, setItems] = useState(getNotifications)

  useEffect(() => subscribeNotifications(setItems), [])

  useEffect(() => {
    if (items.length === 0) {
      return
    }
    const first = items[0]
    const timer = window.setTimeout(() => dismissNotification(first.id), 8000)
    return () => window.clearTimeout(timer)
  }, [items])

  if (items.length === 0) {
    return null
  }

  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed right-3 top-3 z-[60] flex w-[min(340px,calc(100vw-24px))] flex-col gap-2"
    >
      {items.map((item) => (
        <div
          key={item.id}
          className="pointer-events-auto flex items-start gap-3 rounded-xl border border-emerald-500/25 bg-panel-2/95 p-3 shadow-xl backdrop-blur"
        >
          <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-emerald-500/15 text-accent">
            <Bell className="h-3.5 w-3.5" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[12px] font-semibold text-ink-strong">
              {item.title}
            </p>
            {item.body && (
              <p className="mt-0.5 break-words text-[11px] leading-4 text-ink-soft">
                {item.body}
              </p>
            )}
            {item.action && (
              <button
                type="button"
                onClick={() => {
                  onOpenRoute(item.action!.route)
                  dismissNotification(item.id)
                }}
                className="mt-1.5 text-[11px] font-medium text-accent hover:underline"
              >
                {item.action.label}
              </button>
            )}
          </div>
          <button
            type="button"
            onClick={() => dismissNotification(item.id)}
            aria-label={t('notification.dismiss')}
            className="rounded p-0.5 text-ink-muted transition-colors hover:text-ink"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </div>
  )
}

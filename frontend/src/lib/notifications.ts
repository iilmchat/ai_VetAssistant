/** Простой in-app «центр уведомлений» без системного push (T-184). */

import type { AppRoute } from './deepLinks'

export interface AppNotification {
  id: string
  title: string
  body?: string
  action?: { label: string; route: AppRoute }
  createdAt: number
}

export type NotificationInput = Omit<AppNotification, 'id' | 'createdAt'>

let items: AppNotification[] = []
const listeners = new Set<(next: AppNotification[]) => void>()

function emit(): void {
  for (const listener of listeners) {
    listener([...items])
  }
}

export function getNotifications(): AppNotification[] {
  return [...items]
}

export function subscribeNotifications(
  listener: (next: AppNotification[]) => void,
): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function notify(input: NotificationInput): string {
  const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  items = [...items, { ...input, id, createdAt: Date.now() }].slice(-3)
  emit()
  return id
}

export function dismissNotification(id: string): void {
  items = items.filter((item) => item.id !== id)
  emit()
}

export function clearNotifications(): void {
  items = []
  emit()
}

/** Очередь оценок 👍/👎 на время отсутствия сети (T-185). */

import type { FeedbackRating } from '../types'

const QUEUE_KEY = 'vetassistant.feedbackQueue.v1'
const MAX_ITEMS = 50

export interface QueuedFeedback {
  messageId: string
  rating: FeedbackRating
  createdAt: string
}

function storage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    return null
  }
}

export function readFeedbackQueue(): QueuedFeedback[] {
  const raw = storage()?.getItem(QUEUE_KEY)
  if (!raw) {
    return []
  }
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) {
      return []
    }
    return parsed
      .filter(
        (item): item is QueuedFeedback =>
          typeof item === 'object' &&
          item !== null &&
          typeof (item as QueuedFeedback).messageId === 'string' &&
          ((item as QueuedFeedback).rating === 1 ||
            (item as QueuedFeedback).rating === -1),
      )
      .slice(0, MAX_ITEMS)
  } catch {
    return []
  }
}

function writeQueue(items: QueuedFeedback[]): void {
  try {
    storage()?.setItem(QUEUE_KEY, JSON.stringify(items.slice(0, MAX_ITEMS)))
  } catch {
    // Приватный режим — очередь живёт только до перезагрузки.
  }
}

/** Добавить оценку; повтор по messageId заменяет прежнюю. */
export function enqueueFeedback(item: QueuedFeedback): void {
  const next = [
    ...readFeedbackQueue().filter((queued) => queued.messageId !== item.messageId),
    item,
  ]
  writeQueue(next)
}

export function feedbackQueueSize(): number {
  return readFeedbackQueue().length
}

/** Отправить очередь; при ошибке элемент остаётся для следующей попытки. */
export async function flushFeedbackQueue(
  send: (item: QueuedFeedback) => Promise<void>,
): Promise<number> {
  let sent = 0
  for (const item of readFeedbackQueue()) {
    try {
      await send(item)
      writeQueue(readFeedbackQueue().filter((queued) => queued.messageId !== item.messageId))
      sent += 1
    } catch {
      break
    }
  }
  return sent
}

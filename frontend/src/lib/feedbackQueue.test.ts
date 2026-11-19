import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  enqueueFeedback,
  feedbackQueueSize,
  flushFeedbackQueue,
  readFeedbackQueue,
} from './feedbackQueue'

function stubStorage() {
  const store = new Map<string, string>()
  vi.stubGlobal('window', {
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value)
      },
      removeItem: (key: string) => {
        store.delete(key)
      },
    },
  })
  return store
}

beforeEach(() => {
  stubStorage()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('feedbackQueue', () => {
  it('сохраняет оценку и дедуплицирует по messageId', () => {
    enqueueFeedback({ messageId: 'm1', rating: 1, createdAt: 'now' })
    enqueueFeedback({ messageId: 'm1', rating: -1, createdAt: 'later' })

    expect(feedbackQueueSize()).toBe(1)
    expect(readFeedbackQueue()[0]?.rating).toBe(-1)
  })

  it('отправляет очередь и удаляет отправленные', async () => {
    enqueueFeedback({ messageId: 'm1', rating: 1, createdAt: 'now' })
    enqueueFeedback({ messageId: 'm2', rating: -1, createdAt: 'now' })
    const sent: string[] = []

    const count = await flushFeedbackQueue(async (item) => {
      sent.push(item.messageId)
    })

    expect(count).toBe(2)
    expect(sent).toEqual(['m1', 'm2'])
    expect(feedbackQueueSize()).toBe(0)
  })

  it('оставляет элемент в очереди при ошибке отправки', async () => {
    enqueueFeedback({ messageId: 'm1', rating: 1, createdAt: 'now' })

    const count = await flushFeedbackQueue(async () => {
      throw new Error('network')
    })

    expect(count).toBe(0)
    expect(feedbackQueueSize()).toBe(1)
  })

  it('игнорирует повреждённый JSON', () => {
    const store = stubStorage()
    store.set('vetassistant.feedbackQueue.v1', '{broken')

    expect(readFeedbackQueue()).toEqual([])
  })
})

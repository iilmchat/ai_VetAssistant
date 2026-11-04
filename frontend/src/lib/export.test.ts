import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  buildChatJson,
  buildChatMarkdown,
  chatExportFilename,
  downloadChatExport,
} from './export'
import type { UiMessage } from '../types'

const exportedAt = new Date('2026-11-04T12:00:00Z')

const messages: UiMessage[] = [
  {
    id: 'm1',
    role: 'user',
    content: 'Кот не ест сутки',
    toolCalls: [],
    status: 'done',
    createdAt: '2026-11-04T11:58:00Z',
  },
  {
    id: 'm2',
    role: 'assistant',
    content: 'Обратитесь к ветеринару.',
    toolCalls: [
      {
        id: 'call-1',
        type: 'function',
        function: {
          name: 'book_appointment',
          arguments: '{"pet_name":"Мурзик"}',
        },
      },
    ],
    status: 'done',
    createdAt: '2026-11-04T12:00:00Z',
  },
]

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('buildChatMarkdown', () => {
  it('включает роли, текст и вызовы инструментов', () => {
    const markdown = buildChatMarkdown(messages, {
      email: 'owner@example.com',
      exportedAt,
    })

    expect(markdown).toContain('# История диалога VetAssistant')
    expect(markdown).toContain('owner@example.com')
    expect(markdown).toContain('### Пользователь')
    expect(markdown).toContain('Кот не ест сутки')
    expect(markdown).toContain('### Ассистент')
    expect(markdown).toContain('book_appointment')
    expect(markdown).toContain('Мурзик')
  })

  it('не падает на пустой истории', () => {
    expect(buildChatMarkdown([], { exportedAt })).toContain('История пуста')
  })
})

describe('buildChatJson', () => {
  it('сериализует сообщения и даты', () => {
    const payload = JSON.parse(
      buildChatJson(messages, { email: 'owner@example.com', exportedAt }),
    ) as {
      version: number
      exported_at: string
      user: string
      messages: { role: string; created_at: string | null }[]
    }

    expect(payload.version).toBe(1)
    expect(payload.exported_at).toBe(exportedAt.toISOString())
    expect(payload.user).toBe('owner@example.com')
    expect(payload.messages).toHaveLength(2)
    expect(payload.messages[0]?.created_at).toBe('2026-11-04T11:58:00Z')
  })

  it('пишет null для старых сообщений без даты', () => {
    const payload = JSON.parse(
      buildChatJson([{ ...messages[0]!, createdAt: undefined }], { exportedAt }),
    ) as { messages: { created_at: string | null }[] }

    expect(payload.messages[0]?.created_at).toBeNull()
  })
})

describe('chatExportFilename', () => {
  it('нормализует email и дату', () => {
    expect(chatExportFilename('Owner+Test@Example.com', exportedAt, 'md')).toBe(
      'vetassistant-owner-test-example-com-2026-11-04.md',
    )
  })
})

describe('downloadChatExport', () => {
  it('скачивает Markdown через Blob и object URL', () => {
    const click = vi.fn()
    const link = {
      href: '',
      download: '',
      click,
      remove: vi.fn(),
    }
    const appendChild = vi.fn()
    const createObjectURL = vi.fn(() => 'blob:history')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('document', {
      createElement: () => link,
      body: { appendChild },
    })
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })

    downloadChatExport(messages, {
      email: 'owner@example.com',
      exportedAt,
    })

    expect(createObjectURL).toHaveBeenCalledOnce()
    expect(link.download).toBe('vetassistant-owner-example-com-2026-11-04.md')
    expect(click).toHaveBeenCalledOnce()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:history')
  })
})

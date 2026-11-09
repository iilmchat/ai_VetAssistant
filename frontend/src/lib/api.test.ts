import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  approveAdminAccessRequest,
  blockAdminUser,
  buildChatPayload,
  changePassword,
  createTelegramLinkCode,
  deleteAdminUser,
  fetchAdminAccessRequests,
  fetchAdminActivity,
  fetchAdminMetrics,
  fetchAdminUsers,
  fetchFeedbackStats,
  fetchTelegramLink,
  normalizeBaseUrl,
  parseSSEEvent,
  rejectAdminAccessRequest,
  requestAccess,
  setAuthToken,
  submitFeedback,
  unlinkTelegram,
} from './api'
import { AVAILABLE_TOOLS } from './tools'
import type { ChatSettings } from '../types'

const settings: ChatSettings = {
  temperature: 0.4,
  useRag: true,
  useTools: true,
}

afterEach(() => {
  vi.unstubAllGlobals()
  setAuthToken(null)
})

describe('normalizeBaseUrl', () => {
  it('убирает завершающий слеш', () => {
    expect(normalizeBaseUrl('http://127.0.0.1:8000/')).toBe(
      'http://127.0.0.1:8000',
    )
  })

  it('поддерживает относительный префикс nginx', () => {
    expect(normalizeBaseUrl('/api/')).toBe('/api')
  })

  it('возвращает локальный API по умолчанию', () => {
    expect(normalizeBaseUrl(undefined)).toBe('http://127.0.0.1:8000')
    expect(normalizeBaseUrl('   ')).toBe('http://127.0.0.1:8000')
  })
})

describe('buildChatPayload', () => {
  it('включает tools, RAG и stream', () => {
    const payload = buildChatPayload(
      [{ role: 'user', content: 'Кот не ест' }],
      settings,
      AVAILABLE_TOOLS,
      'qwen3-8b-vet',
    )

    expect(payload.model).toBe('qwen3-8b-vet')
    expect(payload.stream).toBe(true)
    expect(payload.use_rag).toBe(true)
    expect(payload.temperature).toBe(0.4)
    expect(payload.messages).toEqual([{ role: 'user', content: 'Кот не ест' }])
    expect(payload.tools).toEqual(AVAILABLE_TOOLS)
  })

  it('не отправляет tools, если Function Calling выключен', () => {
    const payload = buildChatPayload(
      [{ role: 'user', content: 'Вопрос' }],
      { ...settings, useTools: false },
      AVAILABLE_TOOLS,
    )

    expect(payload).not.toHaveProperty('tools')
  })
})

describe('changePassword', () => {
  it('отправляет старый и новый пароль с Bearer-токеном', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ message: 'Пароль изменён' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    setAuthToken('jwt-token')

    const result = await changePassword(
      'secret-pass-1',
      'new-secret-pass-2',
      'new-secret-pass-2',
    )

    expect(result.message).toBe('Пароль изменён')
    expect(fetchMock).toHaveBeenCalledTimes(1)

    const call = fetchMock.mock.calls[0]
    expect(call?.[0]).toBe('http://127.0.0.1:8000/v1/auth/change-password')
    const init = call?.[1] as RequestInit
    expect(init.method).toBe('POST')
    expect(new Headers(init.headers).get('Authorization')).toBe(
      'Bearer jwt-token',
    )
    expect(JSON.parse(String(init.body))).toEqual({
      old_password: 'secret-pass-1',
      new_password: 'new-secret-pass-2',
      new_password_confirm: 'new-secret-pass-2',
    })
  })

  it('передаёт сообщение об ошибке от API', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'Неверный старый пароль' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(
      changePassword('wrong', 'new-secret-pass-2', 'new-secret-pass-2'),
    ).rejects.toThrow('Неверный старый пароль')
  })
})

describe('requestAccess', () => {
  it('отправляет email и причину на /v1/access/request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ message: 'Заявка отправлена' }), {
        status: 202,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await requestAccess(
      'guest@example.com',
      'Ветеринар, хочу протестировать',
    )

    expect(result.message).toBe('Заявка отправлена')
    const call = fetchMock.mock.calls[0]
    expect(call?.[0]).toBe('http://127.0.0.1:8000/v1/access/request')
    const init = call?.[1] as RequestInit
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({
      email: 'guest@example.com',
      reason: 'Ветеринар, хочу протестировать',
    })
  })
})

describe('parseSSEEvent', () => {
  it('извлекает текстовую дельту', () => {
    const event = parseSSEEvent(
      'data: {"choices":[{"delta":{"content":"Здравствуйте"}}]}',
    )

    expect(event).toEqual({ content: 'Здравствуйте' })
  })

  it('извлекает tool_calls бэкенда', () => {
    const event = parseSSEEvent(
      'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"book_appointment","arguments":"{\\"pet_name\\":\\"Мурзик\\"}"}}]}}]}',
    )

    expect(event?.toolCalls).toEqual([
      {
        index: 0,
        id: 'call_1',
        type: 'function',
        function: {
          name: 'book_appointment',
          arguments: '{"pet_name":"Мурзик"}',
        },
      },
    ])
  })

  it('распознаёт завершение потока', () => {
    expect(parseSSEEvent('data: [DONE]')).toEqual({ done: true })
  })

  it('передаёт ошибку сервера', () => {
    expect(
      parseSSEEvent('data: {"error":{"message":"Модель недоступна"}}'),
    ).toEqual({ error: 'Модель недоступна' })
  })

  it('пропускает пустые и повреждённые события', () => {
    expect(parseSSEEvent('')).toBeNull()
    expect(parseSSEEvent('data: not-json')).toBeNull()
    expect(
      parseSSEEvent('data: {"choices":[{"delta":{"role":"assistant"}}]}'),
    ).toBeNull()
  })
})

describe('admin API', () => {
  it('запрашивает заявки с фильтром по статусу', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            id: 1,
            email: 'guest@example.com',
            reason: 'Хочу доступ',
            status: 'pending',
            created_at: '2026-11-04T00:00:00Z',
            reviewed_at: null,
            reviewed_by: null,
            approved_user_id: null,
            rejection_reason: null,
          },
        ]),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    setAuthToken('jwt-token')

    const result = await fetchAdminAccessRequests('pending')

    expect(result).toHaveLength(1)
    expect(result[0]?.email).toBe('guest@example.com')
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      'http://127.0.0.1:8000/v1/admin/access-requests?status=pending',
    )
  })

  it('approve возвращает временный пароль', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          temp_password: 'temp-pass-123',
          user_id: 5,
          email: 'guest@example.com',
          user: {
            id: 5,
            email: 'guest@example.com',
            created_at: '2026-11-04T00:00:00Z',
            is_admin: false,
            must_change_password: true,
          },
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await approveAdminAccessRequest(3)

    expect(result.temp_password).toBe('temp-pass-123')
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      'http://127.0.0.1:8000/v1/admin/access-requests/3/approve',
    )
  })

  it('reject отправляет причину', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: 3,
          email: 'guest@example.com',
          reason: 'Хочу доступ',
          status: 'rejected',
          created_at: '2026-11-04T00:00:00Z',
          reviewed_at: '2026-11-04T00:01:00Z',
          reviewed_by: 1,
          approved_user_id: null,
          rejection_reason: 'Нет необходимости',
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await rejectAdminAccessRequest(3, 'Нет необходимости')

    expect(result.status).toBe('rejected')
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({
      reason: 'Нет необходимости',
    })
  })

  it('fetchAdminMetrics передаёт окно и возвращает снимок', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          source: 'in_process',
          degraded: false,
          window: '24h',
          generated_at: '2026-11-05T00:00:00Z',
          started_at: '2026-11-04T20:00:00Z',
          totals: {
            requests: 12,
            generation_errors: 1,
            prompt_tokens: 500,
            completion_tokens: 200,
            tokens: 700,
            rag_hits: 5,
            rag_misses: 2,
            rag_errors: 0,
            http_errors: 0,
            error_rate: 0.08,
          },
          series: [],
          top_users: [],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchAdminMetrics('24h')

    expect(result.source).toBe('in_process')
    expect(result.totals.tokens).toBe(700)
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      'http://127.0.0.1:8000/v1/admin/metrics?window=24h',
    )
  })

  it('fetchAdminUsers передаёт поиск, статус и пагинацию', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [
            {
              id: 7,
              email: 'owner@example.com',
              is_admin: false,
              is_active: true,
              must_change_password: false,
              telegram_id: null,
              created_at: '2026-11-08T10:00:00Z',
            },
          ],
          total: 1,
          limit: 20,
          offset: 40,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchAdminUsers({
      query: 'own',
      status: 'active',
      limit: 20,
      offset: 40,
    })

    expect(result.total).toBe(1)
    expect(result.items[0]?.email).toBe('owner@example.com')
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      'http://127.0.0.1:8000/v1/admin/users?query=own&status=active&limit=20&offset=40',
    )
  })

  it('blockAdminUser отправляет причину', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: 7,
          email: 'owner@example.com',
          is_admin: false,
          is_active: false,
          must_change_password: false,
          telegram_id: null,
          created_at: '2026-11-08T10:00:00Z',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await blockAdminUser(7, 'спам')

    expect(result.is_active).toBe(false)
    const call = fetchMock.mock.calls[0]
    expect(call?.[0]).toBe('http://127.0.0.1:8000/v1/admin/users/7/block')
    const init = call?.[1] as RequestInit
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ reason: 'спам' })
  })

  it('deleteAdminUser отправляет email и причину', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: 7,
          email: 'owner@example.com',
          is_admin: false,
          is_active: true,
          must_change_password: false,
          telegram_id: null,
          created_at: '2026-11-08T10:00:00Z',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await deleteAdminUser(7, 'owner@example.com', 'по запросу')

    const call = fetchMock.mock.calls[0]
    expect(call?.[0]).toBe('http://127.0.0.1:8000/v1/admin/users/7')
    const init = call?.[1] as RequestInit
    expect(init.method).toBe('DELETE')
    expect(JSON.parse(String(init.body))).toEqual({
      confirm_email: 'owner@example.com',
      reason: 'по запросу',
    })
  })
})

describe('telegram linking', () => {
  it('fetchTelegramLink читает статус с Bearer-токеном', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          linked: true,
          telegram_id: 42,
          linked_at: '2026-11-05T20:00:00Z',
          email: 'owner@example.com',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    setAuthToken('jwt-token')

    const status = await fetchTelegramLink()

    expect(status.linked).toBe(true)
    expect(status.email).toBe('owner@example.com')
    const call = fetchMock.mock.calls[0]
    expect(call?.[0]).toBe('http://127.0.0.1:8000/v1/telegram/link')
    const init = call?.[1] as RequestInit
    expect(new Headers(init.headers).get('Authorization')).toBe(
      'Bearer jwt-token',
    )
  })

  it('createTelegramLinkCode отправляет POST и возвращает код', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          code: 'ABCD2345',
          expires_at: '2026-11-05T20:10:00Z',
          bot_username: 'vetassistant_bot',
          instructions: 'Отправьте /link ABCD2345',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await createTelegramLinkCode()

    expect(result.code).toBe('ABCD2345')
    expect(result.bot_username).toBe('vetassistant_bot')
    const call = fetchMock.mock.calls[0]
    expect(call?.[0]).toBe(
      'http://127.0.0.1:8000/v1/telegram/link-code',
    )
    const init = call?.[1] as RequestInit
    expect(init.method).toBe('POST')
  })

  it('unlinkTelegram отправляет DELETE', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ linked: false, message: 'Telegram отвязан' }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await unlinkTelegram()

    expect(result.message).toBe('Telegram отвязан')
    const call = fetchMock.mock.calls[0]
    expect(call?.[0]).toBe('http://127.0.0.1:8000/v1/telegram/link')
    const init = call?.[1] as RequestInit
    expect(init.method).toBe('DELETE')
  })
})

describe('feedback API', () => {
  it('submitFeedback отправляет оценку с Bearer-токеном', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          message: 'Оценка сохранена',
          message_id: 'msg-1',
          rating: 1,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    setAuthToken('jwt-token')

    const result = await submitFeedback('msg-1', 1)

    expect(result).toEqual({
      message: 'Оценка сохранена',
      message_id: 'msg-1',
      rating: 1,
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const call = fetchMock.mock.calls[0]
    expect(call?.[0]).toBe('http://127.0.0.1:8000/v1/feedback')
    const init = call?.[1] as RequestInit
    expect(init.method).toBe('POST')
    expect(new Headers(init.headers).get('Authorization')).toBe(
      'Bearer jwt-token',
    )
    expect(JSON.parse(String(init.body))).toEqual({
      message_id: 'msg-1',
      rating: 1,
    })
  })

  it('submitFeedback передаёт отрицательную оценку', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          message: 'Оценка обновлена',
          message_id: 'msg-2',
          rating: -1,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await submitFeedback('msg-2', -1)

    expect(result.rating).toBe(-1)
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    expect(JSON.parse(String(init.body))).toEqual({
      message_id: 'msg-2',
      rating: -1,
    })
  })

  it('fetchFeedbackStats читает статистику оценок', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          total: 10,
          positive: 7,
          negative: 3,
          positive_ratio: 0.7,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    setAuthToken('jwt-token')

    const result = await fetchFeedbackStats()

    expect(result).toEqual({
      total: 10,
      positive: 7,
      negative: 3,
      positive_ratio: 0.7,
    })
    const call = fetchMock.mock.calls[0]
    expect(call?.[0]).toBe('http://127.0.0.1:8000/v1/admin/feedback/stats')
    const init = call?.[1] as RequestInit
    expect(new Headers(init.headers).get('Authorization')).toBe(
      'Bearer jwt-token',
    )
  })
})

describe('admin activity API', () => {
  it('fetchAdminActivity передаёт window=7d, Bearer и разбирает series', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          source: 'prometheus',
          degraded: false,
          window: '7d',
          generated_at: '2026-11-09T12:00:00+00:00',
          series: [
            { date: '2026-11-03', active_users: 4, requests: 12 },
            { date: '2026-11-04', active_users: 3, requests: 7.5 },
          ],
          dau: 3,
          wau: 9,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    setAuthToken('jwt-token')

    const result = await fetchAdminActivity()

    expect(result.source).toBe('prometheus')
    expect(result.window).toBe('7d')
    expect(result.dau).toBe(3)
    expect(result.wau).toBe(9)
    expect(result.series).toHaveLength(2)
    expect(result.series[0]).toEqual({
      date: '2026-11-03',
      active_users: 4,
      requests: 12,
    })
    const call = fetchMock.mock.calls[0]
    expect(call?.[0]).toBe(
      'http://127.0.0.1:8000/v1/admin/activity?window=7d',
    )
    const init = call?.[1] as RequestInit
    expect(new Headers(init.headers).get('Authorization')).toBe(
      'Bearer jwt-token',
    )
  })

  it('fetchAdminActivity передаёт window=30d и терпит fallback', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          source: 'unavailable',
          degraded: true,
          window: '30d',
          generated_at: '2026-11-09T12:00:00+00:00',
          series: [],
          dau: 0,
          wau: 0,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchAdminActivity('30d')

    expect(result.source).toBe('unavailable')
    expect(result.series).toEqual([])
    expect(result.dau).toBe(0)
    expect(result.wau).toBe(0)
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      'http://127.0.0.1:8000/v1/admin/activity?window=30d',
    )
  })
})

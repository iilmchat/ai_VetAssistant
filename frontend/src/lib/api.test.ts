import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  buildChatPayload,
  changePassword,
  normalizeBaseUrl,
  parseSSEEvent,
  setAuthToken,
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

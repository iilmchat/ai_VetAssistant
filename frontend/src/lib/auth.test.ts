import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  clearAuthSession,
  loadAuthSession,
  messagesStorageKey,
  parseAuthSession,
  saveAuthSession,
} from './auth'
import type { AuthSession } from './auth'
import { getAuthToken, setAuthToken } from './api'

const session: AuthSession = {
  access_token: 'jwt-token',
  token_type: 'bearer',
  user: {
    id: 7,
    email: 'owner@example.com',
    created_at: '2026-11-03T10:00:00Z',
  },
}

function stubLocalStorage() {
  const store = new Map<string, string>()
  const localStorage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value)
    },
    removeItem: (key: string) => {
      store.delete(key)
    },
  }
  vi.stubGlobal('window', { localStorage })
  return store
}

afterEach(() => {
  vi.unstubAllGlobals()
  setAuthToken(null)
})

describe('parseAuthSession', () => {
  it('принимает корректную сессию', () => {
    expect(parseAuthSession(session)).toEqual(session)
  })

  it('добавляет token_type по умолчанию', () => {
    const raw = { ...session, token_type: undefined }
    expect(parseAuthSession(raw)?.token_type).toBe('bearer')
  })

  it('отклоняет пустой токен и неполного пользователя', () => {
    expect(parseAuthSession({ ...session, access_token: '' })).toBeNull()
    expect(parseAuthSession({ ...session, user: { id: 1 } })).toBeNull()
    expect(parseAuthSession(null)).toBeNull()
  })
})

describe('localStorage-сессия', () => {
  it('сохраняет, читает и очищает сессию', () => {
    const store = stubLocalStorage()

    saveAuthSession(session)
    expect(store.size).toBe(1)
    expect(loadAuthSession()).toEqual(session)

    clearAuthSession()
    expect(loadAuthSession()).toBeNull()
  })

  it('возвращает null при повреждённом JSON', () => {
    const store = stubLocalStorage()
    store.set('vetassistant.auth.v1', '{not-json')

    expect(loadAuthSession()).toBeNull()
  })

  it('строит ключ истории по id пользователя', () => {
    expect(messagesStorageKey(7)).toBe('vetassistant.messages.v1.7')
  })
})

describe('auth token для API', () => {
  it('устанавливает и очищает Bearer-токен', () => {
    expect(getAuthToken()).toBeNull()
    setAuthToken('  jwt-token  ')
    expect(getAuthToken()).toBe('jwt-token')
    setAuthToken('   ')
    expect(getAuthToken()).toBeNull()
  })
})

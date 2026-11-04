export interface AuthUser {
  id: number
  email: string
  created_at: string
  is_admin: boolean
  must_change_password: boolean
}

export interface AuthSession {
  access_token: string
  token_type: string
  user: AuthUser
}

const AUTH_STORAGE_KEY = 'vetassistant.auth.v1'
const MESSAGES_STORAGE_PREFIX = 'vetassistant.messages.v1'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function parseUser(value: unknown): AuthUser | null {
  if (
    !isRecord(value) ||
    typeof value.id !== 'number' ||
    typeof value.email !== 'string' ||
    typeof value.created_at !== 'string'
  ) {
    return null
  }
  return {
    id: value.id,
    email: value.email,
    created_at: value.created_at,
    is_admin: value.is_admin === true,
    must_change_password: value.must_change_password === true,
  }
}

export function parseAuthSession(value: unknown): AuthSession | null {
  if (!isRecord(value)) {
    return null
  }
  const user = parseUser(value.user)
  if (
    typeof value.access_token !== 'string' ||
    !value.access_token ||
    !user
  ) {
    return null
  }
  return {
    access_token: value.access_token,
    token_type:
      typeof value.token_type === 'string' ? value.token_type : 'bearer',
    user,
  }
}

export function loadAuthSession(): AuthSession | null {
  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY)
    if (!raw) {
      return null
    }
    return parseAuthSession(JSON.parse(raw))
  } catch {
    return null
  }
}

export function saveAuthSession(session: AuthSession): void {
  try {
    window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session))
  } catch {
    // Приватный режим или переполненное хранилище — сессия останется в памяти.
  }
}

export function clearAuthSession(): void {
  try {
    window.localStorage.removeItem(AUTH_STORAGE_KEY)
  } catch {
    // Хранилище недоступно — очищать нечего.
  }
}

export function messagesStorageKey(userId: number): string {
  return `${MESSAGES_STORAGE_PREFIX}.${userId}`
}

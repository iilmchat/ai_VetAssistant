import type {
  Appointment,
  ChatSettings,
  Reminder,
  Role,
  ToolCallDelta,
  ToolDefinition,
} from '../types'
import type { AuthSession, AuthUser } from './auth'
import { isAbortError, isRecord } from './utils'

const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000'
const DEFAULT_MODEL_ID = 'qwen3-8b-vet'

export function normalizeBaseUrl(value: string | undefined): string {
  const normalized = value?.trim().replace(/\/+$/, '')
  return normalized || DEFAULT_API_BASE_URL
}

export const API_BASE_URL = normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL)
export const MODEL_ID =
  (import.meta.env.VITE_MODEL_ID as string | undefined)?.trim() ||
  DEFAULT_MODEL_ID

let authToken: string | null = null

/** Задать JWT для всех последующих запросов к API. */
export function setAuthToken(token: string | null): void {
  authToken = token?.trim() || null
}

export function getAuthToken(): string | null {
  return authToken
}

export interface ChatHistoryMessage {
  role: Role | 'system'
  content: string
}

export interface HealthResponse {
  status: string
  model: string
  model_path_exists: boolean
}

export interface ChangePasswordResponse {
  message: string
}

export interface AccessRequestResponse {
  message: string
}

export interface StreamEvent {
  content?: string
  toolCalls?: ToolCallDelta[]
  done?: boolean
  error?: string
}

export interface StreamChatOptions {
  messages: ChatHistoryMessage[]
  settings: ChatSettings
  tools: ToolDefinition[]
  signal?: AbortSignal
  baseUrl?: string
  modelId?: string
}

export class ApiError extends Error {
  readonly status?: number

  constructor(message: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export function apiUrl(path: string, baseUrl: string = API_BASE_URL): string {
  const suffix = path.startsWith('/') ? path : `/${path}`
  return `${normalizeBaseUrl(baseUrl)}${suffix}`
}

export function buildChatPayload(
  messages: ChatHistoryMessage[],
  settings: ChatSettings,
  tools: ToolDefinition[],
  modelId: string = MODEL_ID,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    model: modelId,
    messages: messages.map((message) => ({
      role: message.role,
      content: message.content,
    })),
    temperature: settings.temperature,
    stream: true,
    use_rag: settings.useRag,
  }

  if (settings.useTools && tools.length > 0) {
    payload.tools = tools
  }

  return payload
}

async function extractError(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json()
    if (isRecord(payload)) {
      const detail = payload.detail
      if (typeof detail === 'string' && detail.trim()) {
        return detail
      }
      const error = payload.error
      if (isRecord(error)) {
        const message = error.message
        if (typeof message === 'string' && message.trim()) {
          return message
        }
      }
      if (typeof error === 'string' && error.trim()) {
        return error
      }
    }
  } catch {
    // Тело ошибки может быть не-JSON — ниже вернём сообщение по статусу.
  }

  if (response.status === 401) {
    return 'Требуется вход в систему. Войдите снова.'
  }
  if (response.status === 400) {
    return 'Запрос отклонён системой безопасности.'
  }
  if (response.status === 503) {
    return 'Модель временно недоступна. Попробуйте позже.'
  }
  return `Сервер вернул ошибку ${response.status}. Попробуйте позже.`
}

function withAuth(headers: Headers): Headers {
  if (authToken) {
    headers.set('Authorization', `Bearer ${authToken}`)
  }
  return headers
}

async function requestJson<T>(
  path: string,
  options: RequestInit = {},
  baseUrl: string = API_BASE_URL,
): Promise<T> {
  const headers = withAuth(new Headers(options.headers))
  headers.set('Accept', 'application/json')

  let response: Response
  try {
    response = await fetch(apiUrl(path, baseUrl), { ...options, headers })
  } catch (error) {
    if (isAbortError(error)) {
      throw error
    }
    throw new ApiError(
      'Не удалось связаться с сервером ветеринара. Проверьте, что API запущен.',
    )
  }

  if (!response.ok) {
    throw new ApiError(await extractError(response), response.status)
  }

  return (await response.json()) as T
}

export function register(
  email: string,
  password: string,
  baseUrl: string = API_BASE_URL,
): Promise<AuthSession> {
  return requestJson<AuthSession>(
    '/v1/auth/register',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    },
    baseUrl,
  )
}

export function login(
  email: string,
  password: string,
  baseUrl: string = API_BASE_URL,
): Promise<AuthSession> {
  return requestJson<AuthSession>(
    '/v1/auth/login',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    },
    baseUrl,
  )
}

export async function fetchCurrentUser(
  token: string,
  baseUrl: string = API_BASE_URL,
): Promise<AuthUser> {
  const headers = new Headers()
  headers.set('Authorization', `Bearer ${token}`)
  return requestJson<AuthUser>('/v1/auth/me', { headers }, baseUrl)
}

export function changePassword(
  oldPassword: string,
  newPassword: string,
  newPasswordConfirm?: string,
  baseUrl: string = API_BASE_URL,
): Promise<ChangePasswordResponse> {
  return requestJson<ChangePasswordResponse>(
    '/v1/auth/change-password',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        old_password: oldPassword,
        new_password: newPassword,
        new_password_confirm: newPasswordConfirm,
      }),
    },
    baseUrl,
  )
}

export function requestAccess(
  email: string,
  reason: string,
  baseUrl: string = API_BASE_URL,
): Promise<AccessRequestResponse> {
  return requestJson<AccessRequestResponse>(
    '/v1/access/request',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, reason }),
    },
    baseUrl,
  )
}

export function fetchHealth(
  baseUrl: string = API_BASE_URL,
): Promise<HealthResponse> {
  return requestJson<HealthResponse>(
    '/health',
    { signal: AbortSignal.timeout(5000) },
    baseUrl,
  )
}

export async function fetchAppointments(
  baseUrl: string = API_BASE_URL,
): Promise<Appointment[]> {
  const payload = await requestJson<Appointment[]>(
    '/v1/appointments',
    {},
    baseUrl,
  )
  return Array.isArray(payload) ? payload : []
}

export async function fetchReminders(
  baseUrl: string = API_BASE_URL,
): Promise<Reminder[]> {
  const payload = await requestJson<Reminder[]>('/v1/reminders', {}, baseUrl)
  return Array.isArray(payload) ? payload : []
}

function parseToolCallDelta(value: unknown): ToolCallDelta | null {
  if (!isRecord(value)) {
    return null
  }

  const fn = isRecord(value.function) ? value.function : undefined
  const name =
    fn && typeof fn.name === 'string' && fn.name.length > 0
      ? fn.name
      : undefined

  let args: string | undefined
  if (fn && typeof fn.arguments === 'string') {
    args = fn.arguments
  } else if (fn && fn.arguments !== undefined) {
    args = JSON.stringify(fn.arguments)
  }

  if (!name && !args) {
    return null
  }

  const delta: ToolCallDelta = {}
  if (typeof value.index === 'number') {
    delta.index = value.index
  }
  if (typeof value.id === 'string' && value.id) {
    delta.id = value.id
  }
  if (typeof value.type === 'string' && value.type) {
    delta.type = value.type
  }
  if (name || args) {
    delta.function = {}
    if (name) {
      delta.function.name = name
    }
    if (args) {
      delta.function.arguments = args
    }
  }
  return delta
}

/**
 * Разобрать один SSE-блок (между пустыми строками).
 *
 * Возвращает `null` для служебных/некорректных блоков, чтобы поток не падал
 * из-за одного повреждённого события.
 */
export function parseSSEEvent(raw: string): StreamEvent | null {
  const data = raw
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).replace(/^ /, ''))
    .join('\n')
    .trim()

  if (!data) {
    return null
  }
  if (data === '[DONE]') {
    return { done: true }
  }

  let payload: unknown
  try {
    payload = JSON.parse(data)
  } catch {
    return null
  }
  if (!isRecord(payload)) {
    return null
  }

  if (isRecord(payload.error)) {
    const message = payload.error.message
    if (typeof message === 'string' && message.trim()) {
      return { error: message }
    }
  }
  if (typeof payload.error === 'string' && payload.error.trim()) {
    return { error: payload.error }
  }

  const choices = payload.choices
  if (!Array.isArray(choices) || choices.length === 0) {
    return null
  }

  const first = choices[0]
  if (!isRecord(first) || !isRecord(first.delta)) {
    return null
  }

  const delta = first.delta
  const content =
    typeof delta.content === 'string' && delta.content.length > 0
      ? delta.content
      : undefined

  const rawCalls = Array.isArray(delta.tool_calls) ? delta.tool_calls : []
  const toolCalls = rawCalls
    .map(parseToolCallDelta)
    .filter((call): call is ToolCallDelta => call !== null)

  if (content === undefined && toolCalls.length === 0) {
    return null
  }

  return {
    ...(content !== undefined ? { content } : {}),
    ...(toolCalls.length > 0 ? { toolCalls } : {}),
  }
}

/**
 * Потоково запросить ответ FastAPI через SSE.
 *
 * @throws {ApiError} если сервер недоступен или вернул HTTP-ошибку.
 * @throws {Error} `AbortError`, если запрос отменён через `signal`.
 */
export async function* streamChat(
  options: StreamChatOptions,
): AsyncGenerator<StreamEvent> {
  const {
    messages,
    settings,
    tools,
    signal,
    baseUrl = API_BASE_URL,
    modelId = MODEL_ID,
  } = options

  const payload = buildChatPayload(messages, settings, tools, modelId)

  let response: Response
  try {
    const headers = withAuth(new Headers())
    headers.set('Accept', 'text/event-stream')
    headers.set('Content-Type', 'application/json')

    response = await fetch(apiUrl('/v1/chat/completions', baseUrl), {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      signal,
    })
  } catch (error) {
    if (isAbortError(error)) {
      throw error
    }
    throw new ApiError(
      'Не удалось связаться с сервером ветеринара. Проверьте, что API запущен.',
    )
  }

  if (!response.ok) {
    throw new ApiError(await extractError(response), response.status)
  }
  if (!response.body) {
    throw new ApiError('Сервер не вернул поток ответа.')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  const separator = /\r?\n\r?\n/
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        break
      }

      buffer += decoder.decode(value, { stream: true })
      let match = separator.exec(buffer)

      while (match) {
        const rawEvent = buffer.slice(0, match.index)
        buffer = buffer.slice(match.index + match[0].length)

        const event = parseSSEEvent(rawEvent)
        if (event) {
          yield event
          if (event.done) {
            void reader.cancel().catch(() => undefined)
            return
          }
        }

        match = separator.exec(buffer)
      }
    }

    buffer += decoder.decode()
    if (buffer.trim()) {
      const event = parseSSEEvent(buffer)
      if (event) {
        yield event
      }
    }
  } finally {
    reader.releaseLock()
  }
}

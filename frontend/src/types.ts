export type Role = 'user' | 'assistant'

export interface ToolCallFunction {
  name: string
  arguments: string
}

export interface ToolCall {
  id: string
  type: 'function'
  function: ToolCallFunction
}

export interface ToolCallDelta {
  index?: number
  id?: string
  type?: string
  function?: {
    name?: string
    arguments?: string
  }
}

export interface ToolDefinition {
  type: 'function'
  function: {
    name: string
    description: string
    parameters: Record<string, unknown>
  }
}

export interface ChatSettings {
  temperature: number
  useRag: boolean
  useTools: boolean
}

export type MessageStatus = 'streaming' | 'done' | 'stopped' | 'error'

export interface UiMessage {
  id: string
  role: Role
  content: string
  toolCalls: ToolCall[]
  status: MessageStatus
  createdAt?: string
  error?: string
}

export interface Appointment {
  id: number
  pet_name: string
  date: string
  time: string
}

export interface Reminder {
  id: number
  text: string
  time: string
}

export type ApiStatus = 'checking' | 'online' | 'offline'

export interface TelegramLinkStatus {
  linked: boolean
  telegram_id: number | null
  linked_at: string | null
  email?: string | null
}

export interface TelegramLinkCode {
  code: string
  expires_at: string
  bot_username: string | null
  instructions: string
}

export interface TelegramUnlinkResponse {
  linked: boolean
  message: string
}

export type AccessRequestStatus = 'pending' | 'approved' | 'rejected'

export interface AdminAccessRequest {
  id: number
  email: string
  reason: string
  status: AccessRequestStatus
  created_at: string
  reviewed_at: string | null
  reviewed_by: number | null
  approved_user_id: number | null
  rejection_reason: string | null
}

export type AdminMetricsSource = 'prometheus' | 'in_process'

export type AdminMetricsWindow = '24h' | '7d'

export interface AdminMetricsTotals {
  requests: number
  generation_errors: number
  prompt_tokens: number
  completion_tokens: number
  tokens: number
  rag_hits: number
  rag_misses: number
  rag_errors: number
  http_errors: number
  error_rate: number
}

export interface AdminMetricsPoint {
  ts: string
  requests: number
  tokens: number
}

export interface AdminTopUser {
  user_id: number
  email: string
  requests: number
  tokens: number
}

export interface AdminMetrics {
  source: AdminMetricsSource
  degraded: boolean
  window: AdminMetricsWindow
  generated_at: string
  started_at: string | null
  totals: AdminMetricsTotals
  series: AdminMetricsPoint[]
  top_users: AdminTopUser[]
}

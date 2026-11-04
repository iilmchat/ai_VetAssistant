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

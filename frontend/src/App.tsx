import { useCallback, useEffect, useRef, useState } from 'react'
import {
  BookOpen,
  Loader2,
  Menu,
  Wrench,
  Wifi,
  WifiOff,
} from 'lucide-react'
import type {
  ApiStatus,
  Appointment,
  ChatSettings,
  Reminder,
  ToolCall,
  UiMessage,
} from './types'
import {
  ApiError,
  fetchAppointments,
  fetchCurrentUser,
  fetchHealth,
  fetchReminders,
  setAuthToken,
  streamChat,
} from './lib/api'
import {
  clearAuthSession,
  loadAuthSession,
  messagesStorageKey,
  saveAuthSession,
} from './lib/auth'
import type { AuthSession } from './lib/auth'
import { AVAILABLE_TOOLS, mergeToolCalls } from './lib/tools'
import { downloadChatExport } from './lib/export'
import { errorMessage, isAbortError, isRecord, uid } from './lib/utils'
import { Sidebar } from './components/Sidebar'
import { MessageBubble } from './components/MessageBubble'
import { Composer } from './components/Composer'
import { Welcome } from './components/Welcome'
import { AuthScreen } from './components/AuthScreen'
import { ChangePasswordDialog } from './components/ChangePasswordDialog'
import { AdminDashboard } from './components/AdminDashboard'

const MAX_CONTEXT_MESSAGES = 20
const DEFAULT_SETTINGS: ChatSettings = {
  temperature: 0.7,
  useRag: true,
  useTools: false,
}

function isToolCall(value: unknown): value is ToolCall {
  if (!isRecord(value) || !isRecord(value.function)) {
    return false
  }
  return (
    value.type === 'function' &&
    typeof value.id === 'string' &&
    typeof value.function.name === 'string' &&
    typeof value.function.arguments === 'string'
  )
}

function loadStoredMessages(userId: number | null): UiMessage[] {
  if (userId === null) {
    return []
  }
  try {
    const raw = window.localStorage.getItem(messagesStorageKey(userId))
    if (!raw) {
      return []
    }
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) {
      return []
    }

    const messages: UiMessage[] = []
    for (const item of parsed) {
      if (
        !isRecord(item) ||
        (item.role !== 'user' && item.role !== 'assistant') ||
        typeof item.content !== 'string'
      ) {
        continue
      }

      messages.push({
        id: typeof item.id === 'string' ? item.id : uid(),
        role: item.role,
        content: item.content,
        toolCalls: Array.isArray(item.toolCalls)
          ? item.toolCalls.filter(isToolCall)
          : [],
        status: 'done',
        createdAt:
          typeof item.createdAt === 'string' ? item.createdAt : undefined,
      })
    }
    return messages
  } catch {
    return []
  }
}

function apiStatusLabel(status: ApiStatus): string {
  if (status === 'online') {
    return 'API онлайн'
  }
  if (status === 'offline') {
    return 'API недоступен'
  }
  return 'Подключение…'
}

function App() {
  const [session, setSession] = useState<AuthSession | null>(() =>
    loadAuthSession(),
  )
  const [messages, setMessages] = useState<UiMessage[]>(() =>
    loadStoredMessages(loadAuthSession()?.user.id ?? null),
  )
  const [input, setInput] = useState('')
  const [settings, setSettings] = useState<ChatSettings>(DEFAULT_SETTINGS)
  const [isStreaming, setIsStreaming] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [apiStatus, setApiStatus] = useState<ApiStatus>('checking')
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [reminders, setReminders] = useState<Reminder[]>([])
  const [recordsLoading, setRecordsLoading] = useState(true)
  const [recordsError, setRecordsError] = useState<string | null>(null)
  const [passwordDialogOpen, setPasswordDialogOpen] = useState(false)
  const [adminOpen, setAdminOpen] = useState(false)
  const [authNotice, setAuthNotice] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const shouldStickToBottom = useRef(true)

  const handleLogout = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setAuthToken(null)
    clearAuthSession()
    setSession(null)
    setMessages([])
    setInput('')
    setAppointments([])
    setReminders([])
    setRecordsError(null)
    setRecordsLoading(true)
    setSidebarOpen(false)
    setPasswordDialogOpen(false)
    setAdminOpen(false)
  }, [])

  const handleAuthenticated = useCallback((next: AuthSession) => {
    setAuthToken(next.access_token)
    saveAuthSession(next)
    setSession(next)
    setMessages(loadStoredMessages(next.user.id))
    setRecordsLoading(true)
    setRecordsError(null)
    setAuthNotice(null)
    setSidebarOpen(false)
  }, [])

  const handlePasswordChanged = useCallback(() => {
    setAuthNotice('Пароль изменен')
    handleLogout()
  }, [handleLogout])

  const patchMessage = useCallback(
    (id: string, patch: Partial<UiMessage>) => {
      setMessages((previous) =>
        previous.map((message) =>
          message.id === id ? { ...message, ...patch } : message,
        ),
      )
    },
    [],
  )

  const loadRecords = useCallback(async () => {
    if (!session) {
      return
    }
    try {
      const [nextAppointments, nextReminders] = await Promise.all([
        fetchAppointments(),
        fetchReminders(),
      ])
      setRecordsError(null)
      setAppointments(nextAppointments)
      setReminders(nextReminders)
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        handleLogout()
        return
      }
      if (!isAbortError(error)) {
        setRecordsError(errorMessage(error))
      }
    } finally {
      setRecordsLoading(false)
    }
  }, [session, handleLogout])

  useEffect(() => {
    setAuthToken(session?.access_token ?? null)
  }, [session])

  useEffect(() => {
    // Временный пароль из админ-панели: сразу предлагаем сменить его.
    if (session?.user.must_change_password) {
      // oxlint-disable-next-line react/set-state-in-effect
      setPasswordDialogOpen(true)
    }
  }, [session])

  useEffect(() => {
    // Синхронизация с внешним API при монтировании; состояние обновляется
    // после await, а не синхронно в теле эффекта.
    // oxlint-disable-next-line react/set-state-in-effect
    void loadRecords()
  }, [loadRecords])

  useEffect(() => {
    if (!session) {
      return
    }
    let active = true

    void fetchCurrentUser(session.access_token).catch((error: unknown) => {
      if (active && error instanceof ApiError && error.status === 401) {
        handleLogout()
      }
    })

    return () => {
      active = false
    }
  }, [session, handleLogout])

  useEffect(() => {
    let active = true

    async function checkHealth() {
      try {
        await fetchHealth()
        if (active) {
          setApiStatus('online')
        }
      } catch {
        if (active) {
          setApiStatus('offline')
        }
      }
    }

    void checkHealth()
    const interval = window.setInterval(() => {
      void checkHealth()
    }, 30_000)

    return () => {
      active = false
      window.clearInterval(interval)
    }
  }, [])

  useEffect(() => {
    if (!session) {
      return
    }
    if (messages.some((message) => message.status === 'streaming')) {
      return
    }

    const stored = messages
      .filter(
        (message) => message.content.trim().length > 0 || message.toolCalls.length > 0,
      )
      .map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content,
        toolCalls: message.toolCalls,
        createdAt: message.createdAt,
      }))

    const key = messagesStorageKey(session.user.id)
    try {
      if (stored.length === 0) {
        window.localStorage.removeItem(key)
      } else {
        window.localStorage.setItem(key, JSON.stringify(stored))
      }
    } catch {
      // Приватный режим или переполненное хранилище — история просто не сохранится.
    }
  }, [messages, session])

  useEffect(() => {
    if (!shouldStickToBottom.current) {
      return
    }
    const element = scrollRef.current
    if (!element) {
      return
    }
    element.scrollTo({ top: element.scrollHeight, behavior: 'auto' })
  }, [messages])

  async function sendMessage(raw: string) {
    const text = raw.trim()
    if (!text || isStreaming) {
      return
    }

    shouldStickToBottom.current = true
    const createdAt = new Date().toISOString()

    const userMessage: UiMessage = {
      id: uid(),
      role: 'user',
      content: text,
      toolCalls: [],
      status: 'done',
      createdAt,
    }
    const assistantId = uid()
    const assistantMessage: UiMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      toolCalls: [],
      status: 'streaming',
      createdAt,
    }

    const history = [...messages, userMessage]
      .filter(
        (message) =>
          message.content.trim().length > 0 && message.status !== 'error',
      )
      .slice(-MAX_CONTEXT_MESSAGES)
      .map((message) => ({
        role: message.role,
        content: message.content,
      }))

    setMessages((previous) => [...previous, userMessage, assistantMessage])
    setInput('')
    setIsStreaming(true)

    const controller = new AbortController()
    abortRef.current = controller

    let content = ''
    let toolCalls: ToolCall[] = []

    try {
      for await (const event of streamChat({
        messages: history,
        settings,
        tools: AVAILABLE_TOOLS,
        signal: controller.signal,
      })) {
        if (event.done) {
          break
        }
        if (event.error) {
          throw new ApiError(event.error)
        }

        if (event.content) {
          content += event.content
          patchMessage(assistantId, { content })
        }

        if (event.toolCalls && event.toolCalls.length > 0) {
          toolCalls = mergeToolCalls(toolCalls, event.toolCalls)
          patchMessage(assistantId, { toolCalls })
        }
      }

      if (!content.trim() && toolCalls.length === 0) {
        throw new ApiError(
          'Модель не вернула ответ. Попробуйте переформулировать вопрос.',
        )
      }

      patchMessage(assistantId, { content, toolCalls, status: 'done' })

      if (toolCalls.length > 0) {
        void loadRecords()
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        handleLogout()
        return
      }
      if (controller.signal.aborted || isAbortError(error)) {
        patchMessage(assistantId, {
          content,
          toolCalls,
          status: 'stopped',
        })
      } else {
        patchMessage(assistantId, {
          content,
          toolCalls,
          status: 'error',
          error:
            error instanceof Error
              ? error.message
              : 'Не удалось получить ответ ветеринара.',
        })
      }
    } finally {
      setIsStreaming(false)
      abortRef.current = null
    }
  }

  function handleStop() {
    abortRef.current?.abort()
  }

  function handleNewChat() {
    abortRef.current?.abort()
    setMessages([])
    setInput('')
    setSidebarOpen(false)
    if (!session) {
      return
    }
    try {
      window.localStorage.removeItem(messagesStorageKey(session.user.id))
    } catch {
      // Хранилище недоступно — ничего страшного.
    }
  }

  function handleExportHistory() {
    if (!session || messages.length === 0) {
      return
    }
    downloadChatExport(messages, { email: session.user.email })
  }

  function updateSettings(patch: Partial<ChatSettings>) {
    setSettings((previous) => ({ ...previous, ...patch }))
  }

  if (!session) {
    return <AuthScreen onAuthenticated={handleAuthenticated} notice={authNotice} />
  }

  if (adminOpen) {
    return <AdminDashboard onClose={() => setAdminOpen(false)} />
  }

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-[#212121] text-zinc-100">
      <Sidebar
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        settings={settings}
        onSettingsChange={updateSettings}
        onNewChat={handleNewChat}
        canExport={messages.length > 0}
        onExportHistory={handleExportHistory}
        appointments={appointments}
        reminders={reminders}
        recordsLoading={recordsLoading}
        recordsError={recordsError}
        onRefreshRecords={() => {
          setRecordsLoading(true)
          setRecordsError(null)
          void loadRecords()
        }}
        apiStatus={apiStatus}
        userEmail={session.user.email}
        isAdmin={session.user.is_admin}
        onOpenAdmin={() => {
          setSidebarOpen(false)
          setAdminOpen(true)
        }}
        onOpenSettings={() => {
          setSidebarOpen(false)
          setPasswordDialogOpen(true)
        }}
        onLogout={handleLogout}
      />

      {passwordDialogOpen && (
        <ChangePasswordDialog
          onClose={() => setPasswordDialogOpen(false)}
          onPasswordChanged={handlePasswordChanged}
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-white/[0.07] bg-[#212121]/95 px-3 backdrop-blur sm:px-4 lg:px-6">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            aria-label="Открыть меню"
            className="rounded-lg p-1.5 text-zinc-400 transition-colors hover:bg-white/5 hover:text-white lg:hidden"
          >
            <Menu className="h-5 w-5" />
          </button>

          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="truncate text-[13px] font-semibold tracking-tight text-zinc-100">
                Консультация
              </h1>
              <span className="hidden rounded-full border border-emerald-500/20 bg-emerald-500/[0.07] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-emerald-300 sm:inline">
                vet
              </span>
            </div>
            <p className="truncate text-[10.5px] text-zinc-500">
              Qwen3-8B Vet · локальный API
            </p>
          </div>

          <div className="ml-auto flex items-center gap-1.5">
            {settings.useRag && (
              <span className="hidden items-center gap-1 rounded-full border border-white/10 bg-white/[0.03] px-2 py-1 text-[9.5px] font-medium text-zinc-400 md:inline-flex">
                <BookOpen className="h-3 w-3 text-emerald-400/80" />
                RAG
              </span>
            )}
            {settings.useTools && (
              <span className="hidden items-center gap-1 rounded-full border border-white/10 bg-white/[0.03] px-2 py-1 text-[9.5px] font-medium text-zinc-400 md:inline-flex">
                <Wrench className="h-3 w-3 text-amber-400/80" />
                Tools
              </span>
            )}

            <div
              title={apiStatusLabel(apiStatus)}
              className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[10px] text-zinc-400"
            >
              {apiStatus === 'checking' ? (
                <Loader2 className="h-3 w-3 animate-spin text-amber-400" />
              ) : apiStatus === 'online' ? (
                <Wifi className="h-3 w-3 text-emerald-400" />
              ) : (
                <WifiOff className="h-3 w-3 text-rose-400" />
              )}
              <span className="hidden sm:inline">{apiStatusLabel(apiStatus)}</span>
            </div>
          </div>
        </header>

        <main
          ref={scrollRef}
          onScroll={(event) => {
            const element = event.currentTarget
            const distance =
              element.scrollHeight - element.scrollTop - element.clientHeight
            shouldStickToBottom.current = distance < 120
          }}
          className="flex-1 overflow-y-auto"
        >
          <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6 sm:py-8">
            {messages.length === 0 ? (
              <Welcome
                onSuggestion={(prompt) => {
                  void sendMessage(prompt)
                }}
              />
            ) : (
              <div className="space-y-7">
                {messages.map((message) => (
                  <MessageBubble key={message.id} message={message} />
                ))}
                <div className="h-1" />
              </div>
            )}
          </div>
        </main>

        <Composer
          value={input}
          onChange={setInput}
          onSend={() => {
            void sendMessage(input)
          }}
          onStop={handleStop}
          isStreaming={isStreaming}
        />
      </div>
    </div>
  )
}

export default App

import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertTriangle,
  BookOpen,
  Loader2,
  Menu,
  Wrench,
  Wifi,
  WifiOff,
  X,
} from 'lucide-react'
import type {
  ApiStatus,
  Appointment,
  ChatSettings,
  FeedbackRating,
  Patient,
  Reminder,
  ToolCall,
  UiMessage,
} from './types'
import {
  ApiError,
  fetchAppointments,
  fetchCurrentUser,
  fetchHealth,
  fetchPatients,
  fetchReminders,
  setAuthToken,
  streamChat,
  submitFeedback,
} from './lib/api'
import {
  clearAuthSession,
  loadAuthSession,
  messagesStorageKey,
  saveAuthSession,
} from './lib/auth'
import type { AuthSession } from './lib/auth'
import { AVAILABLE_TOOLS, mergeToolCalls, parseToolArguments } from './lib/tools'
import {
  findPatientByName,
  readActivePatientId,
  resolveActivePatientId,
  saveActivePatientId,
} from './lib/patients'
import { downloadChatExport } from './lib/export'
import { isFocusComposerHotkey } from './lib/hotkeys'
import { watchTheme } from './lib/theme'
import { errorMessage, isAbortError, isRecord, uid } from './lib/utils'
import { Sidebar } from './components/Sidebar'
import { MessageBubble } from './components/MessageBubble'
import { Composer } from './components/Composer'
import { Welcome } from './components/Welcome'
import { AuthScreen } from './components/AuthScreen'
import { ChangePasswordDialog } from './components/ChangePasswordDialog'
import { SettingsDialog } from './components/SettingsDialog'
import { PatientCardDialog } from './components/PatientCardDialog'
import { PwaInstallButton } from './components/PwaInstallButton'
import { AdminDashboard } from './components/AdminDashboard'
import { AdminI18nProvider } from './components/AdminI18nProvider'

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

function App() {
  const { t } = useTranslation()

  function apiStatusLabel(status: ApiStatus): string {
    if (status === 'online') {
      return t('app.apiOnline')
    }
    if (status === 'offline') {
      return t('app.apiOffline')
    }
    return t('app.apiChecking')
  }

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
  const [patients, setPatients] = useState<Patient[]>([])
  const [patientsLoading, setPatientsLoading] = useState(true)
  const [patientsError, setPatientsError] = useState<string | null>(null)
  const [activePatientId, setActivePatientId] = useState<number | null>(null)
  const [patientDialog, setPatientDialog] = useState<{
    patient: Patient | null
  } | null>(null)
  const [recordsLoading, setRecordsLoading] = useState(true)
  const [recordsError, setRecordsError] = useState<string | null>(null)
  const [passwordDialogOpen, setPasswordDialogOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [adminOpen, setAdminOpen] = useState(false)
  const [authNotice, setAuthNotice] = useState<string | null>(null)
  // Оценки ответов живут только в памяти: сервер — источник правды,
  // localStorage для них не используем.
  const [feedbackRatings, setFeedbackRatings] = useState<
    Record<string, FeedbackRating>
  >({})
  const [feedbackPending, setFeedbackPending] = useState<Record<string, boolean>>(
    {},
  )
  const [feedbackError, setFeedbackError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const shouldStickToBottom = useRef(true)
  const refreshedTokenRef = useRef<string | null>(null)

  const handleLogout = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    refreshedTokenRef.current = null
    setAuthToken(null)
    clearAuthSession()
    setSession(null)
    setMessages([])
    setInput('')
    setFeedbackRatings({})
    setFeedbackPending({})
    setFeedbackError(null)
    setAppointments([])
    setReminders([])
    setPatients([])
    setActivePatientId(null)
    setPatientDialog(null)
    setPatientsError(null)
    setPatientsLoading(true)
    setRecordsError(null)
    setRecordsLoading(true)
    setSidebarOpen(false)
    setPasswordDialogOpen(false)
    setSettingsOpen(false)
    setAdminOpen(false)
  }, [])

  const handleAuthenticated = useCallback((next: AuthSession) => {
    setAuthToken(next.access_token)
    saveAuthSession(next)
    setSession(next)
    setMessages(loadStoredMessages(next.user.id))
    setFeedbackRatings({})
    setFeedbackPending({})
    setFeedbackError(null)
    setRecordsLoading(true)
    setRecordsError(null)
    setAuthNotice(null)
    setSidebarOpen(false)
  }, [])

  const handlePasswordChanged = useCallback(() => {
    setAuthNotice(t('app.passwordChanged'))
    handleLogout()
  }, [handleLogout, t])

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

  const refreshPatients = useCallback(
    async (options?: { selectName?: string }) => {
      if (!session) {
        return
      }
      setPatientsLoading(true)
      try {
        const next = await fetchPatients()
        setPatients(next)
        setPatientsError(null)

        if (options?.selectName) {
          const created = findPatientByName(next, options.selectName)
          if (created) {
            setActivePatientId(created.id)
            saveActivePatientId(session.user.id, created.id)
            return
          }
        }

        setActivePatientId((previous) => {
          const stored = previous ?? readActivePatientId(session.user.id)
          const resolved = resolveActivePatientId(stored, next)
          if (resolved !== stored) {
            saveActivePatientId(session.user.id, resolved)
          }
          return resolved
        })
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          handleLogout()
          return
        }
        if (!isAbortError(error)) {
          setPatientsError(errorMessage(error))
        }
      } finally {
        setPatientsLoading(false)
      }
    },
    [session, handleLogout],
  )

  useEffect(() => {
    if (!session) {
      return
    }
    // oxlint-disable-next-line react/set-state-in-effect
    setActivePatientId(readActivePatientId(session.user.id))
    void refreshPatients()
  }, [session, refreshPatients])

  useEffect(() => {
    setAuthToken(session?.access_token ?? null)
    if (session) {
      // Держим localStorage в актуальном состоянии после /auth/me:
      // старые сессии могли быть сохранены до появления is_admin.
      saveAuthSession(session)
    }
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
    const token = session?.access_token
    if (!token || refreshedTokenRef.current === token) {
      return
    }
    // Один refresh на токен: логин/старая сессия из localStorage. Результат
    // /auth/me обязательно применяем к session, иначе is_admin из БД не
    // доедет до Sidebar (баг: ответ запроса раньше игнорировался).
    refreshedTokenRef.current = token
    let active = true

    void fetchCurrentUser(token)
      .then((user) => {
        if (!active) {
          return
        }
        setSession((previous) => {
          if (!previous || previous.access_token !== token) {
            return previous
          }
          return { ...previous, user }
        })
      })
      .catch((error: unknown) => {
        if (!active) {
          return
        }
        if (error instanceof ApiError && error.status === 401) {
          handleLogout()
        } else {
          // Сеть/5xx: попробуем снова при следующем изменении сессии.
          refreshedTokenRef.current = null
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
    // Глобальные хоткеи (T-154.2): Ctrl/Cmd+K — фокус на вводе, Esc — drawer.
    // Модалки (настройки, смена пароля) обрабатывают Esc сами.
    const stopWatchingTheme = watchTheme()

    function handleKeyDown(event: KeyboardEvent) {
      if (isFocusComposerHotkey(event)) {
        if (settingsOpen || passwordDialogOpen) {
          return
        }
        event.preventDefault()
        setSidebarOpen(false)
        composerRef.current?.focus()
        return
      }
      if (event.key === 'Escape' && sidebarOpen) {
        setSidebarOpen(false)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      stopWatchingTheme()
    }
  }, [passwordDialogOpen, settingsOpen, sidebarOpen])

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
        patientId: activePatientId,
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
        throw new ApiError(t('app.emptyResponse'))
      }

      patchMessage(assistantId, { content, toolCalls, status: 'done' })

      if (toolCalls.length > 0) {
        void loadRecords()
        const created = toolCalls.find(
          (call) => call.function.name === 'create_patient',
        )
        if (created) {
          const args = parseToolArguments(created.function.arguments)
          const name = typeof args.name === 'string' ? args.name : ''
          void refreshPatients({ selectName: name })
        }
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
            error instanceof Error ? error.message : t('app.responseError'),
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
    setFeedbackRatings({})
    setFeedbackPending({})
    setFeedbackError(null)
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

  const handleFeedback = useCallback(
    async (messageId: string, rating: FeedbackRating) => {
      setFeedbackPending((previous) => ({ ...previous, [messageId]: true }))
      setFeedbackError(null)
      try {
        await submitFeedback(messageId, rating)
        // Сервер подтвердил оценку — фиксируем её в интерфейсе.
        setFeedbackRatings((previous) => ({ ...previous, [messageId]: rating }))
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          handleLogout()
          return
        }
        // Не блокируем чат: показываем небольшую ошибку и оставляем
        // прежнюю оценку, если она была.
        setFeedbackError(
          t('app.feedbackError', { error: errorMessage(error) }),
        )
      } finally {
        setFeedbackPending((previous) => {
          const next = { ...previous }
          delete next[messageId]
          return next
        })
      }
    },
    [handleLogout, t],
  )

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
    return (
      <AdminI18nProvider>
        <AdminDashboard onClose={() => setAdminOpen(false)} />
      </AdminI18nProvider>
    )
  }

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-app text-ink">
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
        patients={patients}
        patientsLoading={patientsLoading}
        patientsError={patientsError}
        activePatientId={activePatientId}
        onSelectPatient={(patientId) => {
          setActivePatientId(patientId)
          if (session) {
            saveActivePatientId(session.user.id, patientId)
          }
        }}
        onOpenPatientCard={() => {
          const active =
            patients.find((patient) => patient.id === activePatientId) ?? null
          if (active) {
            setPatientDialog({ patient: active })
          } else {
            setPatientDialog({ patient: null })
          }
        }}
        onCreatePatient={() => setPatientDialog({ patient: null })}
        onRefreshPatients={() => {
          void refreshPatients()
        }}
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
          setSettingsOpen(true)
        }}
        onLogout={handleLogout}
      />

      {settingsOpen && (
        <SettingsDialog
          onClose={() => setSettingsOpen(false)}
          onOpenPasswordChange={() => {
            setSettingsOpen(false)
            setPasswordDialogOpen(true)
          }}
        />
      )}

      {passwordDialogOpen && (
        <ChangePasswordDialog
          onClose={() => setPasswordDialogOpen(false)}
          onPasswordChanged={handlePasswordChanged}
        />
      )}

      {patientDialog && (
        <PatientCardDialog
          key={patientDialog.patient?.id ?? 'new-patient'}
          patient={patientDialog.patient}
          onClose={() => setPatientDialog(null)}
          onSaved={(saved) => {
            setPatientDialog(null)
            setActivePatientId(saved.id)
            if (session) {
              saveActivePatientId(session.user.id, saved.id)
            }
            void refreshPatients()
          }}
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line-soft bg-app/95 px-3 backdrop-blur sm:px-4 lg:px-6">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            aria-label={t('app.openMenu')}
            className="rounded-lg p-1.5 text-ink-soft transition-colors hover:bg-hover hover:text-ink-strong md:hidden"
          >
            <Menu className="h-5 w-5" />
          </button>

          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="truncate text-[13px] font-semibold tracking-tight text-ink">
                {t('app.title')}
              </h1>
              <span className="hidden rounded-full border border-emerald-500/20 bg-emerald-500/[0.07] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-accent sm:inline">
                vet
              </span>
            </div>
            <p className="truncate text-[10.5px] text-ink-muted">
              {t('app.subtitle')}
            </p>
          </div>

          <div className="ml-auto flex items-center gap-1.5">
            {settings.useRag && (
              <span className="hidden items-center gap-1 rounded-full border border-line bg-tint px-2 py-1 text-[9.5px] font-medium text-ink-soft md:inline-flex">
                <BookOpen className="h-3 w-3 text-accent-icon/80" />
                RAG
              </span>
            )}
            {settings.useTools && (
              <span className="hidden items-center gap-1 rounded-full border border-line bg-tint px-2 py-1 text-[9.5px] font-medium text-ink-soft md:inline-flex">
                <Wrench className="h-3 w-3 text-warn-icon/80" />
                Tools
              </span>
            )}
            <PwaInstallButton />

            <div
              title={apiStatusLabel(apiStatus)}
              className="flex items-center gap-1.5 rounded-full border border-line bg-tint px-2.5 py-1 text-[10px] text-ink-soft"
            >
              {apiStatus === 'checking' ? (
                <Loader2 className="h-3 w-3 animate-spin text-warn-icon" />
              ) : apiStatus === 'online' ? (
                <Wifi className="h-3 w-3 text-accent-icon" />
              ) : (
                <WifiOff className="h-3 w-3 text-danger-icon" />
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
                  <MessageBubble
                    key={message.id}
                    message={message}
                    rating={feedbackRatings[message.id] ?? null}
                    feedbackPending={Boolean(feedbackPending[message.id])}
                    onFeedback={
                      message.role === 'assistant'
                        ? (rating) => {
                            void handleFeedback(message.id, rating)
                          }
                        : undefined
                    }
                  />
                ))}
                <div className="h-1" />
              </div>
            )}
          </div>
        </main>

        {feedbackError && (
          <div
            role="alert"
            className="mx-auto w-full max-w-3xl px-4 pb-1 sm:px-6"
          >
            <div className="flex w-full items-start gap-2 rounded-xl border border-rose-500/20 bg-rose-500/[0.07] px-3 py-2 text-[11.5px] leading-4 text-danger">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span className="min-w-0 flex-1">{feedbackError}</span>
              <button
                type="button"
                onClick={() => setFeedbackError(null)}
                aria-label={t('app.hideError')}
                className="shrink-0 rounded p-0.5 text-danger/70 transition-colors hover:bg-rose-500/10 hover:text-danger-strong"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        )}

        <Composer
          value={input}
          onChange={setInput}
          onSend={() => {
            void sendMessage(input)
          }}
          onStop={handleStop}
          isStreaming={isStreaming}
          inputRef={composerRef}
        />
      </div>
    </div>
  )
}

export default App

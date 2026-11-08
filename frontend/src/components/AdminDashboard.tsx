import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  Check,
  ClipboardList,
  Copy,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Users,
  X,
} from 'lucide-react'
import type { AccessRequestStatus, AdminAccessRequest } from '../types'
import {
  approveAdminAccessRequest,
  fetchAdminAccessRequests,
  rejectAdminAccessRequest,
} from '../lib/api'
import { formatDateTime } from '../lib/format'
import { errorMessage } from '../lib/utils'
import { AdminAnalytics } from './AdminAnalytics'
import { AdminUsers } from './AdminUsers'

interface AdminDashboardProps {
  onClose: () => void
}

type Filter = AccessRequestStatus | 'all'

type AdminTab = 'requests' | 'users' | 'analytics'

const TABS: { value: AdminTab; label: string; icon: typeof ClipboardList }[] = [
  { value: 'requests', label: 'Заявки', icon: ClipboardList },
  { value: 'users', label: 'Пользователи', icon: Users },
  { value: 'analytics', label: 'Аналитика', icon: Activity },
]

const FILTERS: { value: Filter; label: string }[] = [
  { value: 'pending', label: 'Ожидают' },
  { value: 'approved', label: 'Одобрены' },
  { value: 'rejected', label: 'Отклонены' },
  { value: 'all', label: 'Все' },
]

function statusBadge(status: AccessRequestStatus) {
  if (status === 'approved') {
    return 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300'
  }
  if (status === 'rejected') {
    return 'border-rose-500/25 bg-rose-500/10 text-rose-300'
  }
  return 'border-amber-500/25 bg-amber-500/10 text-amber-300'
}

function statusLabel(status: AccessRequestStatus): string {
  if (status === 'approved') {
    return 'Одобрена'
  }
  if (status === 'rejected') {
    return 'Отклонена'
  }
  return 'Ожидает'
}

export function AdminDashboard({ onClose }: AdminDashboardProps) {
  const [tab, setTab] = useState<AdminTab>('requests')
  const [filter, setFilter] = useState<Filter>('pending')
  const [requests, setRequests] = useState<AdminAccessRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [approveTarget, setApproveTarget] = useState<AdminAccessRequest | null>(
    null,
  )
  const [rejectTarget, setRejectTarget] = useState<AdminAccessRequest | null>(
    null,
  )
  const [rejectionReason, setRejectionReason] = useState('')
  const [actionLoading, setActionLoading] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const [issued, setIssued] = useState<{ email: string; password: string } | null>(
    null,
  )
  const [copied, setCopied] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setRequests(await fetchAdminAccessRequests(filter))
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => {
    // Загрузка списка заявок при смене фильтра.
    // oxlint-disable-next-line react/set-state-in-effect
    void load()
  }, [load])

  function closeActionDialogs() {
    setApproveTarget(null)
    setRejectTarget(null)
    setRejectionReason('')
    setActionError(null)
  }

  async function handleApprove() {
    if (!approveTarget) {
      return
    }
    setActionLoading(true)
    setActionError(null)
    try {
      const result = await approveAdminAccessRequest(approveTarget.id)
      setIssued({ email: result.email, password: result.temp_password })
      setApproveTarget(null)
      await load()
    } catch (requestError) {
      setActionError(errorMessage(requestError))
    } finally {
      setActionLoading(false)
    }
  }

  async function handleReject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!rejectTarget) {
      return
    }
    if (!rejectionReason.trim()) {
      setActionError('Укажите причину отказа.')
      return
    }
    setActionLoading(true)
    setActionError(null)
    try {
      await rejectAdminAccessRequest(rejectTarget.id, rejectionReason.trim())
      closeActionDialogs()
      await load()
    } catch (requestError) {
      setActionError(errorMessage(requestError))
    } finally {
      setActionLoading(false)
    }
  }

  async function copyPassword() {
    if (!issued) {
      return
    }
    try {
      await navigator.clipboard.writeText(issued.password)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setActionError('Не удалось скопировать — выделите пароль вручную.')
    }
  }

  return (
    <div className="min-h-dvh w-full bg-[#212121] text-zinc-100">
      <header className="sticky top-0 z-10 border-b border-white/[0.07] bg-[#212121]/95 backdrop-blur">
        <div className="mx-auto flex w-full max-w-5xl items-center gap-3 px-4 py-3 sm:px-6">
          <button
            type="button"
            onClick={onClose}
            aria-label="Назад к чату"
            className="rounded-lg p-1.5 text-zinc-400 transition-colors hover:bg-white/5 hover:text-white"
          >
            <ArrowLeft className="h-5 w-5" />
          </button>
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-300">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-[15px] font-semibold text-white">
              Администрирование
            </h1>
            <p className="truncate text-[11px] text-zinc-500">
              {tab === 'analytics'
                ? 'Использование модели и RAG'
                : tab === 'users'
                  ? 'Блокировка и удаление аккаунтов'
                  : 'Заявки на доступ к сервису'}
            </p>
          </div>
          {tab === 'requests' && (
            <button
              type="button"
              onClick={() => void load()}
              disabled={loading}
              aria-label="Обновить"
              className="flex items-center gap-2 rounded-lg border border-white/10 px-2.5 py-1.5 text-[11.5px] text-zinc-300 transition-colors hover:bg-white/5 disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
              <span className="hidden sm:inline">Обновить</span>
            </button>
          )}
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl px-4 py-5 sm:px-6 sm:py-7">
        <nav
          aria-label="Разделы админ-панели"
          className="mb-4 flex gap-1.5 rounded-xl border border-white/10 bg-white/[0.02] p-1"
        >
          {TABS.map((item) => {
            const Icon = item.icon
            return (
              <button
                key={item.value}
                type="button"
                aria-current={tab === item.value ? 'page' : undefined}
                onClick={() => setTab(item.value)}
                className={`flex flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2 text-[12.5px] font-medium transition-colors ${
                  tab === item.value
                    ? 'bg-emerald-500 text-emerald-950'
                    : 'text-zinc-400 hover:bg-white/5 hover:text-zinc-200'
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {item.label}
              </button>
            )
          })}
        </nav>

        {tab === 'analytics' ? (
          <AdminAnalytics />
        ) : tab === 'users' ? (
          <AdminUsers />
        ) : (
          <>
            <div className="mb-4 flex flex-wrap gap-1.5">
              {FILTERS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => setFilter(item.value)}
                  className={`rounded-lg px-3 py-1.5 text-[12px] font-medium transition-colors ${
                    filter === item.value
                      ? 'bg-emerald-500 text-emerald-950'
                      : 'border border-white/10 text-zinc-400 hover:bg-white/5 hover:text-zinc-200'
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>

            {error && (
              <div
                role="alert"
                className="mb-4 rounded-xl border border-rose-500/20 bg-rose-500/[0.07] px-3.5 py-3 text-[12.5px] text-rose-300"
              >
                {error}
              </div>
            )}

            {loading ? (
              <div className="flex items-center justify-center gap-2 rounded-2xl border border-white/5 bg-white/[0.02] py-16 text-sm text-zinc-500">
                <Loader2 className="h-4 w-4 animate-spin" />
                Загружаю заявки…
              </div>
            ) : requests.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-white/10 py-16 text-center text-[13px] text-zinc-500">
                Заявок нет.
              </div>
            ) : (
              <div className="overflow-x-auto rounded-2xl border border-white/[0.07]">
                <table className="w-full min-w-[720px] border-collapse text-left">
                  <thead>
                    <tr className="border-b border-white/[0.07] bg-white/[0.02] text-[10.5px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
                      <th className="px-4 py-3">Email</th>
                      <th className="px-4 py-3">Причина</th>
                      <th className="px-4 py-3">Создана</th>
                      <th className="px-4 py-3">Статус</th>
                      <th className="px-4 py-3 text-right">Действия</th>
                    </tr>
                  </thead>
                  <tbody>
                    {requests.map((item) => (
                      <tr
                        key={item.id}
                        className="border-b border-white/[0.05] align-top text-[12.5px] last:border-b-0"
                      >
                        <td className="px-4 py-3 font-medium text-zinc-200">
                          {item.email}
                        </td>
                        <td className="max-w-[260px] px-4 py-3 text-zinc-400">
                          <span className="line-clamp-3">{item.reason}</span>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-zinc-500">
                          {formatDateTime(item.created_at)}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex rounded-full border px-2 py-0.5 text-[10.5px] font-medium ${statusBadge(item.status)}`}
                          >
                            {statusLabel(item.status)}
                          </span>
                          {item.rejection_reason && (
                            <p className="mt-1 max-w-[200px] text-[10.5px] leading-4 text-zinc-500">
                              {item.rejection_reason}
                            </p>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right">
                          {item.status === 'pending' ? (
                            <div className="flex justify-end gap-1.5">
                              <button
                                type="button"
                                onClick={() => {
                                  setApproveTarget(item)
                                  setActionError(null)
                                }}
                                className="rounded-lg bg-emerald-500/15 px-2.5 py-1.5 text-[11.5px] font-medium text-emerald-300 transition-colors hover:bg-emerald-500/25"
                              >
                                Approve
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  setRejectTarget(item)
                                  setRejectionReason('')
                                  setActionError(null)
                                }}
                                className="rounded-lg bg-rose-500/10 px-2.5 py-1.5 text-[11.5px] font-medium text-rose-300 transition-colors hover:bg-rose-500/20"
                              >
                                Reject
                              </button>
                            </div>
                          ) : (
                            <span className="text-[11px] text-zinc-600">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </main>

      {approveTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm">
          <div className="w-full max-w-[400px] rounded-2xl border border-white/10 bg-[#1b1b1b] p-5 shadow-2xl">
            <h2 className="text-[15px] font-semibold text-white">
              Одобрить заявку?
            </h2>
            <p className="mt-2 text-[12.5px] leading-5 text-zinc-400">
              Для <span className="text-zinc-200">{approveTarget.email}</span>{' '}
              будет создан аккаунт с временным паролем. Пароль покажется один
              раз — передайте его пользователю.
            </p>
            {actionError && (
              <p className="mt-3 rounded-lg border border-rose-500/20 bg-rose-500/[0.07] px-3 py-2 text-[12px] text-rose-300">
                {actionError}
              </p>
            )}
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                onClick={closeActionDialogs}
                disabled={actionLoading}
                className="flex-1 rounded-xl border border-white/10 px-4 py-2.5 text-[13px] text-zinc-300 hover:bg-white/5 disabled:opacity-50"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={() => void handleApprove()}
                disabled={actionLoading}
                className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-emerald-500 px-4 py-2.5 text-[13px] font-semibold text-emerald-950 hover:bg-emerald-400 disabled:opacity-60"
              >
                {actionLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Check className="h-4 w-4" />
                )}
                Одобрить
              </button>
            </div>
          </div>
        </div>
      )}

      {rejectTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm">
          <form
            onSubmit={(event) => void handleReject(event)}
            className="w-full max-w-[420px] rounded-2xl border border-white/10 bg-[#1b1b1b] p-5 shadow-2xl"
          >
            <h2 className="text-[15px] font-semibold text-white">
              Отклонить заявку
            </h2>
            <p className="mt-1 text-[12px] text-zinc-500">
              {rejectTarget.email}
            </p>
            <label className="mt-3 block">
              <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-zinc-500">
                Причина
              </span>
              <textarea
                autoFocus
                required
                rows={3}
                maxLength={500}
                value={rejectionReason}
                onChange={(event) => setRejectionReason(event.target.value)}
                placeholder="Почему заявка отклонена"
                className="w-full resize-none rounded-xl border border-white/10 bg-black/25 px-3 py-2.5 text-[13.5px] text-zinc-100 outline-none placeholder:text-zinc-600 focus:border-emerald-500/40"
              />
            </label>
            {actionError && (
              <p className="mt-2 rounded-lg border border-rose-500/20 bg-rose-500/[0.07] px-3 py-2 text-[12px] text-rose-300">
                {actionError}
              </p>
            )}
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                onClick={closeActionDialogs}
                disabled={actionLoading}
                className="flex-1 rounded-xl border border-white/10 px-4 py-2.5 text-[13px] text-zinc-300 hover:bg-white/5 disabled:opacity-50"
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={actionLoading}
                className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-rose-500 px-4 py-2.5 text-[13px] font-semibold text-rose-950 hover:bg-rose-400 disabled:opacity-60"
              >
                {actionLoading && <Loader2 className="h-4 w-4 animate-spin" />}
                Отклонить
              </button>
            </div>
          </form>
        </div>
      )}

      {issued && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/75 px-4 backdrop-blur-sm">
          <div className="w-full max-w-[440px] rounded-2xl border border-emerald-500/20 bg-[#1b1b1b] p-5 shadow-2xl">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-300">
                <ShieldCheck className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <h2 className="text-[15px] font-semibold text-white">
                  Пользователь создан
                </h2>
                <p className="mt-0.5 text-[11.5px] text-zinc-500">
                  {issued.email}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIssued(null)}
                aria-label="Закрыть"
                className="rounded-lg p-1.5 text-zinc-500 hover:bg-white/5 hover:text-zinc-200"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-4 flex items-start gap-2 rounded-xl border border-amber-500/25 bg-amber-500/[0.08] px-3 py-2.5 text-[11.5px] leading-4 text-amber-200">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              Показывается один раз. Скопируйте пароль и передайте пользователю.
            </div>

            <div className="mt-3 flex items-center gap-2 rounded-xl border border-white/10 bg-black/30 px-3 py-2.5">
              <code className="min-w-0 flex-1 break-all font-mono text-[13px] text-emerald-300">
                {issued.password}
              </code>
              <button
                type="button"
                onClick={() => void copyPassword()}
                className="flex shrink-0 items-center gap-1.5 rounded-lg bg-white/5 px-2.5 py-1.5 text-[11.5px] text-zinc-200 hover:bg-white/10"
              >
                {copied ? (
                  <Check className="h-3.5 w-3.5 text-emerald-400" />
                ) : (
                  <Copy className="h-3.5 w-3.5" />
                )}
                {copied ? 'Скопировано' : 'Скопировать'}
              </button>
            </div>

            {actionError && (
              <p className="mt-2 text-[11.5px] text-rose-300">{actionError}</p>
            )}

            <button
              type="button"
              onClick={() => {
                setIssued(null)
                setCopied(false)
              }}
              className="mt-4 w-full rounded-xl bg-emerald-500 px-4 py-2.5 text-[13px] font-semibold text-emerald-950 hover:bg-emerald-400"
            >
              Готово
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

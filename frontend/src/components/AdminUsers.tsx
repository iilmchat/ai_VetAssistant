import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Loader2,
  RefreshCw,
  Search,
  Trash2,
  UserCheck,
  X,
} from 'lucide-react'
import type { AdminUser, AdminUserList, AdminUserStatus } from '../types'
import {
  blockAdminUser,
  deleteAdminUser,
  fetchAdminUsers,
  unblockAdminUser,
} from '../lib/api'
import { formatDateTime } from '../lib/format'
import { errorMessage } from '../lib/utils'

const PAGE_SIZE = 20

const STATUS_FILTERS: { value: AdminUserStatus; label: string }[] = [
  { value: 'all', label: 'Все' },
  { value: 'active', label: 'Активные' },
  { value: 'blocked', label: 'Заблокированные' },
]

function statusBadge(active: boolean): string {
  return active
    ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300'
    : 'border-rose-500/25 bg-rose-500/10 text-rose-300'
}

export function AdminUsers() {
  const [searchInput, setSearchInput] = useState('')
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<AdminUserStatus>('all')
  const [page, setPage] = useState(0)
  const [data, setData] = useState<AdminUserList | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const [blockTarget, setBlockTarget] = useState<AdminUser | null>(null)
  const [unblockTarget, setUnblockTarget] = useState<AdminUser | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null)
  const [reason, setReason] = useState('')
  const [confirmEmail, setConfirmEmail] = useState('')
  const [actionLoading, setActionLoading] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(searchInput.trim())
      setPage(0)
    }, 300)
    return () => window.clearTimeout(timer)
  }, [searchInput])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(
        await fetchAdminUsers({
          query,
          status,
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
        }),
      )
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setLoading(false)
    }
  }, [query, status, page])

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    void load()
  }, [load])

  function closeDialogs() {
    setBlockTarget(null)
    setUnblockTarget(null)
    setDeleteTarget(null)
    setReason('')
    setConfirmEmail('')
    setActionError(null)
  }

  function openBlock(user: AdminUser) {
    setBlockTarget(user)
    setReason('')
    setActionError(null)
  }

  function openUnblock(user: AdminUser) {
    setUnblockTarget(user)
    setReason('')
    setActionError(null)
  }

  function openDelete(user: AdminUser) {
    setDeleteTarget(user)
    setReason('')
    setConfirmEmail('')
    setActionError(null)
  }

  async function handleBlock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!blockTarget) {
      return
    }
    const trimmed = reason.trim()
    if (!trimmed) {
      setActionError('Укажите причину блокировки.')
      return
    }

    const email = blockTarget.email
    setActionLoading(true)
    setActionError(null)
    try {
      await blockAdminUser(blockTarget.id, trimmed)
      closeDialogs()
      await load()
      setNotice(`Пользователь ${email} заблокирован.`)
    } catch (requestError) {
      setActionError(errorMessage(requestError))
    } finally {
      setActionLoading(false)
    }
  }

  async function handleUnblock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!unblockTarget) {
      return
    }
    const trimmed = reason.trim()
    if (!trimmed) {
      setActionError('Укажите причину разблокировки.')
      return
    }

    const email = unblockTarget.email
    setActionLoading(true)
    setActionError(null)
    try {
      await unblockAdminUser(unblockTarget.id, trimmed)
      closeDialogs()
      await load()
      setNotice(`Пользователь ${email} разблокирован.`)
    } catch (requestError) {
      setActionError(errorMessage(requestError))
    } finally {
      setActionLoading(false)
    }
  }

  async function handleDelete(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!deleteTarget) {
      return
    }
    const expectedEmail = deleteTarget.email.trim().toLowerCase()
    if (confirmEmail.trim().toLowerCase() !== expectedEmail) {
      setActionError('Email не совпадает с email пользователя.')
      return
    }

    const targetId = deleteTarget.id
    const email = deleteTarget.email
    const lastOnPage = (data?.items.length ?? 0) === 1 && page > 0
    setActionLoading(true)
    setActionError(null)
    try {
      await deleteAdminUser(targetId, confirmEmail.trim(), reason)
      closeDialogs()
      if (lastOnPage) {
        setPage((current) => Math.max(0, current - 1))
      } else {
        await load()
      }
      setNotice(`Пользователь ${email} удалён.`)
    } catch (requestError) {
      setActionError(errorMessage(requestError))
    } finally {
      setActionLoading(false)
    }
  }

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const deleteEmailMatches =
    deleteTarget !== null &&
    confirmEmail.trim().toLowerCase() ===
      deleteTarget.email.trim().toLowerCase()

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-500" />
          <input
            type="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            aria-label="Поиск пользователей по email"
            placeholder="Поиск по email"
            className="w-full rounded-xl border border-white/10 bg-white/[0.02] py-2 pl-9 pr-3 text-[12.5px] text-zinc-200 outline-none placeholder:text-zinc-600 focus:border-emerald-500/40"
          />
        </div>

        <div className="flex rounded-xl border border-white/10 bg-white/[0.02] p-1">
          {STATUS_FILTERS.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => {
                setStatus(item.value)
                setPage(0)
                setNotice(null)
              }}
              className={`rounded-lg px-3 py-1.5 text-[12px] font-medium transition-colors ${
                status === item.value
                  ? 'bg-emerald-500 text-emerald-950'
                  : 'text-zinc-400 hover:bg-white/5 hover:text-zinc-200'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-white/10 px-2.5 py-1.5 text-[11.5px] text-zinc-300 transition-colors hover:bg-white/5 disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          Обновить
        </button>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-4 flex items-start gap-2 rounded-xl border border-rose-500/20 bg-rose-500/[0.07] px-3.5 py-3 text-[12.5px] text-rose-300"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {error}
        </div>
      )}

      {notice && (
        <div className="mb-4 flex items-center gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.07] px-3.5 py-3 text-[12.5px] text-emerald-300">
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0 flex-1">{notice}</span>
          <button
            type="button"
            onClick={() => setNotice(null)}
            aria-label="Скрыть сообщение"
            className="rounded p-0.5 text-emerald-400/70 hover:bg-white/5 hover:text-emerald-200"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center gap-2 rounded-2xl border border-white/5 bg-white/[0.02] py-16 text-sm text-zinc-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          Загружаю пользователей…
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-white/10 py-16 text-center text-[13px] text-zinc-500">
          Пользователи не найдены.
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-2xl border border-white/[0.07]">
            <table className="w-full min-w-[760px] border-collapse text-left">
              <thead>
                <tr className="border-b border-white/[0.07] bg-white/[0.02] text-[10.5px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
                  <th className="px-4 py-3">Email</th>
                  <th className="px-4 py-3">Регистрация</th>
                  <th className="px-4 py-3">Статус</th>
                  <th className="px-4 py-3 text-right">Действия</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr
                    key={item.id}
                    className="border-b border-white/[0.05] align-middle text-[12.5px] last:border-b-0"
                  >
                    <td className="px-4 py-3 font-medium text-zinc-200">
                      <div className="flex flex-wrap items-center gap-2">
                        <span>{item.email}</span>
                        {item.is_admin && (
                          <span className="rounded border border-amber-500/25 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-300">
                            админ
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-zinc-500">
                      {formatDateTime(item.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex rounded-full border px-2 py-0.5 text-[10.5px] font-medium ${statusBadge(item.is_active)}`}
                      >
                        {item.is_active ? 'Активен' : 'Заблокирован'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex justify-end gap-1.5">
                        {item.is_active ? (
                          <button
                            type="button"
                            onClick={() => openBlock(item)}
                            className="inline-flex items-center gap-1.5 rounded-lg bg-rose-500/10 px-2.5 py-1.5 text-[11.5px] font-medium text-rose-300 transition-colors hover:bg-rose-500/20"
                          >
                            <Ban className="h-3.5 w-3.5" />
                            Заблокировать
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => openUnblock(item)}
                            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500/15 px-2.5 py-1.5 text-[11.5px] font-medium text-emerald-300 transition-colors hover:bg-emerald-500/25"
                          >
                            <UserCheck className="h-3.5 w-3.5" />
                            Разблокировать
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => openDelete(item)}
                          className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-[11.5px] text-zinc-400 transition-colors hover:bg-white/5 hover:text-rose-300"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          Удалить
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
            <p className="text-[11.5px] text-zinc-500">Всего: {total}</p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setPage((current) => Math.max(0, current - 1))}
                disabled={page === 0 || loading}
                className="rounded-lg border border-white/10 px-2.5 py-1.5 text-[11.5px] text-zinc-300 hover:bg-white/5 disabled:opacity-40"
              >
                Назад
              </button>
              <span className="text-[11.5px] text-zinc-500">
                Стр. {Math.min(page + 1, totalPages)} из {totalPages}
              </span>
              <button
                type="button"
                onClick={() => setPage((current) => current + 1)}
                disabled={page + 1 >= totalPages || loading}
                className="rounded-lg border border-white/10 px-2.5 py-1.5 text-[11.5px] text-zinc-300 hover:bg-white/5 disabled:opacity-40"
              >
                Вперёд
              </button>
            </div>
          </div>
        </>
      )}

      {blockTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm">
          <form
            onSubmit={(event) => void handleBlock(event)}
            className="w-full max-w-[420px] rounded-2xl border border-white/10 bg-[#1b1b1b] p-5 shadow-2xl"
          >
            <h2 className="text-[15px] font-semibold text-white">
              Заблокировать пользователя?
            </h2>
            <p className="mt-1 text-[12px] text-zinc-500">
              {blockTarget.email}
            </p>
            <p className="mt-2 text-[12px] leading-5 text-zinc-400">
              Действующий токен перестанет работать сразу, а вход будет
              отклонён с 403.
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
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="Почему пользователь заблокирован"
                className="w-full resize-none rounded-xl border border-white/10 bg-black/25 px-3 py-2.5 text-[13.5px] text-zinc-100 outline-none placeholder:text-zinc-600 focus:border-rose-500/40"
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
                onClick={closeDialogs}
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
                {actionLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Ban className="h-4 w-4" />
                )}
                Заблокировать
              </button>
            </div>
          </form>
        </div>
      )}

      {unblockTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm">
          <form
            onSubmit={(event) => void handleUnblock(event)}
            className="w-full max-w-[420px] rounded-2xl border border-white/10 bg-[#1b1b1b] p-5 shadow-2xl"
          >
            <h2 className="text-[15px] font-semibold text-white">
              Разблокировать пользователя?
            </h2>
            <p className="mt-1 text-[12px] text-zinc-500">
              {unblockTarget.email}
            </p>
            <p className="mt-2 text-[12px] leading-5 text-zinc-400">
              Пользователь снова сможет войти и пользоваться сервисом.
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
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="Почему доступ возвращён"
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
                onClick={closeDialogs}
                disabled={actionLoading}
                className="flex-1 rounded-xl border border-white/10 px-4 py-2.5 text-[13px] text-zinc-300 hover:bg-white/5 disabled:opacity-50"
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={actionLoading}
                className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-emerald-500 px-4 py-2.5 text-[13px] font-semibold text-emerald-950 hover:bg-emerald-400 disabled:opacity-60"
              >
                {actionLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <UserCheck className="h-4 w-4" />
                )}
                Разблокировать
              </button>
            </div>
          </form>
        </div>
      )}

      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4 backdrop-blur-sm">
          <form
            onSubmit={(event) => void handleDelete(event)}
            className="w-full max-w-[440px] rounded-2xl border border-white/10 bg-[#1b1b1b] p-5 shadow-2xl"
          >
            <h2 className="text-[15px] font-semibold text-white">
              Удалить пользователя?
            </h2>
            <p className="mt-1 text-[12px] text-zinc-500">
              {deleteTarget.email}
            </p>
            <div className="mt-2 flex items-start gap-2 rounded-xl border border-rose-500/20 bg-rose-500/[0.07] px-3 py-2.5 text-[11.5px] leading-4 text-rose-200">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              Аккаунт, записи, напоминания и коды привязки будут удалены
              безвозвратно.
            </div>
            <label className="mt-3 block">
              <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-zinc-500">
                Введите email для подтверждения
              </span>
              <input
                autoFocus
                required
                value={confirmEmail}
                onChange={(event) => setConfirmEmail(event.target.value)}
                placeholder={deleteTarget.email}
                className="w-full rounded-xl border border-white/10 bg-black/25 px-3 py-2.5 text-[13.5px] text-zinc-100 outline-none placeholder:text-zinc-600 focus:border-rose-500/40"
              />
            </label>
            {confirmEmail && !deleteEmailMatches && (
              <p className="mt-1.5 text-[11px] text-rose-300">
                Email не совпадает.
              </p>
            )}
            <label className="mt-3 block">
              <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-zinc-500">
                Причина (необязательно)
              </span>
              <textarea
                rows={2}
                maxLength={500}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="Например, дубликат аккаунта"
                className="w-full resize-none rounded-xl border border-white/10 bg-black/25 px-3 py-2.5 text-[13.5px] text-zinc-100 outline-none placeholder:text-zinc-600 focus:border-rose-500/40"
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
                onClick={closeDialogs}
                disabled={actionLoading}
                className="flex-1 rounded-xl border border-white/10 px-4 py-2.5 text-[13px] text-zinc-300 hover:bg-white/5 disabled:opacity-50"
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={actionLoading || !deleteEmailMatches}
                className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-rose-500 px-4 py-2.5 text-[13px] font-semibold text-rose-950 hover:bg-rose-400 disabled:opacity-40"
              >
                {actionLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Trash2 className="h-4 w-4" />
                )}
                Удалить
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}

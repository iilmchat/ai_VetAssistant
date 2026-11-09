import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
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
import { LanguageSwitcher } from './LanguageSwitcher'

interface AdminDashboardProps {
  onClose: () => void
}

type Filter = AccessRequestStatus | 'all'

type AdminTab = 'requests' | 'users' | 'analytics'

const TABS: { value: AdminTab; labelKey: string; icon: typeof ClipboardList }[] = [
  { value: 'requests', labelKey: 'admin.tabs.requests', icon: ClipboardList },
  { value: 'users', labelKey: 'admin.tabs.users', icon: Users },
  { value: 'analytics', labelKey: 'admin.tabs.analytics', icon: Activity },
]

const FILTERS: { value: Filter; labelKey: string }[] = [
  { value: 'pending', labelKey: 'admin.filters.pending' },
  { value: 'approved', labelKey: 'admin.filters.approved' },
  { value: 'rejected', labelKey: 'admin.filters.rejected' },
  { value: 'all', labelKey: 'admin.filters.all' },
]

function statusBadge(status: AccessRequestStatus) {
  if (status === 'approved') {
    return 'border-emerald-500/25 bg-emerald-500/10 text-accent'
  }
  if (status === 'rejected') {
    return 'border-rose-500/25 bg-rose-500/10 text-danger'
  }
  return 'border-amber-500/25 bg-amber-500/10 text-warn'
}

function statusKey(status: AccessRequestStatus): string {
  return `admin.status.${status}`
}

export function AdminDashboard({ onClose }: AdminDashboardProps) {
  const { t, i18n } = useTranslation()
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
      setActionError(t('admin.reasonRequired'))
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
      setActionError(t('admin.copyFailed'))
    }
  }

  useEffect(() => {
    // T-154.2: Esc закрывает модальные окна админки.
    const hasDialog = Boolean(approveTarget || rejectTarget || issued)
    if (!hasDialog) {
      return
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Escape' || actionLoading) {
        return
      }
      setApproveTarget(null)
      setRejectTarget(null)
      setRejectionReason('')
      setActionError(null)
      setIssued(null)
      setCopied(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [actionLoading, approveTarget, issued, rejectTarget])

  return (
    <div className="min-h-dvh w-full bg-app text-ink">
      <header className="sticky top-0 z-10 border-b border-line-soft bg-app/95 backdrop-blur">
        <div className="mx-auto flex w-full max-w-5xl items-center gap-3 px-4 py-3 sm:px-6">
          <button
            type="button"
            onClick={onClose}
            aria-label={t('admin.back')}
            className="rounded-lg p-1.5 text-ink-soft transition-colors hover:bg-hover hover:text-ink-strong"
          >
            <ArrowLeft className="h-5 w-5" />
          </button>
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/15 text-accent">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-[15px] font-semibold text-ink-strong">
              {t('admin.title')}
            </h1>
            <p className="truncate text-[11px] text-ink-muted">
              {t(`admin.subtitles.${tab}`)}
            </p>
          </div>
          {tab === 'requests' && (
            <button
              type="button"
              onClick={() => void load()}
              disabled={loading}
              aria-label={t('admin.refresh')}
              className="flex items-center gap-2 rounded-lg border border-line px-2.5 py-1.5 text-[11.5px] text-ink-soft transition-colors hover:bg-hover disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
              <span className="hidden sm:inline">{t('admin.refresh')}</span>
            </button>
          )}
          <LanguageSwitcher />
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl px-4 py-5 sm:px-6 sm:py-7">
        <nav
          aria-label={t('admin.sectionsAria')}
          className="mb-4 flex gap-1.5 overflow-x-auto rounded-xl border border-line bg-tint p-1"
        >
          {TABS.map((item) => {
            const Icon = item.icon
            return (
              <button
                key={item.value}
                type="button"
                aria-current={tab === item.value ? 'page' : undefined}
                onClick={() => setTab(item.value)}
                className={`flex shrink-0 items-center justify-center gap-2 rounded-lg px-3 py-2 text-[12.5px] font-medium transition-colors sm:flex-1 ${
                  tab === item.value
                    ? 'bg-emerald-500 text-emerald-950'
                    : 'text-ink-soft hover:bg-hover hover:text-ink'
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {t(item.labelKey)}
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
                      : 'border border-line text-ink-soft hover:bg-hover hover:text-ink'
                  }`}
                >
                  {t(item.labelKey)}
                </button>
              ))}
            </div>

            {error && (
              <div
                role="alert"
                className="mb-4 rounded-xl border border-rose-500/20 bg-rose-500/[0.07] px-3.5 py-3 text-[12.5px] text-danger"
              >
                {error}
              </div>
            )}

            {loading ? (
              <div className="flex items-center justify-center gap-2 rounded-2xl border border-line-soft bg-tint py-16 text-sm text-ink-muted">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t('admin.loading')}
              </div>
            ) : requests.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-line py-16 text-center text-[13px] text-ink-muted">
                {t('admin.empty')}
              </div>
            ) : (
              <div className="overflow-x-auto rounded-2xl border border-line-soft">
                <table className="w-full min-w-[720px] border-collapse text-left">
                  <thead>
                    <tr className="border-b border-line-soft bg-tint text-[10.5px] font-semibold uppercase tracking-[0.12em] text-ink-muted">
                      <th className="px-4 py-3">{t('admin.table.email')}</th>
                      <th className="px-4 py-3">{t('admin.table.reason')}</th>
                      <th className="px-4 py-3">{t('admin.table.created')}</th>
                      <th className="px-4 py-3">{t('admin.table.status')}</th>
                      <th className="px-4 py-3 text-right">
                        {t('admin.table.actions')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {requests.map((item) => (
                      <tr
                        key={item.id}
                        className="border-b border-line-soft align-top text-[12.5px] last:border-b-0"
                      >
                        <td className="px-4 py-3 font-medium text-ink">
                          {item.email}
                        </td>
                        <td className="max-w-[260px] px-4 py-3 text-ink-soft">
                          <span className="line-clamp-3">{item.reason}</span>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-ink-muted">
                          {formatDateTime(item.created_at, i18n.language)}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex rounded-full border px-2 py-0.5 text-[10.5px] font-medium ${statusBadge(item.status)}`}
                          >
                            {t(statusKey(item.status))}
                          </span>
                          {item.rejection_reason && (
                            <p className="mt-1 max-w-[200px] text-[10.5px] leading-4 text-ink-muted">
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
                                className="rounded-lg bg-emerald-500/15 px-2.5 py-1.5 text-[11.5px] font-medium text-accent transition-colors hover:bg-emerald-500/25"
                              >
                                {t('admin.approve')}
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  setRejectTarget(item)
                                  setRejectionReason('')
                                  setActionError(null)
                                }}
                                className="rounded-lg bg-rose-500/10 px-2.5 py-1.5 text-[11.5px] font-medium text-danger transition-colors hover:bg-rose-500/20"
                              >
                                {t('admin.reject')}
                              </button>
                            </div>
                          ) : (
                            <span className="text-[11px] text-ink-faint">—</span>
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-overlay px-4 backdrop-blur-sm">
          <div className="w-full max-w-[400px] rounded-2xl border border-line bg-panel-2 p-5 shadow-2xl">
            <h2 className="text-[15px] font-semibold text-ink-strong">
              {t('admin.approveTitle')}
            </h2>
            <p className="mt-2 text-[12.5px] leading-5 text-ink-soft">
              {t('admin.approveBody', { email: approveTarget.email })}
            </p>
            {actionError && (
              <p className="mt-3 rounded-lg border border-rose-500/20 bg-rose-500/[0.07] px-3 py-2 text-[12px] text-danger">
                {actionError}
              </p>
            )}
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                onClick={closeActionDialogs}
                disabled={actionLoading}
                className="flex-1 rounded-xl border border-line px-4 py-2.5 text-[13px] text-ink-soft hover:bg-hover disabled:opacity-50"
              >
                {t('admin.cancel')}
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
                {t('admin.approve')}
              </button>
            </div>
          </div>
        </div>
      )}

      {rejectTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-overlay px-4 backdrop-blur-sm">
          <form
            onSubmit={(event) => void handleReject(event)}
            className="w-full max-w-[420px] rounded-2xl border border-line bg-panel-2 p-5 shadow-2xl"
          >
            <h2 className="text-[15px] font-semibold text-ink-strong">
              {t('admin.rejectTitle')}
            </h2>
            <p className="mt-1 text-[12px] text-ink-muted">
              {rejectTarget.email}
            </p>
            <label className="mt-3 block">
              <span className="mb-1.5 block text-[11px] font-medium uppercase tracking-wide text-ink-muted">
                {t('admin.reasonLabel')}
              </span>
              <textarea
                autoFocus
                required
                rows={3}
                maxLength={500}
                value={rejectionReason}
                onChange={(event) => setRejectionReason(event.target.value)}
                placeholder={t('admin.rejectReasonPlaceholder')}
                className="w-full resize-none rounded-xl border border-line bg-field px-3 py-2.5 text-[13.5px] text-ink outline-none placeholder:text-ink-faint focus:border-emerald-500/40"
              />
            </label>
            {actionError && (
              <p className="mt-2 rounded-lg border border-rose-500/20 bg-rose-500/[0.07] px-3 py-2 text-[12px] text-danger">
                {actionError}
              </p>
            )}
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                onClick={closeActionDialogs}
                disabled={actionLoading}
                className="flex-1 rounded-xl border border-line px-4 py-2.5 text-[13px] text-ink-soft hover:bg-hover disabled:opacity-50"
              >
                {t('admin.cancel')}
              </button>
              <button
                type="submit"
                disabled={actionLoading}
                className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-rose-500 px-4 py-2.5 text-[13px] font-semibold text-rose-950 hover:bg-rose-400 disabled:opacity-60"
              >
                {actionLoading && <Loader2 className="h-4 w-4 animate-spin" />}
                {t('admin.reject')}
              </button>
            </div>
          </form>
        </div>
      )}

      {issued && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-overlay px-4 backdrop-blur-sm">
          <div className="w-full max-w-[440px] rounded-2xl border border-emerald-500/20 bg-panel-2 p-5 shadow-2xl">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-500/15 text-accent">
                <ShieldCheck className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <h2 className="text-[15px] font-semibold text-ink-strong">
                  {t('admin.createdTitle')}
                </h2>
                <p className="mt-0.5 text-[11.5px] text-ink-muted">
                  {issued.email}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIssued(null)}
                aria-label={t('admin.close')}
                className="rounded-lg p-1.5 text-ink-muted hover:bg-hover hover:text-ink"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-4 flex items-start gap-2 rounded-xl border border-amber-500/25 bg-amber-500/[0.08] px-3 py-2.5 text-[11.5px] leading-4 text-warn-strong">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {t('admin.createdWarning')}
            </div>

            <div className="mt-3 flex items-center gap-2 rounded-xl border border-line bg-field px-3 py-2.5">
              <code className="min-w-0 flex-1 break-all font-mono text-[13px] text-accent">
                {issued.password}
              </code>
              <button
                type="button"
                onClick={() => void copyPassword()}
                className="flex shrink-0 items-center gap-1.5 rounded-lg bg-tint-2 px-2.5 py-1.5 text-[11.5px] text-ink hover:bg-hover-strong"
              >
                {copied ? (
                  <Check className="h-3.5 w-3.5 text-accent-icon" />
                ) : (
                  <Copy className="h-3.5 w-3.5" />
                )}
                {copied ? t('admin.copied') : t('admin.copy')}
              </button>
            </div>

            {actionError && (
              <p className="mt-2 text-[11.5px] text-danger">{actionError}</p>
            )}

            <button
              type="button"
              onClick={() => {
                setIssued(null)
                setCopied(false)
              }}
              className="mt-4 w-full rounded-xl bg-emerald-500 px-4 py-2.5 text-[13px] font-semibold text-emerald-950 hover:bg-emerald-400"
            >
              {t('admin.done')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Activity,
  AlertTriangle,
  Database,
  RefreshCw,
  Server,
} from 'lucide-react'
import type {
  AdminActivity,
  AdminActivityWindow,
  AdminMetrics,
  AdminMetricsWindow,
  FeedbackStats,
} from '../types'
import {
  fetchAdminActivity,
  fetchAdminMetrics,
  fetchFeedbackStats,
} from '../lib/api'
import { formatMetricValue, formatPercent, ragHitRate } from '../lib/metrics'
import { errorMessage } from '../lib/utils'
import { Sparkline } from './charts/Sparkline'

const WINDOWS: { value: AdminMetricsWindow; labelKey: string }[] = [
  { value: '24h', labelKey: 'analytics.windows.24h' },
  { value: '7d', labelKey: 'analytics.windows.7d' },
]

const ACTIVITY_WINDOWS: { value: AdminActivityWindow; labelKey: string }[] = [
  { value: '7d', labelKey: 'analytics.windows.7d' },
  { value: '30d', labelKey: 'analytics.windows.30d' },
]

const REFRESH_INTERVAL_MS = 60_000

interface KpiCardProps {
  label: string
  value: string
  hint: string
}

function KpiCard({ label, value, hint }: KpiCardProps) {
  return (
    <div className="rounded-2xl border border-white/[0.07] bg-white/[0.02] px-4 py-3">
      <p className="text-[10.5px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
        {label}
      </p>
      <p className="mt-1 text-[22px] font-semibold leading-7 text-zinc-100">
        {value}
      </p>
      <p className="mt-0.5 text-[11px] text-zinc-500">{hint}</p>
    </div>
  )
}

export function AdminAnalytics() {
  const { t } = useTranslation()
  const [window, setWindow] = useState<AdminMetricsWindow>('24h')
  const [metrics, setMetrics] = useState<AdminMetrics | null>(null)
  const [feedbackStats, setFeedbackStats] = useState<FeedbackStats | null>(null)
  // Активность пользователей живёт отдельно от метрик: своё окно, своё
  // состояние загрузки/ошибки, чтобы сбой одного запроса не ломал другой блок.
  const [activityWindow, setActivityWindow] = useState<AdminActivityWindow>('7d')
  const [activity, setActivity] = useState<AdminActivity | null>(null)
  const [activityLoading, setActivityLoading] = useState(true)
  const [activityError, setActivityError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    // Статистика оценок грузится параллельно с метриками: её сбой не должен
    // ломать остальную аналитику — просто покажем «—» в KPI-карточке.
    const statsPromise = fetchFeedbackStats().catch(() => null)
    try {
      setMetrics(await fetchAdminMetrics(window))
    } catch (requestError) {
      setError(errorMessage(requestError))
    } finally {
      setLoading(false)
    }
    setFeedbackStats(await statsPromise)
  }, [window])

  const loadActivity = useCallback(async () => {
    setActivityLoading(true)
    setActivityError(null)
    try {
      setActivity(await fetchAdminActivity(activityWindow))
    } catch (requestError) {
      setActivityError(errorMessage(requestError))
    } finally {
      setActivityLoading(false)
    }
  }, [activityWindow])

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    void load()
    const timer = globalThis.setInterval(() => {
      void load()
    }, REFRESH_INTERVAL_MS)
    return () => {
      globalThis.clearInterval(timer)
    }
  }, [load])

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    void loadActivity()
    const timer = globalThis.setInterval(() => {
      void loadActivity()
    }, REFRESH_INTERVAL_MS)
    return () => {
      globalThis.clearInterval(timer)
    }
  }, [loadActivity])

  const totals = metrics?.totals
  const hitRate = totals ? ragHitRate(totals) : 0
  const requestsSeries = metrics?.series.map((point) => point.requests) ?? []
  const tokensSeries = metrics?.series.map((point) => point.tokens) ?? []

  // Данные активности показываем только при живом источнике и непустом ряде.
  const activityStats =
    activity && activity.source === 'prometheus' && activity.series.length > 0
      ? activity
      : null
  const activityRequestsTotal =
    activityStats?.series.reduce((sum, point) => sum + point.requests, 0) ?? 0
  const refreshing = loading || activityLoading

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex rounded-xl border border-white/10 bg-white/[0.02] p-1">
          {WINDOWS.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => setWindow(item.value)}
              className={`rounded-lg px-3 py-1.5 text-[12px] font-medium transition-colors ${
                window === item.value
                  ? 'bg-emerald-500 text-emerald-950'
                  : 'text-zinc-400 hover:bg-white/5 hover:text-zinc-200'
              }`}
            >
              {t(item.labelKey)}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={() => {
            void load()
            void loadActivity()
          }}
          disabled={refreshing}
          className="ml-auto flex items-center gap-2 rounded-lg border border-white/10 px-2.5 py-1.5 text-[11.5px] text-zinc-300 transition-colors hover:bg-white/5 disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`} />
          {t('analytics.refresh')}
        </button>
      </div>

      {metrics && (
        <div className="mb-4 flex flex-wrap items-center gap-2 text-[11px] text-zinc-500">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 px-2 py-0.5">
            {metrics.source === 'prometheus' ? (
              <Server className="h-3 w-3" />
            ) : (
              <Database className="h-3 w-3" />
            )}
            {metrics.source === 'prometheus'
              ? t('analytics.sourcePrometheus')
              : t('analytics.sourceSinceStart')}
          </span>
          {metrics.degraded && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/25 bg-amber-500/[0.08] px-2 py-0.5 text-amber-200">
              <AlertTriangle className="h-3 w-3" />
              {t('analytics.degraded')}
            </span>
          )}
          <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 px-2 py-0.5">
            <Activity className="h-3 w-3" />
            {t('analytics.updatedEveryMinute')}
          </span>
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="mb-4 rounded-xl border border-rose-500/20 bg-rose-500/[0.07] px-3.5 py-3 text-[12.5px] text-rose-300"
        >
          {error}
        </div>
      )}

      {loading && !totals ? (
        <div className="flex items-center justify-center gap-2 rounded-2xl border border-white/5 bg-white/[0.02] py-16 text-sm text-zinc-500">
          <RefreshCw className="h-4 w-4 animate-spin" />
          {t('analytics.loading')}
        </div>
      ) : totals ? (
        <>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            <KpiCard
              label={t('analytics.requests')}
              value={formatMetricValue(totals.requests)}
              hint={t('analytics.requestsHint', {
                value: formatMetricValue(totals.generation_errors),
              })}
            />
            <KpiCard
              label={t('analytics.tokens')}
              value={formatMetricValue(totals.tokens)}
              hint={t('analytics.tokensHint', {
                prompt: formatMetricValue(totals.prompt_tokens),
                completion: formatMetricValue(totals.completion_tokens),
              })}
            />
            <KpiCard
              label={t('analytics.ragHitRate')}
              value={formatPercent(hitRate)}
              hint={t('analytics.ragHint', {
                value: formatMetricValue(
                  totals.rag_hits + totals.rag_misses + totals.rag_errors,
                ),
              })}
            />
            <KpiCard
              label={t('analytics.errors5xx')}
              value={formatMetricValue(totals.http_errors)}
              hint={t('analytics.errorsHint', {
                value: formatPercent(totals.error_rate),
              })}
            />
            <KpiCard
              label={t('analytics.rating')}
              value={
                feedbackStats && feedbackStats.total > 0
                  ? formatPercent(feedbackStats.positive_ratio)
                  : '—'
              }
              hint={
                feedbackStats
                  ? t('analytics.ratingHint', {
                      total: formatMetricValue(feedbackStats.total),
                      positive: formatMetricValue(feedbackStats.positive),
                      negative: formatMetricValue(feedbackStats.negative),
                    })
                  : t('analytics.ratingsUnavailable')
              }
            />
          </div>

          <div className="mt-3 grid gap-2 lg:grid-cols-2">
            <div className="rounded-2xl border border-white/[0.07] bg-white/[0.02] px-4 py-3">
              <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-zinc-500">
                {t('analytics.requestsByTime')}
              </p>
              {requestsSeries.length > 0 ? (
                <Sparkline
                  values={requestsSeries}
                  label={t('analytics.requestsChartLabel')}
                />
              ) : (
                <p className="py-6 text-center text-[12px] text-zinc-600">
                  {t('analytics.historyUnavailable')}
                </p>
              )}
            </div>
            <div className="rounded-2xl border border-white/[0.07] bg-white/[0.02] px-4 py-3">
              <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-zinc-500">
                {t('analytics.tokensByTime')}
              </p>
              {tokensSeries.length > 0 ? (
                <Sparkline
                  values={tokensSeries}
                  label={t('analytics.tokensChartLabel')}
                />
              ) : (
                <p className="py-6 text-center text-[12px] text-zinc-600">
                  {t('analytics.historyUnavailable')}
                </p>
              )}
            </div>
          </div>

          <div className="mt-3 rounded-2xl border border-white/[0.07] bg-white/[0.02] px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-zinc-500">
                {t('analytics.activity')}
              </p>
              <div className="ml-auto flex rounded-lg border border-white/10 bg-white/[0.02] p-0.5">
                {ACTIVITY_WINDOWS.map((item) => (
                  <button
                    key={item.value}
                    type="button"
                    onClick={() => setActivityWindow(item.value)}
                    className={`rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${
                      activityWindow === item.value
                        ? 'bg-emerald-500 text-emerald-950'
                        : 'text-zinc-400 hover:bg-white/5 hover:text-zinc-200'
                    }`}
                  >
                    {t(item.labelKey)}
                  </button>
                ))}
              </div>
            </div>

            {activityError && (
              <div
                role="alert"
                className="mt-3 rounded-xl border border-rose-500/20 bg-rose-500/[0.07] px-3 py-2 text-[11.5px] text-rose-300"
              >
                {activityError}
              </div>
            )}

            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <KpiCard
                label={t('analytics.dau')}
                value={activityStats ? formatMetricValue(activityStats.dau) : '—'}
                hint={t('analytics.dauHint')}
              />
              <KpiCard
                label={t('analytics.wau')}
                value={activityStats ? formatMetricValue(activityStats.wau) : '—'}
                hint={t('analytics.wauHint')}
              />
            </div>

            {activityStats ? (
              <div className="mt-3">
                <div className="mb-1 flex flex-wrap items-baseline gap-2">
                  <p className="text-[11px] text-zinc-500">
                    {t('analytics.activeByDay')}
                  </p>
                  <span className="ml-auto text-[10.5px] text-zinc-600">
                    {t('analytics.requestsForPeriod', {
                      value: formatMetricValue(activityRequestsTotal),
                    })}
                  </span>
                </div>
                <Sparkline
                  values={activityStats.series.map(
                    (point) => point.active_users,
                  )}
                  label={t('analytics.activityChartLabel')}
                />
              </div>
            ) : activityLoading ? (
              <div className="mt-3 flex items-center justify-center gap-2 py-6 text-[12px] text-zinc-500">
                <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                {t('analytics.loadingActivity')}
              </div>
            ) : (
              <p className="mt-3 py-6 text-center text-[12px] text-zinc-600">
                {t('analytics.activityUnavailable')}
              </p>
            )}
          </div>

          <div className="mt-3 overflow-x-auto rounded-2xl border border-white/[0.07]">
            <table className="w-full min-w-[480px] border-collapse text-left">
              <thead>
                <tr className="border-b border-white/[0.07] bg-white/[0.02] text-[10.5px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
                  <th className="px-4 py-3">{t('analytics.user')}</th>
                  <th className="px-4 py-3 text-right">
                    {t('analytics.requestsColumn')}
                  </th>
                  <th className="px-4 py-3 text-right">
                    {t('analytics.tokensColumn')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {metrics.top_users.length === 0 ? (
                  <tr>
                    <td
                      colSpan={3}
                      className="px-4 py-6 text-center text-[12px] text-zinc-600"
                    >
                      {t('analytics.noUsers')}
                    </td>
                  </tr>
                ) : (
                  metrics.top_users.map((user) => (
                    <tr
                      key={user.user_id}
                      className="border-b border-white/[0.05] text-[12.5px] last:border-b-0"
                    >
                      <td className="px-4 py-3 text-zinc-200">{user.email}</td>
                      <td className="px-4 py-3 text-right text-zinc-300">
                        {formatMetricValue(user.requests)}
                      </td>
                      <td className="px-4 py-3 text-right text-zinc-300">
                        {formatMetricValue(user.tokens)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <div className="rounded-2xl border border-dashed border-white/10 py-16 text-center text-[13px] text-zinc-500">
          {t('analytics.noMetrics')}
        </div>
      )}
    </div>
  )
}

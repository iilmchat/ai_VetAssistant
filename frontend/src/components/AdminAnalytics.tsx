import { useCallback, useEffect, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  Database,
  RefreshCw,
  Server,
} from 'lucide-react'
import type { AdminMetrics, AdminMetricsWindow, FeedbackStats } from '../types'
import { fetchAdminMetrics, fetchFeedbackStats } from '../lib/api'
import { formatMetricValue, formatPercent, ragHitRate } from '../lib/metrics'
import { errorMessage } from '../lib/utils'
import { Sparkline } from './charts/Sparkline'

const WINDOWS: { value: AdminMetricsWindow; label: string }[] = [
  { value: '24h', label: '24 часа' },
  { value: '7d', label: '7 дней' },
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
  const [window, setWindow] = useState<AdminMetricsWindow>('24h')
  const [metrics, setMetrics] = useState<AdminMetrics | null>(null)
  const [feedbackStats, setFeedbackStats] = useState<FeedbackStats | null>(null)
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

  const totals = metrics?.totals
  const hitRate = totals ? ragHitRate(totals) : 0
  const requestsSeries = metrics?.series.map((point) => point.requests) ?? []
  const tokensSeries = metrics?.series.map((point) => point.tokens) ?? []

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
              {item.label}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="ml-auto flex items-center gap-2 rounded-lg border border-white/10 px-2.5 py-1.5 text-[11.5px] text-zinc-300 transition-colors hover:bg-white/5 disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          Обновить
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
              ? 'Prometheus'
              : 'с момента запуска API'}
          </span>
          {metrics.degraded && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/25 bg-amber-500/[0.08] px-2 py-0.5 text-amber-200">
              <AlertTriangle className="h-3 w-3" />
              Prometheus недоступен, показан локальный снимок
            </span>
          )}
          <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 px-2 py-0.5">
            <Activity className="h-3 w-3" />
            обновляется раз в минуту
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
          Загружаю метрики…
        </div>
      ) : totals ? (
        <>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            <KpiCard
              label="Запросы к модели"
              value={formatMetricValue(totals.requests)}
              hint={`ошибок: ${formatMetricValue(totals.generation_errors)}`}
            />
            <KpiCard
              label="Токены"
              value={formatMetricValue(totals.tokens)}
              hint={`prompt ${formatMetricValue(totals.prompt_tokens)} · completion ${formatMetricValue(totals.completion_tokens)}`}
            />
            <KpiCard
              label="RAG hit rate"
              value={formatPercent(hitRate)}
              hint={`поисков: ${formatMetricValue(totals.rag_hits + totals.rag_misses + totals.rag_errors)}`}
            />
            <KpiCard
              label="Ошибки 5xx"
              value={formatMetricValue(totals.http_errors)}
              hint={`доля ошибок модели: ${formatPercent(totals.error_rate)}`}
            />
            <KpiCard
              label="Рейтинг ответов"
              value={
                feedbackStats && feedbackStats.total > 0
                  ? formatPercent(feedbackStats.positive_ratio)
                  : '—'
              }
              hint={
                feedbackStats
                  ? `оценок: ${formatMetricValue(feedbackStats.total)} · 👍 ${formatMetricValue(feedbackStats.positive)} · 👎 ${formatMetricValue(feedbackStats.negative)}`
                  : 'оценки недоступны'
              }
            />
          </div>

          <div className="mt-3 grid gap-2 lg:grid-cols-2">
            <div className="rounded-2xl border border-white/[0.07] bg-white/[0.02] px-4 py-3">
              <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-zinc-500">
                Запросы по времени
              </p>
              {requestsSeries.length > 0 ? (
                <Sparkline values={requestsSeries} label="График запросов к модели" />
              ) : (
                <p className="py-6 text-center text-[12px] text-zinc-600">
                  История недоступна без Prometheus.
                </p>
              )}
            </div>
            <div className="rounded-2xl border border-white/[0.07] bg-white/[0.02] px-4 py-3">
              <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-zinc-500">
                Токены по времени
              </p>
              {tokensSeries.length > 0 ? (
                <Sparkline values={tokensSeries} label="График токенов модели" />
              ) : (
                <p className="py-6 text-center text-[12px] text-zinc-600">
                  История недоступна без Prometheus.
                </p>
              )}
            </div>
          </div>

          <div className="mt-3 overflow-x-auto rounded-2xl border border-white/[0.07]">
            <table className="w-full min-w-[480px] border-collapse text-left">
              <thead>
                <tr className="border-b border-white/[0.07] bg-white/[0.02] text-[10.5px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
                  <th className="px-4 py-3">Пользователь</th>
                  <th className="px-4 py-3 text-right">Запросы</th>
                  <th className="px-4 py-3 text-right">Токены</th>
                </tr>
              </thead>
              <tbody>
                {metrics.top_users.length === 0 ? (
                  <tr>
                    <td
                      colSpan={3}
                      className="px-4 py-6 text-center text-[12px] text-zinc-600"
                    >
                      Пока нет данных по пользователям.
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
          Метрик пока нет.
        </div>
      )}
    </div>
  )
}

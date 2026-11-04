import type { AdminMetricsTotals } from '../types'

/** Точка в координатах SVG-графика. */
export interface SparklinePoint {
  x: number
  y: number
}

/** Сгруппировать тысячи пробелами: 1500 -> «1 500». */
function groupThousands(value: number): string {
  return Math.round(value)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
}

/** Компактное число для KPI-карточек: 12 345 -> «12,3 тыс.». */
export function formatMetricValue(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return '0'
  }
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1).replace('.', ',')} млн`
  }
  if (value >= 10_000) {
    return `${(value / 1_000).toFixed(1).replace('.', ',')} тыс.`
  }
  if (value >= 1_000) {
    return groupThousands(value)
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(1).replace('.', ',')
}

/** Доля RAG-поисков, которые вернули чанки. */
export function ragHitRate(totals: AdminMetricsTotals): number {
  const total = totals.rag_hits + totals.rag_misses + totals.rag_errors
  return total > 0 ? totals.rag_hits / total : 0
}

/** Проценты с одним знаком: 0.1234 -> «12,3%». */
export function formatPercent(share: number): string {
  if (!Number.isFinite(share)) {
    return '—'
  }
  return `${(share * 100).toFixed(1).replace('.', ',')}%`
}

/**
 * Пересчитать значения в координаты полилинии.
 * Единичное значение ставится по центру, пустой ряд даёт пустой массив.
 */
export function sparklinePoints(
  values: number[],
  width: number,
  height: number,
  padding = 2,
): SparklinePoint[] {
  if (values.length === 0) {
    return []
  }

  const innerWidth = Math.max(width - padding * 2, 1)
  const innerHeight = Math.max(height - padding * 2, 1)
  const min = Math.min(...values, 0)
  const max = Math.max(...values, min)
  const span = max - min || 1
  const step = values.length > 1 ? innerWidth / (values.length - 1) : 0

  return values.map((value, index) => ({
    x:
      values.length === 1
        ? padding + innerWidth / 2
        : padding + step * index,
    y: padding + innerHeight - ((value - min) / span) * innerHeight,
  }))
}

/** SVG path для ряда значений; пустой ряд — пустая строка. */
export function sparklinePath(
  values: number[],
  width: number,
  height: number,
  padding = 2,
): string {
  const points = sparklinePoints(values, width, height, padding)
  return points
    .map((point, index) => {
      const command = index === 0 ? 'M' : 'L'
      return `${command}${point.x.toFixed(1)},${point.y.toFixed(1)}`
    })
    .join(' ')
}

import { describe, expect, it } from 'vitest'
import type { AdminMetricsTotals } from '../types'
import {
  formatMetricValue,
  formatPercent,
  ragHitRate,
  sparklinePath,
  sparklinePoints,
} from './metrics'

function totals(overrides: Partial<AdminMetricsTotals> = {}): AdminMetricsTotals {
  return {
    requests: 0,
    generation_errors: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    tokens: 0,
    rag_hits: 0,
    rag_misses: 0,
    rag_errors: 0,
    http_errors: 0,
    error_rate: 0,
    ...overrides,
  }
}

describe('formatMetricValue', () => {
  it('оставляет маленькие числа как есть', () => {
    expect(formatMetricValue(0)).toBe('0')
    expect(formatMetricValue(42)).toBe('42')
  })

  it('группирует тысячи пробелами', () => {
    expect(formatMetricValue(1500)).toBe('1 500')
    expect(formatMetricValue(9999)).toBe('9 999')
  })

  it('сокращает крупные значения', () => {
    expect(formatMetricValue(12_345)).toBe('12,3 тыс.')
    expect(formatMetricValue(1_500_000)).toBe('1,5 млн')
  })

  it('пишет дробные числа через запятую', () => {
    expect(formatMetricValue(3.5)).toBe('3,5')
  })

  it('не падает на некорректных значениях', () => {
    expect(formatMetricValue(Number.NaN)).toBe('0')
    expect(formatMetricValue(-5)).toBe('0')
  })
})

describe('formatPercent', () => {
  it('показывает долю с одним знаком', () => {
    expect(formatPercent(0.1234)).toBe('12,3%')
    expect(formatPercent(0)).toBe('0,0%')
    expect(formatPercent(1)).toBe('100,0%')
  })

  it('возвращает прочерк для NaN', () => {
    expect(formatPercent(Number.NaN)).toBe('—')
  })
})

describe('ragHitRate', () => {
  it('считает долю попаданий', () => {
    expect(ragHitRate(totals({ rag_hits: 5, rag_misses: 3, rag_errors: 2 }))).toBe(0.5)
  })

  it('возвращает 0 без поисков', () => {
    expect(ragHitRate(totals())).toBe(0)
  })
})

describe('sparklinePoints', () => {
  it('возвращает пустой массив без данных', () => {
    expect(sparklinePoints([], 100, 32)).toEqual([])
  })

  it('строит по точке на значение в пределах высоты', () => {
    const points = sparklinePoints([1, 5, 3], 100, 32, 2)

    expect(points).toHaveLength(3)
    for (const point of points) {
      expect(point.y).toBeGreaterThanOrEqual(2)
      expect(point.y).toBeLessThanOrEqual(30)
    }
  })

  it('ставит единственное значение по центру', () => {
    const [point] = sparklinePoints([7], 100, 32, 2)

    expect(point.x).toBeCloseTo(50)
  })

  it('не падает на плоском ряде', () => {
    const points = sparklinePoints([0, 0, 0], 100, 32)

    expect(points).toHaveLength(3)
    for (const point of points) {
      expect(Number.isFinite(point.x)).toBe(true)
      expect(Number.isFinite(point.y)).toBe(true)
    }
  })
})

describe('sparklinePath', () => {
  it('начинается с M и продолжается L', () => {
    const path = sparklinePath([1, 2], 100, 32)

    expect(path.startsWith('M')).toBe(true)
    expect(path).toContain('L')
  })

  it('возвращает пустую строку без данных', () => {
    expect(sparklinePath([], 100, 32)).toBe('')
  })
})

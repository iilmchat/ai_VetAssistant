import { sparklinePath } from '../../lib/metrics'

interface SparklineProps {
  values: number[]
  label: string
  className?: string
}

const WIDTH = 100
const HEIGHT = 32

/**
 * Минималистичный SVG-график без внешних зависимостей (T-135).
 * Высота фиксирована viewBox'ом: компонент растягивается по ширине контейнера.
 */
export function Sparkline({ values, label, className }: SparklineProps) {
  const path = sparklinePath(values, WIDTH, HEIGHT)

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
      className={`h-16 w-full ${className ?? ''}`}
    >
      <line
        x1="0"
        y1={HEIGHT - 1}
        x2={WIDTH}
        y2={HEIGHT - 1}
        strokeWidth="0.4"
        className="stroke-line"
      />
      {path && (
        <path
          d={path}
          fill="none"
          strokeWidth="1.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="stroke-accent-icon"
        />
      )}
    </svg>
  )
}

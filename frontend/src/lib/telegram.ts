/** Чистые хелперы блока «Telegram» в настройках (T-134.5). */

/** Срок жизни кода привязки на бэкенде: 10 минут. */
export const TELEGRAM_CODE_TTL_MS = 10 * 60 * 1000

/**
 * Сколько секунд осталось до истечения кода.
 *
 * Возвращает 0 для уже истёкшего или некорректного `expires_at`.
 */
export function codeSecondsLeft(
  expiresAt: string,
  now: number = Date.now(),
): number {
  const timestamp = Date.parse(expiresAt)
  if (Number.isNaN(timestamp)) {
    return 0
  }
  return Math.max(0, Math.ceil((timestamp - now) / 1000))
}

/** Форматировать секунды как `мм:сс` для обратного отсчёта. */
export function formatCountdown(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds))
  const minutes = Math.floor(safe / 60)
  const seconds = safe % 60
  return `${minutes}:${seconds.toString().padStart(2, '0')}`
}

/** Показать код двумя группами по 4 символа — так проще диктовать. */
export function formatTelegramCode(code: string): string {
  const normalized = code.trim()
  if (normalized.length <= 4) {
    return normalized
  }
  return `${normalized.slice(0, 4)} ${normalized.slice(4)}`
}

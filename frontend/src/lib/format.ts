import i18n from '../i18n'

/** BCP-47 локаль для Intl: `ru-RU`/`en-US`; можно переопределить явно. */
function resolveLocale(locale?: string): string {
  if (locale) {
    return locale
  }
  return currentLocale() === 'en' ? 'en-US' : 'ru-RU'
}

function currentLocale(): 'ru' | 'en' {
  return i18n.language?.startsWith('en') ? 'en' : 'ru'
}

interface DateParts {
  year: number
  month: number
  day: number
}

function parseIsoDate(value: string): DateParts | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim())
  if (!match) {
    return null
  }
  return {
    year: Number(match[1]),
    month: Number(match[2]),
    day: Number(match[3]),
  }
}

/** Короткая дата (`04.11` / `11/04`) без сдвига из-за часового пояса. */
export function formatDate(value: string, locale?: string): string {
  const parts = parseIsoDate(value)
  if (!parts) {
    return value
  }
  const date = new Date(
    Date.UTC(parts.year, parts.month - 1, parts.day),
  )
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat(resolveLocale(locale), {
    day: '2-digit',
    month: '2-digit',
    timeZone: 'UTC',
  }).format(date)
}

/** Полная дата и время по правилам текущего языка. */
export function formatDateTime(value: string, locale?: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat(resolveLocale(locale), {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

/** Дата и время приёма (`04.11 в 10:00` / `11/04 at 10:00 AM`). */
export function formatAppointmentMoment(
  date: string,
  time: string,
  locale?: string,
): string {
  const shortDate = formatDate(date, locale)
  if (shortDate && time) {
    return resolveLocale(locale).startsWith('en')
      ? `${shortDate} at ${time}`
      : `${shortDate} в ${time}`
  }
  return shortDate || time || '—'
}

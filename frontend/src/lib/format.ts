export function formatDate(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim())
  if (!match) {
    return value
  }
  return `${match[3]}.${match[2]}`
}

export function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatAppointmentMoment(date: string, time: string): string {
  const shortDate = formatDate(date)
  if (shortDate && time) {
    return `${shortDate} в ${time}`
  }
  return shortDate || time || '—'
}

/** Разбор глубоких ссылок приложения (T-184). */

export type AppRoute =
  | { type: 'patient'; patientId: number }
  | { type: 'chat' }

function parseId(value: string | null): number | null {
  if (!value) {
    return null
  }
  const id = Number(value)
  return Number.isInteger(id) && id > 0 ? id : null
}

/** Разобрать `vetassistant://patient/7`, `...://open?patient=7` или HTTPS-путь. */
export function parseAppRoute(input: string | null | undefined): AppRoute | null {
  if (!input) {
    return null
  }

  try {
    const url = new URL(input)

    if (url.protocol === 'vetassistant:') {
      const queryId = parseId(
        url.searchParams.get('patient') ?? url.searchParams.get('patient_id'),
      )
      if (queryId !== null) {
        return { type: 'patient', patientId: queryId }
      }

      const parts = [url.hostname, ...url.pathname.split('/').filter(Boolean)]
        .filter(Boolean)
        .map((part) => part.toLowerCase())
      if (parts[0] === 'patient') {
        const id = parseId(parts[1] ?? null)
        if (id !== null) {
          return { type: 'patient', patientId: id }
        }
      }
      return { type: 'chat' }
    }

    if (
      (url.protocol === 'https:' || url.protocol === 'http:') &&
      (url.hostname === 'app.ai-pets.ru' ||
        url.hostname === 'ai-pets.ru' ||
        url.hostname === 'localhost' ||
        url.hostname === '127.0.0.1')
    ) {
      const match = url.pathname.match(/^\/patient\/(\d+)\/?$/)
      if (match) {
        const id = parseId(match[1])
        if (id !== null) {
          return { type: 'patient', patientId: id }
        }
      }
      if (url.pathname === '/' || url.pathname === '/chat') {
        return { type: 'chat' }
      }
    }
  } catch {
    return null
  }

  return null
}

/** Ссылка для открытия карточки питомца из уведомления. */
export function buildPatientDeepLink(patientId: number): string {
  return `vetassistant://patient/${patientId}`
}

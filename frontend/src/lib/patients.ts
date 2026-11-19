import type { Patient } from '../types'

const ACTIVE_PATIENT_PREFIX = 'vetassistant.activePatient'
const PATIENT_CACHE_PREFIX = 'vetassistant.patientsCache'

/** Ключ кэша списка питомцев конкретного пользователя. */
export function patientsCacheKey(userId: number): string {
  return `${PATIENT_CACHE_PREFIX}.${userId}`
}

/** Прочитать последний успешно загруженный список питомцев. */
export function readCachedPatients(userId: number): Patient[] | null {
  if (typeof window === 'undefined') {
    return null
  }
  try {
    const raw = window.localStorage.getItem(patientsCacheKey(userId))
    if (!raw) {
      return null
    }
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) {
      return null
    }
    return parsed.filter(
      (item): item is Patient =>
        typeof item === 'object' &&
        item !== null &&
        typeof (item as Patient).id === 'number' &&
        typeof (item as Patient).name === 'string',
    )
  } catch {
    return null
  }
}

/** Обновить кэш списка питомцев. */
export function writeCachedPatients(userId: number, patients: Patient[]): void {
  if (typeof window === 'undefined') {
    return
  }
  try {
    window.localStorage.setItem(
      patientsCacheKey(userId),
      JSON.stringify(patients),
    )
  } catch {
    // Приватный режим — кэш не нужен, данные останутся на сервере.
  }
}

/** Ключ localStorage для активного питомца конкретного пользователя. */
export function activePatientStorageKey(userId: number): string {
  return `${ACTIVE_PATIENT_PREFIX}.${userId}`
}

/** Прочитать сохранённый id активного питомца. */
export function readActivePatientId(userId: number): number | null {
  if (typeof window === 'undefined') {
    return null
  }
  try {
    const raw = window.localStorage.getItem(activePatientStorageKey(userId))
    if (!raw) {
      return null
    }
    const parsed = Number(raw)
    return Number.isInteger(parsed) && parsed > 0 ? parsed : null
  } catch {
    return null
  }
}

/** Сохранить активного питомца; `null` очищает выбор. */
export function saveActivePatientId(
  userId: number,
  patientId: number | null,
): void {
  if (typeof window === 'undefined') {
    return
  }
  try {
    const key = activePatientStorageKey(userId)
    if (patientId === null) {
      window.localStorage.removeItem(key)
    } else {
      window.localStorage.setItem(key, String(patientId))
    }
  } catch {
    // Приватный режим — выбор просто не переживёт перезагрузку.
  }
}

/** Оставить сохранённый id только если он есть в списке пациентов. */
export function resolveActivePatientId(
  stored: number | null,
  patients: Patient[],
): number | null {
  if (stored === null) {
    return null
  }
  return patients.some((patient) => patient.id === stored) ? stored : null
}

/** Найти питомца по кличке (без учёта регистра) после agentic-создания. */
export function findPatientByName(
  patients: Patient[],
  name: string,
): Patient | null {
  const needle = name.trim().toLocaleLowerCase()
  if (!needle) {
    return null
  }
  return (
    patients.find(
      (patient) => patient.name.trim().toLocaleLowerCase() === needle,
    ) ?? null
  )
}

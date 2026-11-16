import type { Patient } from '../types'

const ACTIVE_PATIENT_PREFIX = 'vetassistant.activePatient'

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

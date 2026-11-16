import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Patient } from '../types'
import {
  activePatientStorageKey,
  findPatientByName,
  readActivePatientId,
  resolveActivePatientId,
  saveActivePatientId,
} from './patients'

function createStorage() {
  const values = new Map<string, string>()
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value)
    },
    removeItem: (key: string) => {
      values.delete(key)
    },
  }
}

function patient(id: number, name: string): Patient {
  return {
    id,
    name,
    species: 'dog',
    breed: null,
    birth_date: null,
    weight: null,
    known_allergies: null,
    chronic_conditions: null,
    age_years: null,
    created_at: '2026-11-16T10:00:00Z',
    updated_at: '2026-11-16T10:00:00Z',
  }
}

let storage: ReturnType<typeof createStorage>

beforeEach(() => {
  storage = createStorage()
  vi.stubGlobal('window', { localStorage: storage })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('patients storage', () => {
  it('хранит активного питомца отдельно для каждого пользователя', () => {
    saveActivePatientId(1, 10)
    saveActivePatientId(2, 20)

    expect(activePatientStorageKey(1)).toBe('vetassistant.activePatient.1')
    expect(readActivePatientId(1)).toBe(10)
    expect(readActivePatientId(2)).toBe(20)
  })

  it('очищает выбор при null', () => {
    saveActivePatientId(1, 10)
    saveActivePatientId(1, null)

    expect(readActivePatientId(1)).toBeNull()
  })

  it('игнорирует битое значение в localStorage', () => {
    storage.setItem(activePatientStorageKey(1), 'not-a-number')

    expect(readActivePatientId(1)).toBeNull()
  })
})

describe('resolveActivePatientId', () => {
  it('оставляет id, если питомец есть в списке', () => {
    const patients = [patient(1, 'Бобик'), patient(2, 'Мурка')]

    expect(resolveActivePatientId(2, patients)).toBe(2)
  })

  it('сбрасывает id, если питомца удалили', () => {
    expect(resolveActivePatientId(3, [patient(1, 'Бобик')])).toBeNull()
  })

  it('возвращает null без сохранённого выбора', () => {
    expect(resolveActivePatientId(null, [patient(1, 'Бобик')])).toBeNull()
  })
})

describe('findPatientByName', () => {
  it('находит питомца без учёта регистра', () => {
    const patients = [patient(1, 'Бобик'), patient(2, 'Мурка')]

    expect(findPatientByName(patients, '  бобик ')?.id).toBe(1)
  })

  it('возвращает null для пустого имени или промаха', () => {
    const patients = [patient(1, 'Бобик')]

    expect(findPatientByName(patients, '   ')).toBeNull()
    expect(findPatientByName(patients, 'Рекс')).toBeNull()
  })
})

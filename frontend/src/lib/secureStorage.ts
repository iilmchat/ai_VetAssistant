/** Безопасное хранилище сессии: Preferences на Android, localStorage в вебе (T-181). */

import { Capacitor } from '@capacitor/core'

export const AUTH_STORAGE_KEY = 'vetassistant.auth.v1'

function webStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    return null
  }
}

/** Прочитать сохранённую сессию (для асинхронного старта приложения). */
export async function readSecureValue(): Promise<string | null> {
  if (Capacitor.isNativePlatform()) {
    try {
      const { Preferences } = await import('@capacitor/preferences')
      const result = await Preferences.get({ key: AUTH_STORAGE_KEY })
      return result.value ?? null
    } catch {
      return null
    }
  }
  return webStorage()?.getItem(AUTH_STORAGE_KEY) ?? null
}

/** Сохранить или удалить сессию. `null` означает выход из аккаунта. */
export async function writeSecureValue(value: string | null): Promise<void> {
  if (Capacitor.isNativePlatform()) {
    try {
      const { Preferences } = await import('@capacitor/preferences')
      if (value === null) {
        await Preferences.remove({ key: AUTH_STORAGE_KEY })
      } else {
        await Preferences.set({ key: AUTH_STORAGE_KEY, value })
      }
    } catch {
      // Нет доступного хранилища — сессия останется только в памяти.
    }
    return
  }

  const storage = webStorage()
  try {
    if (value === null) {
      storage?.removeItem(AUTH_STORAGE_KEY)
    } else if (storage) {
      storage.setItem(AUTH_STORAGE_KEY, value)
    }
  } catch {
    // Приватный режим или переполненное хранилище.
  }
}

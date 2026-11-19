/** PWA-утилиты: регистрация Service Worker и режим «установлено» (T-176). */

/** Зарегистрировать Service Worker только в production-сборке. */
export function registerServiceWorker(enabled: boolean = import.meta.env.PROD): void {
  if (typeof window === 'undefined' || !enabled) {
    return
  }
  if (!('serviceWorker' in navigator)) {
    return
  }

  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/sw.js').catch(() => {
      // PWA — дополнение: сбой регистрации не должен ломать чат.
    })
  })
}

/** Приложение запущено как standalone/установленное PWA. */
export function isStandalone(): boolean {
  if (typeof window === 'undefined') {
    return false
  }
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    (window.navigator as Navigator & { standalone?: boolean }).standalone === true
  )
}

/** Событие браузера о возможности установить PWA. */
export interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

/** Проверить, что событие установки имеет нужный интерфейс. */
export function isBeforeInstallPromptEvent(value: Event): value is BeforeInstallPromptEvent {
  return (
    typeof (value as BeforeInstallPromptEvent).prompt === 'function' &&
    'userChoice' in value
  )
}

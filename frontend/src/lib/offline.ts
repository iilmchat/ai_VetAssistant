/** Состояние сети и локальная очередь оценок (T-185). */

import { useEffect, useState } from 'react'

export function isBrowserOnline(): boolean {
  if (typeof navigator === 'undefined') {
    return true
  }
  return navigator.onLine !== false
}

/** Реактивное состояние `navigator.onLine`. */
export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState(isBrowserOnline)

  useEffect(() => {
    const handleOnline = () => setOnline(true)
    const handleOffline = () => setOnline(false)
    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)
    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  return online
}

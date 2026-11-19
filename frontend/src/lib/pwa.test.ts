import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  isBeforeInstallPromptEvent,
  isStandalone,
  registerServiceWorker,
} from './pwa'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('registerServiceWorker', () => {
  it('не регистрирует SW в dev-режиме', () => {
    const addEventListener = vi.fn()
    const register = vi.fn()
    vi.stubGlobal('window', { addEventListener })
    vi.stubGlobal('navigator', { serviceWorker: { register } })

    registerServiceWorker(false)

    expect(addEventListener).not.toHaveBeenCalled()
    expect(register).not.toHaveBeenCalled()
  })

  it('регистрирует /sw.js после load в prod', () => {
    const listeners: Record<string, () => void> = {}
    const register = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('window', {
      addEventListener: (name: string, handler: () => void) => {
        listeners[name] = handler
      },
    })
    vi.stubGlobal('navigator', { serviceWorker: { register } })

    registerServiceWorker(true)
    listeners.load?.()

    expect(register).toHaveBeenCalledWith('/sw.js')
  })

  it('не падает без поддержки Service Worker', () => {
    const addEventListener = vi.fn()
    vi.stubGlobal('window', { addEventListener })
    vi.stubGlobal('navigator', {})

    expect(() => registerServiceWorker(true)).not.toThrow()
    expect(addEventListener).not.toHaveBeenCalled()
  })
})

describe('isStandalone', () => {
  it('возвращает true в display-mode: standalone', () => {
    vi.stubGlobal('window', {
      matchMedia: () => ({ matches: true }),
      navigator: {},
    })

    expect(isStandalone()).toBe(true)
  })

  it('возвращает false в обычном браузере', () => {
    vi.stubGlobal('window', {
      matchMedia: () => ({ matches: false }),
      navigator: {},
    })

    expect(isStandalone()).toBe(false)
  })
})

describe('isBeforeInstallPromptEvent', () => {
  it('распознаёт событие установки PWA', () => {
    const event = {
      prompt: () => Promise.resolve(),
      userChoice: Promise.resolve({ outcome: 'accepted' }),
    } as unknown as Event

    expect(isBeforeInstallPromptEvent(event)).toBe(true)
  })

  it('отвергает обычное событие', () => {
    expect(isBeforeInstallPromptEvent(new Event('click'))).toBe(false)
  })
})

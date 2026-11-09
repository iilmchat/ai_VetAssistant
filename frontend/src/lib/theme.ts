/** Ключ localStorage, в котором хранится выбранная тема. */
export const THEME_STORAGE_KEY = 'vetassistant.theme'

export const THEME_MODES = ['light', 'dark', 'system'] as const
export type ThemeMode = (typeof THEME_MODES)[number]
export type ResolvedTheme = 'light' | 'dark'

/**
 * По умолчанию — тёмная тема: сохраняем вид интерфейса до v1.12.0.
 * «Системная» доступна в переключателе, но не навязывается существующим
 * пользователям после обновления.
 */
export const DEFAULT_THEME: ThemeMode = 'dark'

export function isThemeMode(value: unknown): value is ThemeMode {
  return value === 'light' || value === 'dark' || value === 'system'
}

/** Разобрать значение из localStorage с безопасным fallback. */
export function parseTheme(value: string | null | undefined): ThemeMode {
  return isThemeMode(value) ? value : DEFAULT_THEME
}

export function readStoredTheme(): ThemeMode {
  if (typeof window === 'undefined') {
    return DEFAULT_THEME
  }
  try {
    return parseTheme(window.localStorage.getItem(THEME_STORAGE_KEY))
  } catch {
    // Приватный режим или недоступное хранилище — тема по умолчанию.
    return DEFAULT_THEME
  }
}

/** Привести режим к конкретной теме с учётом системной настройки. */
export function resolveTheme(
  mode: ThemeMode,
  prefersDark: boolean,
): ResolvedTheme {
  if (mode === 'system') {
    return prefersDark ? 'dark' : 'light'
  }
  return mode
}

function systemPrefersDark(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return true
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

/**
 * Применить тему к документу: `data-theme` на `<html>` переключает
 * CSS-переменные из `index.css`, `color-scheme` — нативные контролы.
 */
export function applyTheme(mode: ThemeMode): ResolvedTheme {
  const resolved = resolveTheme(mode, systemPrefersDark())
  if (typeof document !== 'undefined') {
    const root = document.documentElement
    root.dataset.theme = resolved
    root.style.colorScheme = resolved
    const meta = document.querySelector('meta[name="theme-color"]')
    meta?.setAttribute('content', resolved === 'dark' ? '#171717' : '#f6f6f3')
  }
  return resolved
}

/** Выбрать тему, сохранить её и сразу применить. */
export function setTheme(mode: ThemeMode): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, mode)
  } catch {
    // Хранилище недоступно — тема всё равно применится до перезагрузки.
  }
  applyTheme(mode)
}

/**
 * Следить за системной темой (когда выбран «System») и за изменениями
 * localStorage в других вкладках. Возвращает функцию отписки.
 */
export function watchTheme(): () => void {
  if (typeof window === 'undefined') {
    return () => {}
  }

  const media =
    typeof window.matchMedia === 'function'
      ? window.matchMedia('(prefers-color-scheme: dark)')
      : null

  const handleMedia = () => {
    if (readStoredTheme() === 'system') {
      applyTheme('system')
    }
  }
  const handleStorage = (event: StorageEvent) => {
    if (event.key === THEME_STORAGE_KEY) {
      applyTheme(parseTheme(event.newValue))
    }
  }

  media?.addEventListener('change', handleMedia)
  window.addEventListener('storage', handleStorage)

  return () => {
    media?.removeEventListener('change', handleMedia)
    window.removeEventListener('storage', handleStorage)
  }
}

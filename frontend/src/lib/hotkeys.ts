/** Минимальное описание клавиатурного события для чистых проверок. */
export interface HotkeyEvent {
  key: string
  ctrlKey: boolean
  metaKey: boolean
  altKey: boolean
  shiftKey: boolean
  isComposing?: boolean
}

/** Ctrl+K (Windows/Linux) или Cmd+K (macOS) — фокус на поле ввода чата. */
export function isFocusComposerHotkey(event: HotkeyEvent): boolean {
  return (
    (event.ctrlKey || event.metaKey) &&
    !event.altKey &&
    !event.shiftKey &&
    event.key.toLowerCase() === 'k'
  )
}

/**
 * Enter или Ctrl/Cmd+Enter — отправить сообщение.
 * Shift+Enter и Alt+Enter оставляем для переноса строки, а ввод в режиме
 * IME (китайский/японский) не перехватываем.
 */
export function isSendHotkey(event: HotkeyEvent): boolean {
  if (event.key !== 'Enter' || event.isComposing) {
    return false
  }
  return !event.shiftKey && !event.altKey
}

import { describe, expect, it } from 'vitest'
import { isFocusComposerHotkey, isSendHotkey } from './hotkeys'
import type { HotkeyEvent } from './hotkeys'

function event(patch: Partial<HotkeyEvent>): HotkeyEvent {
  return {
    key: '',
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    shiftKey: false,
    ...patch,
  }
}

describe('горячие клавиши', () => {
  it('Ctrl+K и Cmd+K фокусируют поле ввода', () => {
    expect(isFocusComposerHotkey(event({ key: 'k', ctrlKey: true }))).toBe(true)
    expect(isFocusComposerHotkey(event({ key: 'K', metaKey: true }))).toBe(true)
  })

  it('не перехватывают K без модификатора или с Shift/Alt', () => {
    expect(isFocusComposerHotkey(event({ key: 'k' }))).toBe(false)
    expect(
      isFocusComposerHotkey(event({ key: 'k', ctrlKey: true, shiftKey: true })),
    ).toBe(false)
    expect(
      isFocusComposerHotkey(event({ key: 'k', ctrlKey: true, altKey: true })),
    ).toBe(false)
  })

  it('Enter и Ctrl/Cmd+Enter отправляют сообщение', () => {
    expect(isSendHotkey(event({ key: 'Enter' }))).toBe(true)
    expect(isSendHotkey(event({ key: 'Enter', ctrlKey: true }))).toBe(true)
    expect(isSendHotkey(event({ key: 'Enter', metaKey: true }))).toBe(true)
  })

  it('Shift+Enter, Alt+Enter и IME не отправляют', () => {
    expect(isSendHotkey(event({ key: 'Enter', shiftKey: true }))).toBe(false)
    expect(isSendHotkey(event({ key: 'Enter', altKey: true }))).toBe(false)
    expect(isSendHotkey(event({ key: 'Enter', isComposing: true }))).toBe(false)
    expect(isSendHotkey(event({ key: 'a' }))).toBe(false)
  })
})

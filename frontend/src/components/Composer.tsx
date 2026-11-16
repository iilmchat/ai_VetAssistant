import { useEffect, useRef } from 'react'
import type { KeyboardEvent, RefObject } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowUp, Loader2, Square } from 'lucide-react'
import { isSendHotkey } from '../lib/hotkeys'

interface ComposerProps {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  onStop: () => void
  isStreaming: boolean
  /** Внешний ref нужен для Ctrl/Cmd+K из App (T-154.2). */
  inputRef?: RefObject<HTMLTextAreaElement | null>
}

export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  isStreaming,
  inputRef,
}: ComposerProps) {
  const { t } = useTranslation()
  const innerRef = useRef<HTMLTextAreaElement>(null)
  const textareaRef = inputRef ?? innerRef

  useEffect(() => {
    const element = textareaRef.current
    if (!element) {
      return
    }
    element.style.height = '0px'
    element.style.height = `${Math.min(element.scrollHeight, 200)}px`
  }, [textareaRef, value])

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    const wantsSend = isSendHotkey({
      key: event.key,
      ctrlKey: event.ctrlKey,
      metaKey: event.metaKey,
      altKey: event.altKey,
      shiftKey: event.shiftKey,
      isComposing: event.nativeEvent.isComposing,
    })
    if (!wantsSend) {
      return
    }
    event.preventDefault()
    if (value.trim() && !isStreaming) {
      onSend()
    }
  }

  return (
    <div className="bg-gradient-to-t from-app via-app to-transparent px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2 sm:px-4 sm:pb-4 lg:px-6">
      <div className="mx-auto w-full max-w-3xl">
        <form
          noValidate
          onSubmit={(event) => {
            event.preventDefault()
            if (value.trim() && !isStreaming) {
              onSend()
            }
          }}
        >
          <div className="flex items-end gap-2 rounded-3xl border border-line bg-composer p-2 pl-4 shadow-[0_10px_40px_rgba(0,0,0,0.25)] transition-colors focus-within:border-emerald-500/60 focus-within:ring-2 focus-within:ring-emerald-500/25">
            <textarea
              ref={textareaRef}
              value={value}
              onChange={(event) => onChange(event.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              autoFocus
              placeholder={t('composer.placeholder')}
              aria-label={t('composer.messageAria')}
              className="composer-input max-h-48 min-h-11 flex-1 resize-none border-0 bg-transparent py-2.5 pr-2 text-[15px] leading-6 text-ink caret-emerald-400 shadow-none outline-none placeholder:text-ink-muted focus:outline-none focus:ring-0 focus-visible:outline-none invalid:border-0 invalid:shadow-none"
            />
            {isStreaming ? (
              <>
                <span
                  role="status"
                  className="flex h-10 w-10 shrink-0 items-center justify-center sm:h-9 sm:w-9"
                >
                  <Loader2
                    className="h-4 w-4 animate-spin text-accent-icon"
                    aria-hidden="true"
                  />
                  <span className="sr-only">{t('composer.generating')}</span>
                </span>
                <button
                  type="button"
                  onClick={onStop}
                  aria-label={t('composer.stop')}
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-ink-strong text-app transition-transform hover:scale-105 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 sm:h-9 sm:w-9"
                >
                  <Square className="h-3.5 w-3.5 fill-current" />
                </button>
              </>
            ) : (
              <button
                type="submit"
                disabled={!value.trim()}
                aria-label={t('composer.send')}
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-ink-strong text-app transition-all hover:scale-105 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 disabled:cursor-not-allowed disabled:bg-tint-3 disabled:text-ink-muted disabled:hover:scale-100 sm:h-9 sm:w-9"
              >
                <ArrowUp className="h-4 w-4" strokeWidth={2.5} />
              </button>
            )}
          </div>
        </form>
        <p className="mt-2 text-center text-[10.5px] leading-4 text-ink-faint">
          {t('composer.disclaimer')}
          <span className="hidden sm:inline"> {t('composer.hint')}</span>
        </p>
      </div>
    </div>
  )
}

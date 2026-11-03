import { useEffect, useRef } from 'react'
import type { KeyboardEvent } from 'react'
import { ArrowUp, Square } from 'lucide-react'

interface ComposerProps {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  onStop: () => void
  isStreaming: boolean
}

export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  isStreaming,
}: ComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const element = textareaRef.current
    if (!element) {
      return
    }
    element.style.height = '0px'
    element.style.height = `${Math.min(element.scrollHeight, 200)}px`
  }, [value])

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === 'Enter' &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault()
      if (value.trim() && !isStreaming) {
        onSend()
      }
    }
  }

  return (
    <div className="bg-gradient-to-t from-[#212121] via-[#212121] to-transparent px-3 pb-3 pt-2 sm:px-4 sm:pb-4 lg:px-6">
      <div className="mx-auto w-full max-w-3xl">
        <form
          onSubmit={(event) => {
            event.preventDefault()
            if (value.trim() && !isStreaming) {
              onSend()
            }
          }}
        >
          <div className="flex items-end gap-2 rounded-3xl border border-white/10 bg-[#2f2f2f] p-2 pl-4 shadow-[0_10px_40px_rgba(0,0,0,0.25)] transition-colors focus-within:border-emerald-500/40 focus-within:ring-1 focus-within:ring-emerald-500/20">
            <textarea
              ref={textareaRef}
              value={value}
              onChange={(event) => onChange(event.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              autoFocus
              placeholder="Опишите, что беспокоит питомца…"
              aria-label="Сообщение"
              className="max-h-48 min-h-11 flex-1 resize-none bg-transparent py-2.5 pr-2 text-[15px] leading-6 text-zinc-100 outline-none placeholder:text-zinc-500"
            />
            {isStreaming ? (
              <button
                type="button"
                onClick={onStop}
                aria-label="Остановить генерацию"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-zinc-950 transition-transform hover:scale-105 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
              >
                <Square className="h-3.5 w-3.5 fill-current" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!value.trim()}
                aria-label="Отправить сообщение"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white text-zinc-950 transition-all hover:scale-105 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-zinc-500 disabled:hover:scale-100"
              >
                <ArrowUp className="h-4 w-4" strokeWidth={2.5} />
              </button>
            )}
          </div>
        </form>
        <p className="mt-2 text-center text-[10.5px] leading-4 text-zinc-600">
          VetAssistant — ИИ, а не живой ветеринарный врач. При экстренных
          симптомах сразу обратитесь в клинику.
          <span className="hidden sm:inline">
            {' '}
            Enter — отправить, Shift+Enter — новая строка.
          </span>
        </p>
      </div>
    </div>
  )
}

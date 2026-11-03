import { AlertTriangle, PawPrint, UserRound } from 'lucide-react'
import type { UiMessage } from '../types'
import { Markdown } from './Markdown'
import { ToolCallBadge } from './ToolCallBadge'

function TypingIndicator() {
  return (
    <div
      className="flex items-center gap-1.5 py-2"
      aria-label="Ассистент печатает"
    >
      <span className="typing-dot" />
      <span className="typing-dot" />
      <span className="typing-dot" />
    </div>
  )
}

export function MessageBubble({ message }: { message: UiMessage }) {
  const isUser = message.role === 'user'

  return (
    <div
      className={`message-enter flex w-full gap-3 ${
        isUser ? 'justify-end' : 'justify-start'
      }`}
    >
      {!isUser && (
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-emerald-400 to-teal-600 text-zinc-950 shadow-[0_4px_14px_rgba(16,185,129,0.2)]">
          <PawPrint className="h-4 w-4" strokeWidth={2.4} />
        </div>
      )}

      <div
        className={`min-w-0 ${
          isUser ? 'max-w-[88%] sm:max-w-[75%]' : 'flex-1 pt-0.5'
        }`}
      >
        {!isUser && (
          <div className="mb-1.5 flex items-center gap-2">
            <span className="text-[13px] font-semibold text-zinc-100">
              VetAssistant
            </span>
            <span className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-emerald-300">
              AI
            </span>
          </div>
        )}

        {message.toolCalls.length > 0 && (
          <div className="mb-2.5 space-y-2">
            {message.toolCalls.map((call) => (
              <ToolCallBadge key={call.id || call.function.name} call={call} />
            ))}
          </div>
        )}

        {isUser ? (
          <div className="whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-emerald-600 px-4 py-2.5 text-[15px] leading-7 text-white shadow-[0_4px_16px_rgba(5,150,105,0.18)]">
            {message.content}
          </div>
        ) : (
          <div className="min-w-0">
            {message.content ? (
              <div>
                <Markdown content={message.content} />
                {message.status === 'streaming' && (
                  <span className="stream-cursor" aria-hidden="true" />
                )}
              </div>
            ) : message.status === 'streaming' ? (
              <TypingIndicator />
            ) : null}

            {message.status === 'stopped' && (
              <p className="mt-2 text-[11px] text-zinc-500">
                Генерация остановлена.
              </p>
            )}

            {message.error && (
              <div className="mt-3 flex items-start gap-2.5 rounded-xl border border-rose-500/20 bg-rose-500/[0.06] px-3.5 py-3 text-[12px] leading-5 text-rose-300">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{message.error}</span>
              </div>
            )}
          </div>
        )}
      </div>

      {isUser && (
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-white/10 bg-[#2f2f2f] text-zinc-300">
          <UserRound className="h-4 w-4" />
        </div>
      )}
    </div>
  )
}

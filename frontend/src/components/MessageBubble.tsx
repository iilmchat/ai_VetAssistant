import { useTranslation } from 'react-i18next'
import {
  AlertTriangle,
  PawPrint,
  ThumbsDown,
  ThumbsUp,
  UserRound,
} from 'lucide-react'
import type { FeedbackRating, UiMessage } from '../types'
import { Markdown } from './Markdown'
import { ToolCallBadge } from './ToolCallBadge'

interface MessageBubbleProps {
  message: UiMessage
  rating?: FeedbackRating | null
  feedbackPending?: boolean
  onFeedback?: (rating: FeedbackRating) => void
}

function TypingIndicator() {
  const { t } = useTranslation()
  return (
    <div
      className="flex items-center gap-1.5 py-2"
      aria-label={t('message.typing')}
    >
      <span className="typing-dot" />
      <span className="typing-dot" />
      <span className="typing-dot" />
    </div>
  )
}

export function MessageBubble({
  message,
  rating = null,
  feedbackPending = false,
  onFeedback,
}: MessageBubbleProps) {
  const { t } = useTranslation()
  const isUser = message.role === 'user'
  const canRate =
    !isUser &&
    message.status === 'done' &&
    message.content.trim().length > 0 &&
    !message.error &&
    typeof onFeedback === 'function'

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
            <span className="text-[13px] font-semibold text-ink">
              VetAssistant
            </span>
            <span className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-accent">
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
              <p className="mt-2 text-[11px] text-ink-muted">
                {t('message.stopped')}
              </p>
            )}

            {message.error && (
              <div className="mt-3 flex items-start gap-2.5 rounded-xl border border-rose-500/20 bg-rose-500/[0.06] px-3.5 py-3 text-[12px] leading-5 text-danger">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{message.error}</span>
              </div>
            )}

            {canRate && (
              <div
                role="group"
                aria-label={t('message.feedbackGroup')}
                className="mt-2.5 flex items-center gap-1.5"
              >
                <button
                  type="button"
                  onClick={() => onFeedback?.(1)}
                  disabled={feedbackPending}
                  aria-pressed={rating === 1}
                  aria-label={t('message.helpful')}
                  title={t('message.helpful')}
                  className={`inline-flex h-10 w-10 items-center justify-center rounded-lg border transition-colors disabled:cursor-wait disabled:opacity-60 sm:h-8 sm:w-8 ${
                    rating === 1
                      ? 'border-emerald-400 bg-emerald-500 text-emerald-950 hover:bg-emerald-400'
                      : 'border-line bg-tint text-ink-muted hover:border-emerald-500/40 hover:bg-emerald-500/10 hover:text-accent'
                  }`}
                >
                  <ThumbsUp className="h-4 w-4" strokeWidth={2.2} />
                </button>
                <button
                  type="button"
                  onClick={() => onFeedback?.(-1)}
                  disabled={feedbackPending}
                  aria-pressed={rating === -1}
                  aria-label={t('message.notHelpful')}
                  title={t('message.notHelpful')}
                  className={`inline-flex h-10 w-10 items-center justify-center rounded-lg border transition-colors disabled:cursor-wait disabled:opacity-60 sm:h-8 sm:w-8 ${
                    rating === -1
                      ? 'border-rose-400 bg-rose-500 text-rose-950 hover:bg-rose-400'
                      : 'border-line bg-tint text-ink-muted hover:border-rose-500/40 hover:bg-rose-500/10 hover:text-danger'
                  }`}
                >
                  <ThumbsDown className="h-4 w-4" strokeWidth={2.2} />
                </button>
                {feedbackPending && (
                  <span className="ml-0.5 text-[10.5px] text-ink-muted">
                    {t('message.savingRating')}
                  </span>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {isUser && (
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-line bg-composer text-ink-soft">
          <UserRound className="h-4 w-4" />
        </div>
      )}
    </div>
  )
}

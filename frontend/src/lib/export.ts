import i18n from '../i18n'
import type { UiMessage } from '../types'

export interface ChatExportOptions {
  email?: string
  exportedAt?: Date
  /** BCP-47 локаль; по умолчанию — язык интерфейса. */
  locale?: string
}

function resolveLocale(locale?: string): string {
  if (locale) {
    return locale
  }
  return i18n.language?.startsWith('en') ? 'en-US' : 'ru-RU'
}

function translate(key: string, options?: Record<string, unknown>): string {
  return (options ? i18n.t(key, options) : i18n.t(key)) as string
}

function formatDate(
  value: string | undefined,
  fallback: Date,
  locale?: string,
): string {
  const date = value ? new Date(value) : fallback
  if (Number.isNaN(date.getTime())) {
    return translate('export.unknownDate')
  }
  return new Intl.DateTimeFormat(resolveLocale(locale), {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function messageHeading(
  message: UiMessage,
  exportedAt: Date,
  locale?: string,
): string {
  const role =
    message.role === 'user'
      ? translate('export.roleUser')
      : translate('export.roleAssistant')
  return `### ${role} — ${formatDate(message.createdAt, exportedAt, locale)}`
}

/** Собрать Markdown-экспорт истории диалога. */
export function buildChatMarkdown(
  messages: UiMessage[],
  options: ChatExportOptions = {},
): string {
  const exportedAt = options.exportedAt ?? new Date()
  const locale = options.locale
  const lines = [`# ${translate('export.title')}`, '']

  if (options.email) {
    lines.push(`- ${translate('export.user')}: ${options.email}`)
  }
  lines.push(
    `- ${translate('export.exported')}: ${formatDate(exportedAt.toISOString(), exportedAt, locale)}`,
  )
  lines.push('', '---', '')

  if (messages.length === 0) {
    lines.push(`_${translate('export.emptyHistory')}_`, '')
    return lines.join('\n')
  }

  for (const message of messages) {
    lines.push(
      messageHeading(message, exportedAt, locale),
      '',
      message.content.trim() || `_${translate('export.emptyMessage')}_`,
      '',
    )
    if (message.toolCalls.length > 0) {
      lines.push(`**${translate('export.toolCalls')}**`, '')
      for (const call of message.toolCalls) {
        lines.push(`- \`${call.function.name}\` (${call.function.arguments})`)
      }
      lines.push('')
    }
  }

  return lines.join('\n').trimEnd() + '\n'
}

/** Собрать JSON-экспорт истории диалога. */
export function buildChatJson(
  messages: UiMessage[],
  options: ChatExportOptions = {},
): string {
  const exportedAt = options.exportedAt ?? new Date()
  return JSON.stringify(
    {
      version: 1,
      exported_at: exportedAt.toISOString(),
      user: options.email ?? null,
      messages: messages.map((message) => ({
        role: message.role,
        content: message.content,
        created_at: message.createdAt ?? null,
        tool_calls: message.toolCalls.map((call) => ({
          name: call.function.name,
          arguments: call.function.arguments,
        })),
      })),
    },
    null,
    2,
  )
}

/** Имя файла вида `vetassistant-owner-example-com-2026-11-04.md`. */
export function chatExportFilename(
  email: string | undefined,
  exportedAt: Date,
  extension: 'md' | 'json',
): string {
  const owner = (email ?? 'user')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  const date = exportedAt.toISOString().slice(0, 10)
  return `vetassistant-${owner || 'user'}-${date}.${extension}`
}

/** Скачать историю диалога в браузере через Blob и object URL. */
export function downloadChatExport(
  messages: UiMessage[],
  options: ChatExportOptions = {},
): void {
  const exportedAt = options.exportedAt ?? new Date()
  const content = buildChatMarkdown(messages, { ...options, exportedAt })
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = chatExportFilename(options.email, exportedAt, 'md')
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

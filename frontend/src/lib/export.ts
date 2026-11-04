import type { UiMessage } from '../types'

export interface ChatExportOptions {
  email?: string
  exportedAt?: Date
}

function formatDate(value: string | undefined, fallback: Date): string {
  const date = value ? new Date(value) : fallback
  if (Number.isNaN(date.getTime())) {
    return 'дата неизвестна'
  }
  return date.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function messageHeading(message: UiMessage, exportedAt: Date): string {
  const role = message.role === 'user' ? 'Пользователь' : 'Ассистент'
  return `### ${role} — ${formatDate(message.createdAt, exportedAt)}`
}

/** Собрать Markdown-экспорт истории диалога. */
export function buildChatMarkdown(
  messages: UiMessage[],
  options: ChatExportOptions = {},
): string {
  const exportedAt = options.exportedAt ?? new Date()
  const lines = ['# История диалога VetAssistant', '']

  if (options.email) {
    lines.push(`- Пользователь: ${options.email}`)
  }
  lines.push(`- Экспортировано: ${formatDate(exportedAt.toISOString(), exportedAt)}`)
  lines.push('', '---', '')

  if (messages.length === 0) {
    lines.push('_История пуста._', '')
    return lines.join('\n')
  }

  for (const message of messages) {
    lines.push(messageHeading(message, exportedAt), '', message.content.trim() || '_Пустое сообщение_', '')
    if (message.toolCalls.length > 0) {
      lines.push('**Вызовы инструментов:**', '')
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

import i18n from '../i18n'
import type {
  ToolCall,
  ToolCallDelta,
  ToolDefinition,
} from '../types'

export const AVAILABLE_TOOLS: ToolDefinition[] = [
  {
    type: 'function',
    function: {
      name: 'book_appointment',
      description: 'Записать питомца на приём к ветеринарному врачу.',
      parameters: {
        type: 'object',
        properties: {
          date: {
            type: 'string',
            description: 'Дата приёма в формате YYYY-MM-DD.',
          },
          time: {
            type: 'string',
            description: 'Время приёма в формате HH:MM.',
          },
          pet_name: {
            type: 'string',
            description: 'Кличка питомца.',
          },
        },
        required: ['date', 'time', 'pet_name'],
        additionalProperties: false,
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'set_reminder',
      description: 'Создать напоминание, например дать питомцу таблетку.',
      parameters: {
        type: 'object',
        properties: {
          time: {
            type: 'string',
            description: 'Когда напомнить: ISO-время или понятная фраза.',
          },
          text: {
            type: 'string',
            description: 'Текст напоминания.',
          },
        },
        required: ['time', 'text'],
        additionalProperties: false,
      },
    },
  },
]

export function parseToolArguments(raw: string): Record<string, unknown> {
  try {
    const value: unknown = JSON.parse(raw)
    return typeof value === 'object' && value !== null && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {}
  } catch {
    return {}
  }
}

/**
 * Склеить инкрементальные tool_call-дельты OpenAI.
 *
 * Бэкенд присылает вызов целиком одним чанком, но формат OpenAI допускает
 * передачу имени и аргументов по частям — поддерживаем оба варианта.
 */
export function mergeToolCalls(
  current: ToolCall[],
  deltas: ToolCallDelta[],
): ToolCall[] {
  const next = current.map((call) => ({
    ...call,
    function: { ...call.function },
  }))

  for (const delta of deltas) {
    let index = typeof delta.index === 'number' ? delta.index : -1
    if (index < 0 && delta.id) {
      index = next.findIndex((call) => call.id === delta.id)
    }
    if (index < 0 || index > next.length) {
      index = next.length
    }

    let target = next[index]
    if (!target) {
      target = {
        id: delta.id ?? `call_${index}`,
        type: 'function',
        function: { name: '', arguments: '' },
      }
      next[index] = target
    }

    if (delta.id) {
      target.id = delta.id
    }

    const name = delta.function?.name
    if (name) {
      target.function.name =
        target.function.name === name
          ? name
          : `${target.function.name}${name}`
    }

    const args = delta.function?.arguments
    if (args) {
      target.function.arguments += args
    }
  }

  return next.filter(
    (call) => call.function.name.length > 0 || call.function.arguments.length > 0,
  )
}

export type ToolTone = 'success' | 'warning' | 'neutral'
export type ToolKind = 'calendar' | 'bell' | 'paw' | 'wrench'

/** Минимальный контракт перевода: хватает и `i18n.t`, и `t` из useTranslation. */
export type Translate = (
  key: string,
  options?: Record<string, unknown>,
) => string

const defaultTranslate: Translate = (key, options) =>
  (options ? i18n.t(key, options) : i18n.t(key)) as string

export interface ToolPresentation {
  title: string
  details: string
  tone: ToolTone
  kind: ToolKind
}

function stringArg(
  args: Record<string, unknown>,
  key: string,
): string | undefined {
  const value = args[key]
  if (typeof value === 'string' && value.trim()) {
    return value.trim()
  }
  if (typeof value === 'number') {
    return String(value)
  }
  return undefined
}

export function presentToolCall(
  call: ToolCall,
  t: Translate = defaultTranslate,
): ToolPresentation {
  const args = parseToolArguments(call.function.arguments)

  if (call.function.name === 'book_appointment') {
    const petName = stringArg(args, 'pet_name')
    const date = stringArg(args, 'date')
    const time = stringArg(args, 'time')
    const moment =
      date && time
        ? t('toolCall.moment', { date, time })
        : [date, time].filter(Boolean).join(' ')
    const details = [petName, moment].filter(Boolean).join(' · ')
    return {
      title: t('toolCall.appointmentTitle'),
      details: details || t('toolCall.appointmentFallback'),
      tone: 'success',
      kind: 'calendar',
    }
  }

  if (call.function.name === 'set_reminder') {
    const text = stringArg(args, 'text')
    const time = stringArg(args, 'time')
    const details = [text, time].filter(Boolean).join(' · ')
    return {
      title: t('toolCall.reminderTitle'),
      details: details || t('toolCall.reminderFallback'),
      tone: 'warning',
      kind: 'bell',
    }
  }

  if (call.function.name === 'create_patient') {
    const petName = stringArg(args, 'name')
    const species = stringArg(args, 'species')
    const speciesLabel =
      species === 'cat'
        ? t('patient.cat')
        : species === 'dog'
          ? t('patient.dog')
          : undefined
    const details = [petName, speciesLabel].filter(Boolean).join(' · ')
    return {
      title: t('toolCall.patientTitle'),
      details: details || t('toolCall.patientFallback'),
      tone: 'success',
      kind: 'paw',
    }
  }

  return {
    title: t('toolCall.unknownTitle', {
      name: call.function.name || t('toolCall.noName'),
    }),
    details: t('toolCall.unknownDetails'),
    tone: 'neutral',
    kind: 'wrench',
  }
}

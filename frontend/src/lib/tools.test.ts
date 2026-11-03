import { describe, expect, it } from 'vitest'
import {
  mergeToolCalls,
  parseToolArguments,
  presentToolCall,
} from './tools'
import type { ToolCall, ToolCallDelta } from '../types'

function call(
  name: string,
  args: string,
  id = 'call_1',
): ToolCall {
  return {
    id,
    type: 'function',
    function: { name, arguments: args },
  }
}

describe('mergeToolCalls', () => {
  it('сохраняет полный tool_call из бэкенда', () => {
    const delta: ToolCallDelta = {
      index: 0,
      id: 'call_1',
      type: 'function',
      function: {
        name: 'book_appointment',
        arguments: '{"pet_name":"Мурзик","date":"2026-11-04","time":"10:00"}',
      },
    }

    expect(mergeToolCalls([], [delta])).toEqual([
      call(
        'book_appointment',
        '{"pet_name":"Мурзик","date":"2026-11-04","time":"10:00"}',
      ),
    ])
  })

  it('склеивает инкрементальные имя и аргументы', () => {
    const deltas: ToolCallDelta[] = [
      {
        index: 0,
        id: 'call_1',
        function: { name: 'book_', arguments: '{"pet_' },
      },
      { index: 0, function: { name: 'appointment', arguments: 'name":"Мурзик"}' } },
    ]

    expect(mergeToolCalls([], deltas)).toEqual([
      call('book_appointment', '{"pet_name":"Мурзик"}'),
    ])
  })

  it('не дублирует полное имя, пришедшее повторно', () => {
    const current = [call('set_reminder', '{"text":"Таблетка",')]
    const delta: ToolCallDelta = {
      index: 0,
      function: { name: 'set_reminder', arguments: '"time":"09:00"}' },
    }

    expect(mergeToolCalls(current, [delta])).toEqual([
      call('set_reminder', '{"text":"Таблетка","time":"09:00"}'),
    ])
  })
})

describe('parseToolArguments', () => {
  it('возвращает объект для корректного JSON', () => {
    expect(parseToolArguments('{"pet_name":"Мурзик"}')).toEqual({
      pet_name: 'Мурзик',
    })
  })

  it('возвращает пустой объект для мусора', () => {
    expect(parseToolArguments('not-json')).toEqual({})
    expect(parseToolArguments('["Мурзик"]')).toEqual({})
  })
})

describe('presentToolCall', () => {
  it('описывает запись на приём', () => {
    const presentation = presentToolCall(
      call(
        'book_appointment',
        '{"pet_name":"Мурзик","date":"2026-11-04","time":"10:00"}',
      ),
    )

    expect(presentation.tone).toBe('success')
    expect(presentation.kind).toBe('calendar')
    expect(presentation.title).toBe('Запись на приём создана')
    expect(presentation.details).toContain('Мурзик')
    expect(presentation.details).toContain('2026-11-04 в 10:00')
  })

  it('описывает напоминание', () => {
    const presentation = presentToolCall(
      call('set_reminder', '{"text":"Дать таблетку","time":"09:00"}'),
    )

    expect(presentation.tone).toBe('warning')
    expect(presentation.kind).toBe('bell')
    expect(presentation.details).toContain('Дать таблетку')
  })

  it('не падает на неизвестном инструменте', () => {
    const presentation = presentToolCall(call('unknown_tool', 'not-json'))

    expect(presentation.tone).toBe('neutral')
    expect(presentation.title).toContain('unknown_tool')
  })
})

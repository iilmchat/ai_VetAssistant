import {
  Bell,
  BookOpen,
  CalendarDays,
  Loader2,
  LogOut,
  PawPrint,
  Plus,
  RefreshCw,
  Settings,
  ShieldAlert,
  SlidersHorizontal,
  UserRound,
  Wrench,
  X,
} from 'lucide-react'
import type {
  ApiStatus,
  Appointment,
  ChatSettings,
  Reminder,
} from '../types'
import { formatAppointmentMoment } from '../lib/format'
import { MODEL_ID } from '../lib/api'
import { Toggle } from './Toggle'

interface SidebarProps {
  open: boolean
  onClose: () => void
  settings: ChatSettings
  onSettingsChange: (patch: Partial<ChatSettings>) => void
  onNewChat: () => void
  appointments: Appointment[]
  reminders: Reminder[]
  recordsLoading: boolean
  recordsError: string | null
  onRefreshRecords: () => void
  apiStatus: ApiStatus
  userEmail: string
  onOpenSettings: () => void
  onLogout: () => void
}

function statusLabel(status: ApiStatus): string {
  if (status === 'online') {
    return 'API онлайн'
  }
  if (status === 'offline') {
    return 'API недоступен'
  }
  return 'Проверяю API…'
}

function statusColor(status: ApiStatus): string {
  if (status === 'online') {
    return 'bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.6)]'
  }
  if (status === 'offline') {
    return 'bg-rose-400'
  }
  return 'bg-amber-400'
}

export function Sidebar({
  open,
  onClose,
  settings,
  onSettingsChange,
  onNewChat,
  appointments,
  reminders,
  recordsLoading,
  recordsError,
  onRefreshRecords,
  apiStatus,
  userEmail,
  onOpenSettings,
  onLogout,
}: SidebarProps) {
  return (
    <>
      {open && (
        <button
          type="button"
          aria-label="Закрыть меню"
          onClick={onClose}
          className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm lg:hidden"
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex h-full w-[320px] max-w-[86vw] shrink-0 flex-col border-r border-white/10 bg-[#171717] transition-transform duration-300 ease-out lg:static lg:z-auto lg:translate-x-0 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex items-center gap-3 px-4 pb-3 pt-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-400 to-teal-600 text-zinc-950 shadow-[0_8px_20px_rgba(16,185,129,0.25)]">
            <PawPrint className="h-5 w-5" strokeWidth={2.4} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[15px] font-semibold tracking-tight text-white">
              VetAssistant
            </p>
            <p className="truncate text-[11px] text-zinc-500">
              ИИ-ветеринар для ваших питомцев
            </p>
          </div>
          <button
            type="button"
            aria-label="Закрыть меню"
            onClick={onClose}
            className="rounded-lg p-1.5 text-zinc-400 transition-colors hover:bg-white/5 hover:text-white lg:hidden"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="px-3">
          <button
            type="button"
            onClick={onNewChat}
            className="flex w-full items-center gap-2.5 rounded-xl border border-white/10 bg-white/[0.04] px-3.5 py-2.5 text-left text-[13px] font-medium text-zinc-100 transition-colors hover:border-emerald-500/30 hover:bg-emerald-500/10"
          >
            <Plus className="h-4 w-4 text-emerald-300" />
            Новый чат
          </button>
        </div>

        <div className="mt-5 flex-1 space-y-6 overflow-y-auto px-3 pb-4">
          <section>
            <div className="mb-2.5 flex items-center gap-2 px-1">
              <SlidersHorizontal className="h-3.5 w-3.5 text-zinc-500" />
              <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-500">
                Настройки
              </h2>
            </div>

            <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
              <div className="flex items-center justify-between gap-3">
                <label
                  htmlFor="temperature"
                  className="text-[13px] font-medium text-zinc-200"
                >
                  Temperature
                </label>
                <span className="rounded-md border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 font-mono text-[11px] text-emerald-300">
                  {settings.temperature.toFixed(2)}
                </span>
              </div>
              <input
                id="temperature"
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={settings.temperature}
                onChange={(event) =>
                  onSettingsChange({
                    temperature: Number(event.target.value),
                  })
                }
                className="mt-3 h-1.5 w-full cursor-pointer appearance-none rounded-full bg-zinc-700 accent-emerald-400"
              />
              <div className="mt-2 flex justify-between text-[10px] text-zinc-600">
                <span>Точно</span>
                <span>Творчески</span>
              </div>
            </div>

            <div className="mt-2 space-y-2">
              <Toggle
                icon={<BookOpen className="h-4 w-4" />}
                label="База знаний (RAG)"
                description="Фрагменты MSD Vet Manual в контексте"
                checked={settings.useRag}
                onChange={(useRag) => onSettingsChange({ useRag })}
              />
              <Toggle
                icon={<Wrench className="h-4 w-4" />}
                label="Function Calling"
                description="Запись на приём и напоминания"
                checked={settings.useTools}
                onChange={(useTools) => onSettingsChange({ useTools })}
              />
            </div>
          </section>

          <section>
            <div className="mb-2.5 flex items-center justify-between px-1">
              <div className="flex items-center gap-2">
                <CalendarDays className="h-3.5 w-3.5 text-zinc-500" />
                <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-500">
                  Мои записи
                </h2>
              </div>
              <button
                type="button"
                onClick={onRefreshRecords}
                disabled={recordsLoading}
                aria-label="Обновить записи"
                className="rounded-md p-1 text-zinc-500 transition-colors hover:bg-white/5 hover:text-zinc-200 disabled:opacity-50"
              >
                <RefreshCw
                  className={`h-3.5 w-3.5 ${recordsLoading ? 'animate-spin' : ''}`}
                />
              </button>
            </div>

            {recordsLoading && appointments.length === 0 && reminders.length === 0 ? (
              <div className="flex items-center justify-center gap-2 rounded-xl border border-white/5 bg-white/[0.02] py-6 text-xs text-zinc-500">
                <Loader2 className="h-4 w-4 animate-spin" />
                Загружаю записи…
              </div>
            ) : recordsError ? (
              <div className="rounded-xl border border-rose-500/20 bg-rose-500/[0.06] p-3 text-xs leading-5 text-rose-300">
                {recordsError}
              </div>
            ) : appointments.length === 0 && reminders.length === 0 ? (
              <div className="rounded-xl border border-dashed border-white/10 p-3 text-center text-[11px] leading-5 text-zinc-500">
                Пока нет записей и напоминаний.
                <br />
                Включите Function Calling и попросите записать питомца.
              </div>
            ) : (
              <div className="space-y-2">
                {appointments.map((appointment) => (
                  <div
                    key={`appointment-${appointment.id}`}
                    className="rounded-xl border border-emerald-500/15 bg-emerald-500/[0.055] p-3"
                  >
                    <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-300/80">
                      <CalendarDays className="h-3 w-3" />
                      Приём
                    </div>
                    <p className="mt-1.5 truncate text-[13px] font-medium text-zinc-100">
                      {appointment.pet_name}
                    </p>
                    <p className="mt-0.5 text-[11px] text-zinc-400">
                      {formatAppointmentMoment(
                        appointment.date,
                        appointment.time,
                      )}
                    </p>
                  </div>
                ))}

                {reminders.map((reminder) => (
                  <div
                    key={`reminder-${reminder.id}`}
                    className="rounded-xl border border-amber-500/15 bg-amber-500/[0.055] p-3"
                  >
                    <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-amber-300/80">
                      <Bell className="h-3 w-3" />
                      Напоминание
                    </div>
                    <p className="mt-1.5 text-[13px] font-medium leading-5 text-zinc-100">
                      {reminder.text}
                    </p>
                    <p className="mt-0.5 text-[11px] text-zinc-400">
                      {reminder.time}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>

        <div className="border-t border-white/10 px-4 py-3.5">
          <div className="mb-3 flex items-center gap-2.5 rounded-xl border border-white/[0.07] bg-white/[0.03] px-2.5 py-2">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-300">
              <UserRound className="h-3.5 w-3.5" />
            </div>
            <span
              title={userEmail}
              className="min-w-0 flex-1 truncate text-[11.5px] text-zinc-300"
            >
              {userEmail}
            </span>
            <button
              type="button"
              onClick={onOpenSettings}
              aria-label="Настройки"
              title="Настройки"
              className="rounded-md p-1.5 text-zinc-500 transition-colors hover:bg-white/5 hover:text-zinc-200"
            >
              <Settings className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={onLogout}
              aria-label="Выйти"
              title="Выйти"
              className="rounded-md p-1.5 text-zinc-500 transition-colors hover:bg-rose-500/10 hover:text-rose-300"
            >
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>

          <div className="flex items-center gap-2 text-[11px] text-zinc-500">
            <span
              className={`h-1.5 w-1.5 rounded-full ${statusColor(apiStatus)}`}
            />
            <span>{statusLabel(apiStatus)}</span>
            <span className="ml-auto max-w-[110px] truncate font-mono text-[10px] text-zinc-600">
              {MODEL_ID}
            </span>
          </div>
          <p className="mt-2.5 flex items-start gap-1.5 text-[10px] leading-4 text-zinc-600">
            <ShieldAlert className="mt-0.5 h-3 w-3 shrink-0" />
            Не заменяет осмотр и назначения ветеринарного врача.
          </p>
        </div>
      </aside>
    </>
  )
}

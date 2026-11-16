import { useTranslation } from 'react-i18next'
import {
  Bell,
  BookOpen,
  CalendarDays,
  Download,
  Loader2,
  LogOut,
  PawPrint,
  Plus,
  RefreshCw,
  Settings,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  UserRound,
  Wrench,
  X,
} from 'lucide-react'
import type {
  ApiStatus,
  Appointment,
  ChatSettings,
  Patient,
  Reminder,
} from '../types'
import { formatAppointmentMoment } from '../lib/format'
import { MODEL_ID } from '../lib/api'
import { LanguageSwitcher } from './LanguageSwitcher'
import { ThemeSwitcher } from './ThemeSwitcher'
import { Toggle } from './Toggle'

interface SidebarProps {
  open: boolean
  onClose: () => void
  settings: ChatSettings
  onSettingsChange: (patch: Partial<ChatSettings>) => void
  onNewChat: () => void
  canExport: boolean
  onExportHistory: () => void
  appointments: Appointment[]
  reminders: Reminder[]
  patients: Patient[]
  patientsLoading: boolean
  patientsError: string | null
  activePatientId: number | null
  onSelectPatient: (patientId: number | null) => void
  onOpenPatientCard: () => void
  onCreatePatient: () => void
  onRefreshPatients: () => void
  recordsLoading: boolean
  recordsError: string | null
  onRefreshRecords: () => void
  apiStatus: ApiStatus
  userEmail: string
  isAdmin: boolean
  onOpenAdmin: () => void
  onOpenSettings: () => void
  onLogout: () => void
}

function statusKey(status: ApiStatus): string {
  if (status === 'online') {
    return 'app.apiOnline'
  }
  if (status === 'offline') {
    return 'app.apiOffline'
  }
  return 'sidebar.apiChecking'
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
  canExport,
  onExportHistory,
  appointments,
  reminders,
  patients,
  patientsLoading,
  patientsError,
  activePatientId,
  onSelectPatient,
  onOpenPatientCard,
  onCreatePatient,
  onRefreshPatients,
  recordsLoading,
  recordsError,
  onRefreshRecords,
  apiStatus,
  userEmail,
  isAdmin,
  onOpenAdmin,
  onOpenSettings,
  onLogout,
}: SidebarProps) {
  const { t, i18n } = useTranslation()
  const activePatient =
    patients.find((patient) => patient.id === activePatientId) ?? null

  return (
    <>
      {open && (
        <button
          type="button"
          aria-label={t('sidebar.closeMenu')}
          onClick={onClose}
          className="fixed inset-0 z-30 bg-overlay backdrop-blur-sm md:hidden"
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex h-full w-[320px] max-w-[86vw] shrink-0 flex-col overscroll-contain border-r border-line bg-panel shadow-2xl transition-transform duration-300 ease-out md:static md:z-auto md:translate-x-0 md:shadow-none ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex items-center gap-3 px-4 pb-3 pt-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-400 to-teal-600 text-zinc-950 shadow-[0_8px_20px_rgba(16,185,129,0.25)]">
            <PawPrint className="h-5 w-5" strokeWidth={2.4} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[15px] font-semibold tracking-tight text-ink-strong">
              VetAssistant
            </p>
            <p className="truncate text-[11px] text-ink-muted">
              {t('sidebar.tagline')}
            </p>
          </div>
          <button
            type="button"
            aria-label={t('sidebar.closeMenu')}
            onClick={onClose}
            className="rounded-lg p-1.5 text-ink-soft transition-colors hover:bg-hover hover:text-ink-strong md:hidden"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="px-3">
          <button
            type="button"
            onClick={onNewChat}
            className="flex w-full items-center gap-2.5 rounded-xl border border-line bg-tint-2 px-3.5 py-2.5 text-left text-[13px] font-medium text-ink transition-colors hover:border-emerald-500/30 hover:bg-emerald-500/10"
          >
            <Plus className="h-4 w-4 text-accent" />
            {t('sidebar.newChat')}
          </button>

          <button
            type="button"
            onClick={onExportHistory}
            disabled={!canExport}
            title={
              canExport ? t('sidebar.exportTitle') : t('sidebar.exportEmpty')
            }
            className="mt-2 flex w-full items-center gap-2.5 rounded-xl border border-line bg-tint px-3.5 py-2.5 text-left text-[13px] font-medium text-ink-soft transition-colors hover:border-emerald-500/25 hover:bg-hover hover:text-ink-strong disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-line disabled:hover:bg-tint"
          >
            <Download className="h-4 w-4 text-ink-soft" />
            {t('sidebar.export')}
          </button>
        </div>

        {isAdmin && (
          <div className="mt-2 px-3">
            <button
              type="button"
              onClick={onOpenAdmin}
              className="flex w-full items-center gap-2.5 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.07] px-3.5 py-2.5 text-left text-[13px] font-medium text-accent-strong transition-colors hover:border-emerald-500/35 hover:bg-emerald-500/15"
            >
              <ShieldCheck className="h-4 w-4 text-accent" />
              {t('sidebar.admin')}
            </button>
          </div>
        )}

        <div className="mt-5 flex-1 space-y-6 overflow-y-auto px-3 pb-4">
          <section>
            <div className="mb-2.5 flex items-center justify-between px-1">
              <div className="flex items-center gap-2">
                <PawPrint className="h-3.5 w-3.5 text-ink-muted" />
                <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
                  {t('patient.pickerLabel')}
                </h2>
              </div>
              <button
                type="button"
                onClick={onRefreshPatients}
                disabled={patientsLoading}
                aria-label={t('patient.refresh')}
                className="rounded-md p-1 text-ink-muted transition-colors hover:bg-hover hover:text-ink disabled:opacity-50"
              >
                <RefreshCw
                  className={`h-3.5 w-3.5 ${patientsLoading ? 'animate-spin' : ''}`}
                />
              </button>
            </div>

            <div className="rounded-xl border border-line-soft bg-tint p-3">
              <div className="flex items-center gap-2">
                <select
                  aria-label={t('patient.pickerLabel')}
                  value={activePatientId ?? ''}
                  onChange={(event) => {
                    const value = event.target.value
                    onSelectPatient(value ? Number(value) : null)
                  }}
                  disabled={patientsLoading && patients.length === 0}
                  className="min-w-0 flex-1 rounded-lg border border-line bg-panel px-2.5 py-2 text-[12.5px] text-ink outline-none transition-colors focus:border-emerald-500/40 disabled:opacity-60"
                >
                  <option value="">{t('patient.noPatient')}</option>
                  {patients.map((patient) => (
                    <option key={patient.id} value={patient.id}>
                      {patient.name} ·{' '}
                      {patient.species === 'cat'
                        ? t('patient.cat')
                        : t('patient.dog')}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={onCreatePatient}
                  aria-label={t('patient.add')}
                  title={t('patient.add')}
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-emerald-500/25 bg-emerald-500/10 text-accent transition-colors hover:border-emerald-500/40 hover:bg-emerald-500/15"
                >
                  <Plus className="h-4 w-4" />
                </button>
              </div>

              {patientsError ? (
                <p className="mt-2 text-[10.5px] leading-4 text-danger">
                  {patientsError}
                </p>
              ) : patientsLoading && patients.length === 0 ? (
                <p className="mt-2 flex items-center gap-1.5 text-[10.5px] text-ink-muted">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  {t('patient.loading')}
                </p>
              ) : patients.length === 0 ? (
                <button
                  type="button"
                  onClick={onCreatePatient}
                  className="mt-2 w-full rounded-lg border border-dashed border-line px-2.5 py-2 text-left text-[10.5px] leading-4 text-ink-muted transition-colors hover:border-emerald-500/30 hover:text-ink-soft"
                >
                  {t('patient.emptyHint')}
                </button>
              ) : activePatient ? (
                <button
                  type="button"
                  onClick={onOpenPatientCard}
                  className="mt-2 flex w-full items-center justify-between gap-2 rounded-lg border border-line px-2.5 py-1.5 text-[11px] text-ink-soft transition-colors hover:border-emerald-500/25 hover:bg-hover hover:text-ink"
                >
                  <span className="truncate">
                    {activePatient.breed || t('patient.openCard')}
                  </span>
                  <span className="shrink-0 text-[10px] text-accent">
                    {t('patient.cardAction')}
                  </span>
                </button>
              ) : null}
            </div>
          </section>

          <section>
            <div className="mb-2.5 flex items-center gap-2 px-1">
              <SlidersHorizontal className="h-3.5 w-3.5 text-ink-muted" />
              <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
                {t('sidebar.settings')}
              </h2>
            </div>

            <div className="rounded-xl border border-line-soft bg-tint p-3">
              <div className="flex items-center justify-between gap-3">
                <label
                  htmlFor="temperature"
                  className="text-[13px] font-medium text-ink"
                >
                  {t('sidebar.temperature')}
                </label>
                <span className="rounded-md border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 font-mono text-[11px] text-accent">
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
                className="mt-3 h-1.5 w-full cursor-pointer appearance-none rounded-full bg-track accent-emerald-400"
              />
              <div className="mt-2 flex justify-between text-[10px] text-ink-faint">
                <span>{t('sidebar.precise')}</span>
                <span>{t('sidebar.creative')}</span>
              </div>
            </div>

            <div className="mt-2 space-y-2">
              <Toggle
                icon={<BookOpen className="h-4 w-4" />}
                label={t('sidebar.ragLabel')}
                description={t('sidebar.ragDescription')}
                checked={settings.useRag}
                onChange={(useRag) => onSettingsChange({ useRag })}
              />
              <Toggle
                icon={<Wrench className="h-4 w-4" />}
                label={t('sidebar.toolsLabel')}
                description={t('sidebar.toolsDescription')}
                checked={settings.useTools}
                onChange={(useTools) => onSettingsChange({ useTools })}
              />
            </div>
          </section>

          <section>
            <div className="mb-2.5 flex items-center justify-between px-1">
              <div className="flex items-center gap-2">
                <CalendarDays className="h-3.5 w-3.5 text-ink-muted" />
                <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
                  {t('sidebar.records')}
                </h2>
              </div>
              <button
                type="button"
                onClick={onRefreshRecords}
                disabled={recordsLoading}
                aria-label={t('sidebar.refreshRecords')}
                className="rounded-md p-1 text-ink-muted transition-colors hover:bg-hover hover:text-ink disabled:opacity-50"
              >
                <RefreshCw
                  className={`h-3.5 w-3.5 ${recordsLoading ? 'animate-spin' : ''}`}
                />
              </button>
            </div>

            {recordsLoading && appointments.length === 0 && reminders.length === 0 ? (
              <div className="flex items-center justify-center gap-2 rounded-xl border border-line-soft bg-tint py-6 text-xs text-ink-muted">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t('sidebar.loadingRecords')}
              </div>
            ) : recordsError ? (
              <div className="rounded-xl border border-rose-500/20 bg-rose-500/[0.06] p-3 text-xs leading-5 text-danger">
                {recordsError}
              </div>
            ) : appointments.length === 0 && reminders.length === 0 ? (
              <div className="rounded-xl border border-dashed border-line p-3 text-center text-[11px] leading-5 text-ink-muted">
                {t('sidebar.noRecords')}
                <br />
                {t('sidebar.noRecordsHint')}
              </div>
            ) : (
              <div className="space-y-2">
                {appointments.map((appointment) => (
                  <div
                    key={`appointment-${appointment.id}`}
                    className="rounded-xl border border-emerald-500/15 bg-emerald-500/[0.055] p-3"
                  >
                    <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-accent/80">
                      <CalendarDays className="h-3 w-3" />
                      {t('sidebar.appointment')}
                    </div>
                    <p className="mt-1.5 truncate text-[13px] font-medium text-ink">
                      {appointment.pet_name}
                    </p>
                    <p className="mt-0.5 text-[11px] text-ink-soft">
                      {formatAppointmentMoment(
                        appointment.date,
                        appointment.time,
                        i18n.language,
                      )}
                    </p>
                  </div>
                ))}

                {reminders.map((reminder) => (
                  <div
                    key={`reminder-${reminder.id}`}
                    className="rounded-xl border border-amber-500/15 bg-amber-500/[0.055] p-3"
                  >
                    <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-warn/80">
                      <Bell className="h-3 w-3" />
                      {t('sidebar.reminder')}
                    </div>
                    <p className="mt-1.5 text-[13px] font-medium leading-5 text-ink">
                      {reminder.text}
                    </p>
                    <p className="mt-0.5 text-[11px] text-ink-soft">
                      {reminder.time}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>

        <div className="border-t border-line px-4 py-3.5">
          <div className="mb-3 flex items-center justify-between gap-2">
            <ThemeSwitcher />
            <LanguageSwitcher />
          </div>
          <div className="mb-3 flex items-center gap-2.5 rounded-xl border border-line-soft bg-tint px-2.5 py-2">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-accent">
              <UserRound className="h-3.5 w-3.5" />
            </div>
            <span
              title={userEmail}
              className="min-w-0 flex-1 truncate text-[11.5px] text-ink-soft"
            >
              {userEmail}
            </span>
            <button
              type="button"
              onClick={onOpenSettings}
              aria-label={t('sidebar.openSettings')}
              title={t('sidebar.openSettings')}
              className="rounded-md p-1.5 text-ink-muted transition-colors hover:bg-hover hover:text-ink"
            >
              <Settings className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={onLogout}
              aria-label={t('sidebar.logout')}
              title={t('sidebar.logout')}
              className="rounded-md p-1.5 text-ink-muted transition-colors hover:bg-rose-500/10 hover:text-danger"
            >
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>

          <div className="flex items-center gap-2 text-[11px] text-ink-muted">
            <span
              className={`h-1.5 w-1.5 rounded-full ${statusColor(apiStatus)}`}
            />
            <span>{t(statusKey(apiStatus))}</span>
            <span className="ml-auto max-w-[110px] truncate font-mono text-[10px] text-ink-faint">
              {MODEL_ID}
            </span>
          </div>
          <p className="mt-2.5 flex items-start gap-1.5 text-[10px] leading-4 text-ink-faint">
            <ShieldAlert className="mt-0.5 h-3 w-3 shrink-0" />
            {t('sidebar.disclaimer')}
          </p>
        </div>
      </aside>
    </>
  )
}

import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Loader2, PawPrint, X } from 'lucide-react'
import type {
  Patient,
  PatientEpisode,
  PatientInput,
  PatientSpecies,
} from '../types'
import { createPatient, fetchPatientHistory, updatePatient } from '../lib/api'
import { errorMessage } from '../lib/utils'

const HISTORY_PAGE_SIZE = 10

interface PatientCardDialogProps {
  /** `null` — создание новой карточки. */
  patient: Patient | null
  onClose: () => void
  onSaved: (patient: Patient) => void
}

function formatEpisodeDate(value: string, language: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }
  return parsed.toLocaleDateString(language, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

export function PatientCardDialog({
  patient,
  onClose,
  onSaved,
}: PatientCardDialogProps) {
  const { t, i18n } = useTranslation()
  const isCreate = patient === null

  const [name, setName] = useState(patient?.name ?? '')
  const [species, setSpecies] = useState<PatientSpecies>(
    patient?.species ?? 'dog',
  )
  const [breed, setBreed] = useState(patient?.breed ?? '')
  const [birthDate, setBirthDate] = useState(patient?.birth_date ?? '')
  const [weight, setWeight] = useState(
    patient?.weight !== null && patient?.weight !== undefined
      ? String(patient.weight)
      : '',
  )
  const [allergies, setAllergies] = useState(patient?.known_allergies ?? '')
  const [chronic, setChronic] = useState(patient?.chronic_conditions ?? '')

  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [history, setHistory] = useState<PatientEpisode[]>([])
  const [historyTotal, setHistoryTotal] = useState(0)
  const [historyLoading, setHistoryLoading] = useState(patient !== null)
  const [historyError, setHistoryError] = useState<string | null>(null)

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  useEffect(() => {
    if (patient === null) {
      return
    }
    let active = true
    void fetchPatientHistory(patient.id, { limit: HISTORY_PAGE_SIZE, offset: 0 })
      .then((page) => {
        if (!active) {
          return
        }
        setHistory(page.items)
        setHistoryTotal(page.total)
        setHistoryError(null)
      })
      .catch((cause: unknown) => {
        if (active) {
          setHistoryError(
            t('patient.historyError', { error: errorMessage(cause) }),
          )
        }
      })
      .finally(() => {
        if (active) {
          setHistoryLoading(false)
        }
      })
    return () => {
      active = false
    }
  }, [patient, t])

  async function loadMoreHistory() {
    if (patient === null || historyLoading) {
      return
    }
    setHistoryLoading(true)
    try {
      const page = await fetchPatientHistory(patient.id, {
        limit: HISTORY_PAGE_SIZE,
        offset: history.length,
      })
      setHistory((previous) => [...previous, ...page.items])
      setHistoryTotal(page.total)
      setHistoryError(null)
    } catch (cause) {
      setHistoryError(t('patient.historyError', { error: errorMessage(cause) }))
    } finally {
      setHistoryLoading(false)
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (saving) {
      return
    }
    const trimmedName = name.trim()
    if (!trimmedName) {
      setError(t('patient.nameRequired'))
      return
    }

    let parsedWeight: number | null = null
    if (weight.trim()) {
      parsedWeight = Number(weight)
      if (!Number.isFinite(parsedWeight) || parsedWeight <= 0) {
        setError(t('patient.weightInvalid'))
        return
      }
    }

    const payload: PatientInput = {
      name: trimmedName,
      species,
      breed: breed.trim() || null,
      birth_date: birthDate || null,
      weight: parsedWeight,
      known_allergies: allergies.trim() || null,
      chronic_conditions: chronic.trim() || null,
    }

    setSaving(true)
    setError(null)
    try {
      const saved =
        patient === null
          ? await createPatient(payload)
          : await updatePatient(patient.id, payload)
      onSaved(saved)
    } catch (cause) {
      setError(t('patient.saveError', { error: errorMessage(cause) }))
    } finally {
      setSaving(false)
    }
  }

  const inputClass =
    'mt-1 w-full rounded-lg border border-line bg-tint px-3 py-2 text-[13px] text-ink outline-none transition-colors placeholder:text-ink-faint focus:border-emerald-500/40 focus:bg-tint-2'
  const labelClass = 'text-[11px] font-medium uppercase tracking-wide text-ink-muted'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-overlay px-4 py-8 backdrop-blur-sm"
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose()
        }
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="patient-card-title"
        className="relative max-h-[88vh] w-full max-w-[520px] overflow-y-auto rounded-2xl border border-line bg-panel-2 p-5 shadow-2xl shadow-black/50"
      >
        <div className="mb-5 flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-500/15 text-accent">
            <PawPrint className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h2
              id="patient-card-title"
              className="text-[15px] font-semibold text-ink-strong"
            >
              {isCreate ? t('patient.createTitle') : t('patient.editTitle')}
            </h2>
            <p className="mt-0.5 text-[11.5px] leading-4 text-ink-muted">
              {t('patient.subtitle')}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('patient.close')}
            className="rounded-lg p-1.5 text-ink-muted transition-colors hover:bg-hover hover:text-ink"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={(event) => void handleSubmit(event)} className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className={labelClass}>{t('patient.name')}</span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
                maxLength={120}
                className={inputClass}
                placeholder={t('patient.namePlaceholder')}
              />
            </label>
            <label className="block">
              <span className={labelClass}>{t('patient.species')}</span>
              <select
                value={species}
                onChange={(event) =>
                  setSpecies(event.target.value as PatientSpecies)
                }
                className={inputClass}
              >
                <option value="dog">{t('patient.dog')}</option>
                <option value="cat">{t('patient.cat')}</option>
              </select>
            </label>
            <label className="block">
              <span className={labelClass}>{t('patient.breed')}</span>
              <input
                value={breed}
                onChange={(event) => setBreed(event.target.value)}
                maxLength={120}
                className={inputClass}
              />
            </label>
            <label className="block">
              <span className={labelClass}>{t('patient.birthDate')}</span>
              <input
                type="date"
                value={birthDate}
                onChange={(event) => setBirthDate(event.target.value)}
                className={inputClass}
              />
            </label>
            <label className="block">
              <span className={labelClass}>{t('patient.weight')}</span>
              <input
                type="number"
                min="0.01"
                max="9999"
                step="0.01"
                value={weight}
                onChange={(event) => setWeight(event.target.value)}
                className={inputClass}
              />
            </label>
            <label className="block">
              <span className={labelClass}>{t('patient.allergies')}</span>
              <input
                value={allergies}
                onChange={(event) => setAllergies(event.target.value)}
                maxLength={2000}
                className={inputClass}
              />
            </label>
          </div>
          <label className="block">
            <span className={labelClass}>{t('patient.chronic')}</span>
            <textarea
              value={chronic}
              onChange={(event) => setChronic(event.target.value)}
              maxLength={2000}
              rows={2}
              className={`${inputClass} resize-y`}
            />
          </label>

          {error && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-lg border border-rose-500/20 bg-rose-500/[0.07] px-3 py-2 text-[11.5px] leading-4 text-danger"
            >
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-line px-3.5 py-2 text-[12px] font-medium text-ink-soft transition-colors hover:bg-hover hover:text-ink"
            >
              {t('patient.cancel')}
            </button>
            <button
              type="submit"
              disabled={saving}
              className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-3.5 py-2 text-[12px] font-semibold text-zinc-950 transition-colors hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {saving ? t('patient.saving') : t('patient.save')}
            </button>
          </div>
        </form>

        {patient !== null && (
          <section className="mt-5 border-t border-line pt-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-[11px] font-semibold uppercase tracking-wide text-ink-muted">
                {t('patient.history')}
              </h3>
              <span className="text-[10.5px] text-ink-faint">
                {t('patient.historyCount', { count: historyTotal })}
              </span>
            </div>

            {historyLoading && history.length === 0 ? (
              <div className="flex items-center gap-2 py-3 text-[11.5px] text-ink-muted">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                {t('patient.historyLoading')}
              </div>
            ) : historyError ? (
              <p className="rounded-lg border border-rose-500/20 bg-rose-500/[0.06] px-3 py-2 text-[11.5px] text-danger">
                {historyError}
              </p>
            ) : history.length === 0 ? (
              <p className="text-[11.5px] text-ink-muted">
                {t('patient.historyEmpty')}
              </p>
            ) : (
              <div className="space-y-2">
                {history.map((episode) => (
                  <div
                    key={episode.id}
                    className="rounded-xl border border-line-soft bg-tint px-3 py-2"
                  >
                    <div className="flex items-center justify-between gap-2 text-[10px] uppercase tracking-wide text-ink-faint">
                      <span>{t(`patient.episodeType.${episode.type}`)}</span>
                      <span>
                        {formatEpisodeDate(episode.created_at, i18n.language)}
                      </span>
                    </div>
                    <p className="mt-1 break-words text-[11.5px] leading-5 text-ink-soft">
                      {episode.content}
                    </p>
                  </div>
                ))}
                {history.length < historyTotal && (
                  <button
                    type="button"
                    onClick={() => void loadMoreHistory()}
                    disabled={historyLoading}
                    className="w-full rounded-lg border border-line px-3 py-1.5 text-[11.5px] text-ink-soft transition-colors hover:bg-hover disabled:opacity-50"
                  >
                    {historyLoading ? t('patient.loadingMore') : t('patient.loadMore')}
                  </button>
                )}
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  )
}

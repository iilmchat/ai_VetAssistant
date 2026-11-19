import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Download } from 'lucide-react'
import {
  isBeforeInstallPromptEvent,
  isStandalone,
} from '../lib/pwa'
import type { BeforeInstallPromptEvent } from '../lib/pwa'

/** Кнопка «Установить приложение», появляется только когда браузер разрешил. */
export function PwaInstallButton() {
  const { t } = useTranslation()
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null)

  useEffect(() => {
    if (isStandalone()) {
      return
    }

    function handlePrompt(event: Event) {
      event.preventDefault()
      if (isBeforeInstallPromptEvent(event)) {
        setDeferred(event)
      }
    }
    function handleInstalled() {
      setDeferred(null)
    }

    window.addEventListener('beforeinstallprompt', handlePrompt)
    window.addEventListener('appinstalled', handleInstalled)
    return () => {
      window.removeEventListener('beforeinstallprompt', handlePrompt)
      window.removeEventListener('appinstalled', handleInstalled)
    }
  }, [])

  if (!deferred || isStandalone()) {
    return null
  }

  async function handleInstall() {
    if (!deferred) {
      return
    }
    await deferred.prompt()
    setDeferred(null)
  }

  return (
    <button
      type="button"
      onClick={() => void handleInstall()}
      title={t('pwa.installTitle')}
      aria-label={t('pwa.install')}
      className="hidden items-center gap-1.5 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-medium text-accent transition-colors hover:bg-emerald-500/20 sm:inline-flex"
    >
      <Download className="h-3 w-3" />
      {t('pwa.install')}
    </button>
  )
}

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './i18n'
import { applyTheme, readStoredTheme } from './lib/theme'
import { registerServiceWorker } from './lib/pwa'
import { setupNativeShell } from './lib/native'
import { restoreAuthSession } from './lib/auth'
import { setAuthToken } from './lib/api'
import App from './App.tsx'

/** До рендера восстанавливаем сессию из 안전ного хранилища платформы. */
async function bootstrap() {
  applyTheme(readStoredTheme())

  const session = await restoreAuthSession()
  setAuthToken(session?.access_token ?? null)

  void setupNativeShell()
  registerServiceWorker()

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App initialSession={session} />
    </StrictMode>,
  )
}

void bootstrap()

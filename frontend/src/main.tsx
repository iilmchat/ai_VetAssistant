import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './i18n'
import { applyTheme, readStoredTheme } from './lib/theme'
import { registerServiceWorker } from './lib/pwa'
import App from './App.tsx'

// Тему применяем до первого рендера, чтобы не было вспышки тёмного фона.
applyTheme(readStoredTheme())
registerServiceWorker()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

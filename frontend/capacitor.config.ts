import type { CapacitorConfig } from '@capacitor/cli'

/** Конфигурация Android-обёртки VetAssistant (T-179, T-180). */
const config: CapacitorConfig = {
  appId: 'ru.vetassistant.app',
  appName: 'VetAssistant',
  webDir: 'dist',
  server: {
    // HTTPS-схема нужна для Service Worker, WebView и безопасных запросов.
    androidScheme: 'https',
  },
  android: {
    allowMixedContent: false,
    captureInput: true,
  },
  plugins: {
    SplashScreen: {
      launchShowDuration: 600,
      backgroundColor: '#171717',
      androidSplashResourceName: 'splash',
      showSpinner: false,
    },
    StatusBar: {
      style: 'DARK',
      backgroundColor: '#171717',
      overlaysWebView: true,
    },
    Keyboard: {
      resizeOnFullScreen: true,
    },
  },
}

export default config

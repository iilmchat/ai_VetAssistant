/** Нативная оболочка Capacitor: статус-бар, splash и кнопка «Назад» (T-180). */

import { Capacitor } from '@capacitor/core'

/** Приложение запущено внутри Capacitor (Android), а не в браузере. */
export function isNativeApp(): boolean {
  return Capacitor.isNativePlatform()
}

/** Применить нативную тему и скрыть splash после готовности WebView. */
export async function setupNativeShell(): Promise<void> {
  if (!isNativeApp()) {
    return
  }

  try {
    const [{ StatusBar, Style }, { SplashScreen }] = await Promise.all([
      import('@capacitor/status-bar'),
      import('@capacitor/splash-screen'),
    ])
    await StatusBar.setOverlaysWebView({ overlay: true })
    await StatusBar.setStyle({ style: Style.Dark })
    await StatusBar.setBackgroundColor({ color: '#171717' })
    await SplashScreen.hide()
  } catch {
    // Нативные плагины — улучшение: сбой не должен блокировать рендер чата.
  }
}

/** Обработать системную кнопку «Назад». Возвращает функцию отписки. */
export async function registerNativeBack(
  onBack: () => boolean,
): Promise<() => void> {
  if (!isNativeApp()) {
    return () => {}
  }

  try {
    const { App: CapacitorApp } = await import('@capacitor/app')
    const handle = await CapacitorApp.addListener('backButton', () => {
      if (!onBack()) {
        void CapacitorApp.minimizeApp()
      }
    })
    return () => {
      void handle.remove()
    }
  } catch {
    return () => {}
  }
}

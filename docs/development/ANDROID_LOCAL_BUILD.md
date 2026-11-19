# Локальная сборка Android-приложения (T-179, T-182)

## Что уже есть

- `frontend/capacitor.config.ts` — `appId: ru.vetassistant.app`, `webDir: dist`,
  HTTPS-схема WebView и настройки SplashScreen/StatusBar/Keyboard.
- `frontend/android/` — сгенерированный Capacitor 8 проект (Gradle, манифест,
  launcher-иконки и splash с лапой VetAssistant).
- Скрипты `android:add`, `android:sync`, `android:build`, `android:open` в
  `frontend/package.json`.

Скопированные веб-ассеты (`android/app/src/main/assets/public`) и
сгенерированные `capacitor.config.json` / `capacitor.plugins.json` намеренно
не хранятся в Git — они создаются командой `cap sync`.

## Требования к окружению

- Node.js **22** (как в CI и Vite 8).
- JDK **21**.
- Android SDK **platform 36** и Build Tools (устанавливаются через Android Studio
  или `android-actions/setup-android` в CI).
- Для release-сборки — keystore (см. ниже).

## Команды

```bash
cd frontend
npm ci
npm run build          # dist/
npm run android:sync   # копирует dist в android/app/src/main/assets/public
npm run android:open   # открыть проект в Android Studio
```

Debug-сборка без подписи (для проверки на устройстве/эмуляторе):

```bash
cd frontend/android
./gradlew assembleDebug --no-daemon
# APK: app/build/outputs/apk/debug/app-debug.apk
```

## Подпись release-сборки

Секреты хранятся у владельца аккаунта (Андрей Н.). В CI это GitHub Secrets:

| Секрет | Назначение |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | base64-содержимое файла `*.jks` |
| `ANDROID_KEYSTORE_PASSWORD` | пароль хранилища |
| `ANDROID_KEY_ALIAS` | alias ключа |
| `ANDROID_KEY_PASSWORD` | пароль ключа |

Локально можно передать те же значения через окружение:

```powershell
$env:ANDROID_KEYSTORE_FILE = "C:\path\to\vetassistant.jks"
$env:ANDROID_KEYSTORE_PASSWORD = "..."
$env:ANDROID_KEY_ALIAS = "vetassistant"
$env:ANDROID_KEY_PASSWORD = "..."
$env:ANDROID_VERSION_CODE = "1"
$env:ANDROID_VERSION_NAME = "1.0.0-android"

cd frontend/android
.\gradlew.bat bundleRelease assembleRelease --no-daemon
```

Результат: `app/build/outputs/bundle/release/app-release.aab` и
`app/build/outputs/apk/release/app-release.apk`.

**Важно:** один и тот же сертификат используется для всех версий. Потеря
ключа означает невозможность обновить приложение; смена подписи — только
через `support@rustore.ru` с архивацией всех версий.

## CI

- `ci.yml` → job `android-build`: всегда собирает debug APK; при наличии
  секретов — подписанные AAB/APK и загружает артефакт `android-release`.
- `release.yml` → job `android-release`: по тегу `v*` при наличии секретов
  прикрепляет AAB/APK к GitHub Release.

Пока секреты не заданы, release-задача быстро завершается без сборки — это
ожидаемое поведение, а не ошибка CI.

## Загрузка в RuStore

Делается вручную в [RuStore Console](https://console.rustore.ru) до появления
отдельной автоматизации (T-189): «Приложения» → создать приложение →
«Загрузить версию» → AAB + отдельная загрузка подписи. После обработки файла
есть **14 дней** на отправку на модерацию.

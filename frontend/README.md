# VetAssistant — React-фронтенд

Современный чат-интерфейс на React 19, Vite, TypeScript и Tailwind CSS 4.

## Возможности

- SSE-стриминг ответов FastAPI (текст появляется по мере генерации).
- Markdown и GFM-таблицы через `react-markdown`.
- Бейджи Function Calling: запись на приём и напоминания.
- Настройки `temperature`, RAG и Function Calling.
- Блок «Мои записи» с приёмами и напоминаниями.
- Адаптивная вёрстка: боковая панель превращается в drawer на мобильных.

## Локальный запуск

Нужны Node.js 20.19+ (или 22.12+) и запущенный FastAPI на
`http://127.0.0.1:8000`.

```powershell
cd frontend
npm install
npm run dev
```

Откройте `http://localhost:5173`. По умолчанию фронтенд обращается к
`http://127.0.0.1:8000`; адрес можно изменить в `frontend/.env`:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_MODEL_ID=qwen3-8b-vet
```

## Сборка и тесты

```powershell
npm run build
npm test
npm run lint
```

## Docker

Из корня проекта:

```powershell
docker compose up --build frontend
```

Фронтенд будет доступен на `http://localhost:3000`. Nginx раздаёт статику и
проксирует `/api/*` в сервис `api`, поэтому CORS и адрес `api:8000` не
попадают в браузер.

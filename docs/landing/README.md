# VetAssistant — лендинг `ai-pets.ru`

Статический лендинг для корня `ai-pets.ru`. Разворачивается отдельным
контейнером `vetassistant-landing` и проксируется Caddy на edge-хосте.
Само приложение живёт на `app.ai-pets.ru` (см. план Phase 2).

## Структура

Web-root содержит только публичную статику:

```text
landing/
├── index.html
├── privacy/index.html      # черновик, требует юридической проверки
├── terms/index.html        # черновик, требует юридической проверки
├── 404.html
├── assets/
│   ├── styles.css
│   ├── app.png             # реальный скриншот React-интерфейса
│   ├── og.png              # OG-карточка 1200×630
│   └── favicon.svg
├── robots.txt
└── sitemap.xml
```

Служебные файлы лежат вне web-root, в `docs/landing/`, и не раздаются
nginx:

```text
docs/landing/
├── nginx.conf                  # конфиг контейнера лендинга
├── compose.edge.fragment.yml   # сервис для docker-compose.edge.yml
├── Caddyfile.edge.snippet      # блоки ai-pets.ru / app.ai-pets.ru
├── DEPLOY.md                   # порядок применения и отката
└── README.md
```

Caddy-матчер `@landing_private` больше не нужен: служебных файлов в web-root
нет. Smoke-проверки всё равно ожидают 404 на `/README.md`, `/DEPLOY.md`,
`/nginx.conf`, `/compose.edge.fragment.yml` и `/Caddyfile.edge.snippet`.

## Локальный просмотр

Из папки `landing/`:

```bash
python -m http.server 8098
```

Открыть `http://127.0.0.1:8098/`. Ссылки на `https://app.ai-pets.ru/` начнут
работать после выкладки приложения на поддомен.

## Публикация

Подробный чек-лист — в [`DEPLOY.md`](DEPLOY.md). Кратко:

1. Скопировать папку `landing/` в `/srv/vetassistant/landing`.
2. Запустить `deploy/landing/apply-package-b.sh` — он поднимает отдельный
   Compose-проект `vetassistant-landing`, не редактируя tracked
   `docker-compose.edge.yml` (чтобы не ломать `git pull` в CI).
3. В Caddy направить `ai-pets.ru` на `vetassistant-landing:80`, а
   `app.ai-pets.ru` — на frontend + API; готовый скрипт делает это сам,
   сниппет — `docs/landing/Caddyfile.edge.snippet`.
4. Проверить `https://ai-pets.ru/`, `/privacy/`, `/terms/`, `/robots.txt`,
   `/sitemap.xml`, `/assets/og.png`, а также 404 на служебные пути.

DNS, Caddy и сертификаты — отдельный шаг, без него лендинг не публикуется.
Если сервис нужно добавить именно в `docker-compose.edge.yml`, используйте
`docs/landing/compose.edge.fragment.yml` и коммитьте изменение в репозиторий,
а не только на сервер.

## Nginx и кэш

`docs/landing/nginx.conf` отдаёт HTML с `Cache-Control: no-cache`, CSS/JS/шрифты
— на год с `immutable`, картинки — на 30 дней. Заголовки задаются через `map`,
чтобы не дублировать security-заголовки в каждом `location`. Конфиг
монтируется в контейнер из `docs/landing/nginx.conf` и не лежит в web-root.

## Связь с приложением

CTA «Запросить доступ» ведёт на `https://app.ai-pets.ru/?mode=request`.
AuthScreen приложения должен открывать форму заявки по параметру `mode=request`;
CTA «Открыть приложение» ведёт на `https://app.ai-pets.ru/`.

## Юридические тексты

`privacy/` и `terms/` — базовые черновики с явной пометкой
«Требуется юридическая проверка». До проверки юристом не считать их
финальными документами.

## Источники

- скриншот: `docs/assets/react-ui.png`;
- favicon: `frontend/public/favicon.svg`;
- OG-карточка: сгенерирована из макета 1200×630, лежит в `assets/og.png`.

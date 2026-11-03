# VetAssistant — лендинг `ai-pets.ru`

Статический лендинг для корня `ai-pets.ru`. Разворачивается отдельным
контейнером `vetassistant-landing` и проксируется Caddy на edge-хосте.
Само приложение живёт на `app.ai-pets.ru` (см. план Phase 2).

## Структура

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
├── sitemap.xml
├── nginx.conf
├── compose.edge.fragment.yml   # сервис для docker-compose.edge.yml
├── Caddyfile.edge.snippet      # блоки ai-pets.ru / app.ai-pets.ru
├── DEPLOY.md                   # порядок применения и отката
└── README.md
```

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
2. Добавить сервис `landing` из `compose.edge.fragment.yml` в
   `docker-compose.edge.yml` (см. план Phase 2).
3. В Caddy направить `ai-pets.ru` на `vetassistant-landing:80`, а
   `app.ai-pets.ru` — на frontend + API; готовый сниппет —
   `Caddyfile.edge.snippet`.
4. Проверить `https://ai-pets.ru/`, `/privacy/`, `/terms/`, `/robots.txt`,
   `/sitemap.xml`, `/assets/og.png`.

DNS, Caddy и сертификаты — отдельный шаг, без него лендинг не публикуется.

## Nginx и кэш

`nginx.conf` отдаёт HTML с `Cache-Control: no-cache`, CSS/JS/шрифты — на год
с `immutable`, картинки — на 30 дней. Заголовки задаются через `map`, чтобы
не дублировать security-заголовки в каждом `location`.

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

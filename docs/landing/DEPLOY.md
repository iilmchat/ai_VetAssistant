# Пакет B — порядок применения

> **Актуальный способ:** запустить `deploy/landing/apply-package-b.sh`.
> Скрипт использует отдельный Compose-проект `vetassistant-landing`, чтобы
> не редактировать tracked `docker-compose.edge.yml` на сервере: иначе
> `git pull --ff-only` в CI может упасть на dirty tree. Вариант с вставкой
> сервиса в `docker-compose.edge.yml` ниже — для случая, когда изменение
> добавляется в репозиторий, а не только на сервер.

Чек-лист для момента, когда Пакет A уже задеплоен и проверен на production.
До этого шага **ничего не применять**: файл описывает действия, а не текущее
состояние инфраструктуры.

## 0. Предусловия

- Пакет A задеплоен: в приложении нет вкладки регистрации, форма заявки
  работает, `?mode=request` открывает её.
- `https://ai-pets.ru/api/health` отвечает 200.
- Лендинг из `landing/` уже на сервере в `/srv/vetassistant/landing`.
- Скрипт лежит в `/srv/vetassistant/deploy/landing/apply-package-b.sh`.
- Служебные файлы лежат вне web-root: `docs/landing/nginx.conf`,
  `docs/landing/Caddyfile.edge.snippet`.
- DNS-запись `app.ai-pets.ru` добавлена; скрипт подождёт её распространения.
- Backup Caddyfile скрипт делает сам.

## 1. Запустить скрипт

```bash
chmod +x /srv/vetassistant/deploy/landing/apply-package-b.sh
bash /srv/vetassistant/deploy/landing/apply-package-b.sh
```

Скрипт:

- проверяет DNS `app.ai-pets.ru`;
- создаёт отдельный Compose-проект `docker-compose.landing.yml` и поднимает
  `vetassistant-landing`;
- **не редактирует** tracked `docker-compose.edge.yml`;
- сначала добавляет только `app.ai-pets.ru`, проверяет приложение и API;
- затем переключает `ai-pets.ru` на лендинг;
- проверяет, что служебные файлы (`README.md`, `DEPLOY.md`, `nginx.conf`,
  `compose.edge.fragment.yml`, `Caddyfile.edge.snippet`) отсутствуют в
  web-root и отдают 404.

Если нужно добавить сервис именно в `docker-compose.edge.yml` (например, для
commit в репозиторий), используйте `docs/landing/compose.edge.fragment.yml`.
На сервере вручную этого не делать: файл tracked, CI делает `git pull --ff-only`.

## 2. DNS и сертификат для app.ai-pets.ru

В панели reg.ru добавить:

```text
app.ai-pets.ru  A  62.109.1.230  TTL 300
```

Проверить с внешней сети:

```bash
dig +short app.ai-pets.ru
```

Дождаться, пока запись начнёт отдавать `62.109.1.230`. Caddy выпустит
сертификат автоматически при первом запросе после reload.

Важно: на `ai-pets.ru` уже стоит HSTS с `includeSubDomains`. Не анонсировать
`app.ai-pets.ru`, пока TLS не проверен.

## 3. Переключить Caddy

Сниппет: `docs/landing/Caddyfile.edge.snippet`.

Порядок:

```bash
cd /srv/ai-infra
cp Caddyfile Caddyfile.bak-$(date +%Y%m%d-%H%M%S)

# заменить старый блок ai-pets.ru на новый и добавить app.ai-pets.ru
# (вставить содержимое docs/landing/Caddyfile.edge.snippet)

docker exec edge-caddy caddy validate --config /etc/caddy/Caddyfile
docker exec edge-caddy caddy reload --config /etc/caddy/Caddyfile
```

Если `validate` не проходит — не делать reload, вернуть backup.

## 4. Smoke-проверки

```bash
# лендинг
curl -sI https://ai-pets.ru/ | head -n 1
curl -sI https://ai-pets.ru/ | grep -i '^cache-control'
curl -sI https://ai-pets.ru/assets/styles.css | grep -i '^cache-control'

# приложение
curl -sI https://app.ai-pets.ru/ | head -n 1
curl -sI https://app.ai-pets.ru/ | grep -i '^x-robots-tag'
curl -s https://app.ai-pets.ru/api/health

# редирект www
curl -sI https://www.ai-pets.ru/ | head -n 1

# юридические страницы и SEO
curl -sI https://ai-pets.ru/privacy/ | head -n 1
curl -sI https://ai-pets.ru/terms/ | head -n 1
curl -s https://ai-pets.ru/robots.txt
curl -s https://ai-pets.ru/sitemap.xml | head
```

Ожидаем:

- `ai-pets.ru` — 200, `Cache-Control: no-cache`, security-заголовки;
- `assets/styles.css` — `public, max-age=31536000, immutable`;
- `assets/app.png` и `assets/og.png` — `public, max-age=2592000`;
- `app.ai-pets.ru` — 200 и `X-Robots-Tag: noindex, nofollow`;
- `/api/health` — 200;
- `www` — 301 на apex;
- `/privacy/`, `/terms/`, `/robots.txt`, `/sitemap.xml` — 200.

Дополнительно открыть лендинг и приложение на телефоне, проверить CTA
«Открыть приложение» и «Запросить доступ».

## 5. Откат

Если что-то пошло не так:

```bash
cd /srv/ai-infra
cp Caddyfile.bak-YYYYMMDD-HHMMSS Caddyfile
docker exec edge-caddy caddy validate --config /etc/caddy/Caddyfile
docker exec edge-caddy caddy reload --config /etc/caddy/Caddyfile
```

После отката `ai-pets.ru` снова проксируется на `vetassistant-frontend:80`.
Контейнер `vetassistant-landing` и DNS-запись `app` можно оставить — они
не мешают. Если проблема в сертификате `app`, не переключать корень,
пока TLS не будет готов.

## 6. Замечания

- При переезде приложения с `ai-pets.ru` на `app.ai-pets.ru` меняется origin:
  сохранённая сессия и история в `localStorage` не переносятся, пользователям
  нужно войти заново. Это ожидаемо, но стоит предупредить активных пользователей.
- Кэш картинок — 30 дней. Если меняется `assets/app.png` или `assets/og.png`,
  обновить имя файла или добавить `?v=N` в ссылки, иначе соцсети и браузеры
  могут показывать старую версию.
- `nginx.conf` использует `map` для `Cache-Control`; при правках не добавлять
  `add_header` внутри `location`, иначе security-заголовки перестанут
  наследоваться. Конфиг лежит в `docs/landing/nginx.conf` и монтируется в
  контейнер; в web-root его быть не должно.
- В `landing/` допустима только публичная статика (`index.html`, `404.html`,
  `assets/`, `privacy/`, `terms/`, `robots.txt`, `sitemap.xml`). Служебные
  файлы — в `docs/landing/`.
- Caddy-сниппет использует имена `vetassistant-*` из внешней сети `edge`.
  Для standalone-варианта `deploy/Caddyfile` имена другие (`api`, `frontend`,
  `landing`) — не перепутать.

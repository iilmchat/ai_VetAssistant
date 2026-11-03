# DNS для `app.ai-pets.ru`

Добавить в панели reg.ru (домен `ai-pets.ru`, NS `ns1/ns2.hosting.reg.ru`):

| Поле | Значение |
|---|---|
| Host / Subdomain | `app` |
| Type | `A` |
| Value / IP | `62.109.1.230` |
| TTL | `300` |
| Priority | не заполнять |
| Weight | не заполнять |

Если панель требует полное имя, Host = `app.ai-pets.ru`.

Не трогать существующие записи `@`, `www`, MX, SPF, DKIM, DMARC.
`www.ai-pets.ru` уже указывает на `62.109.1.230` и редиректит на apex.

Проверка с внешней сети:

```bash
dig +short app.ai-pets.ru A
nslookup app.ai-pets.ru
```

Ожидается `62.109.1.230`. TTL 300 — до 5 минут на распространение.

Важно: на `ai-pets.ru` уже стоит HSTS с `includeSubDomains`. Не анонсировать
`app.ai-pets.ru`, пока TLS-сертификат не выпущен и не проверен.

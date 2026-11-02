# Защита ветки `main` (T-029)

## Текущий статус

На 2026-11-03 репозиторий `iilmchat/ai_VetAssistant` является **private**
на тарифе GitHub Free. GitHub API возвращает для branch protection и
repository rulesets:

```text
403 Upgrade to GitHub Pro or make this repository public to enable this feature.
```

Поэтому программно включить защиту ветки сейчас нельзя. Нужен **GitHub Pro**
(или Team/Enterprise), либо публичный репозиторий.

## Ручная настройка после апгрейда

1. Откройте **Settings → Branches → Add branch protection rule**
   (для rulesets: **Settings → Rules → New branch ruleset**).
2. Branch name pattern: `main`.
3. Включите **Require a pull request before merging**.
   - Для соло-разработки достаточно **Required approvals: 0**.
   - Если есть второй Maintainer — поставьте 1 approval.
4. Включите **Require status checks to pass before merging** и выберите:
   - `Lint & Test`
   - `Docker Build`
5. Рекомендуется включить **Require branches to be up to date before merging**.
6. Включите **Do not allow bypassing the above settings** — это запрещает
   прямые push в `main` даже администраторам.
7. Отключите force pushes и удаление ветки.
8. Сохраните правило.

После этого изменения в `main` проходят только через Pull Request, а merge
блокируется, пока оба CI-job’а не станут зелёными.

## Вариант через `gh api`

После апгрейда тарифа:

```powershell
@'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["Lint & Test", "Docker Build"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 0
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
'@ | gh api -X PUT repos/iilmchat/ai_VetAssistant/branches/main/protection --input -
```

Проверка:

```powershell
gh api repos/iilmchat/ai_VetAssistant/branches/main/protection
```

## Почему это важно

- Прямые push в `main` обходят ревью и обязательные проверки.
- Required status checks гарантируют, что в `main` попадает только код,
  прошедший `ruff`, `mypy`, `pytest` и Docker-сборку.
- `enforce_admins: true` закрывает лазейку с bypass для администраторов.

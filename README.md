# Мамин Помощник (Mama)

Telegram- и MAX-бот для родителей с общим Mini App: трекеры, дневник,
ассистент по вопросам беременности и раннего родительства, персональный
разбор и добровольная поддержка проекта.

## Статус

NGI Autonomous Development Standard v1 migration: **PASS**. GitHub main
(`demo23rus/Mama`, branch `main`) — единственный source of truth. Подробный
статус: [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md).

**Spec Kit pilot:** для больших функций, сложных багов и оценки спорных идей установлен GitHub Spec Kit; мелкие задачи по-прежнему идут обычным JOB. Владелец пишет обычным языком, режим выбирается автоматически. Runtime/production установкой не менялись. См. [docs/SPECKIT_PROJECT_USAGE_2026-10-06.md](docs/SPECKIT_PROJECT_USAGE_2026-10-06.md).

**Известный security risk (ACCEPTED/DEFERRED):** в текущем tracked-источнике
есть захардкоженные credential-литералы (MAX_TOKEN, YooKassa) в публичном
репозитории. Значения нигде не публикуются; owner явно решил отложить
ротацию и перевод на env-переменные (см. [.ngi/decisions.md](.ngi/decisions.md)
D009) — это не активный блокер. Подробности: [docs/SECURITY.md](docs/SECURITY.md).

## Структура репозитория

- `mama_bot.py` — продакшен backend Telegram-бота.
- `mama_max_bot.py` — продакшен backend MAX-бота; также обслуживает общий
  Mini App backend (Telegram + MAX auth/platform routing).
- `miniapp_frontend/` — зеркало продакшен-источника Mini App
  (`/var/www/mama-miniapp`).
- `ops/deploy_mama.sh` — контролируемый deploy script.
- `.ngi/` — NGI v1 правила, решения, профиль проекта, worker chain.
- `docs/` — текущая документация (архитектура, продуктовая карта, модель
  данных, безопасность, статус).
- `ROADMAP.md` — текущий roadmap (ACTIVE/NEXT/DONE/DEFERRED/PROCESS).

## Документация

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — платформа и инфраструктура.
- [docs/PRODUCT_MAP.md](docs/PRODUCT_MAP.md) — продуктовая карта Mini App.
- [docs/DATA_MODEL.md](docs/DATA_MODEL.md) — базы данных и таблицы.
- [docs/SECURITY.md](docs/SECURITY.md) — security posture и блокеры.
- [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) — текущий статус проекта.
- [docs/SPECKIT_PROJECT_USAGE_2026-10-06.md](docs/SPECKIT_PROJECT_USAGE_2026-10-06.md) — pilot-процесс Spec Kit и automatic routing.
- [ROADMAP.md](ROADMAP.md) — roadmap.
- [.ngi/decisions.md](.ngi/decisions.md) — зафиксированные решения, которые
  future workers не должны переисследовать.

## Правила работы

Любое изменение продукта или инфраструктуры проходит через coordinator
narrow technical preflight и NGI worker chain (Claude Code implementation →
Codex independent review/repair). Прямое редактирование production файлов
(`/root/mama_bot.py`, `/root/mama_max_bot.py`, `/var/www/mama-miniapp`)
запрещено — только controlled deploy. Подробно: [.ngi/rules.md](.ngi/rules.md).

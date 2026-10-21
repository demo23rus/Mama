# ARCHITECTURE — Мамин Помощник

## Платформы

- **Telegram бот** — `mama_bot.py`, продакшен-сервис `mambot.service`.
- **MAX бот** — `mama_max_bot.py`, продакшен-сервис `mama-max.service`.
  Поддерживает Telegram + MAX auth/platform routing и обслуживает общий
  Mini App backend (`/api/miniapp/*`).
- Общий Mini App использует один backend (`mama_max_bot.py`) для обеих
  платформ, но раздельные базы данных (см. [DATA_MODEL.md](DATA_MODEL.md)).

## Mini App

- Frontend webroot в продакшене: `/var/www/mama-miniapp`.
- Зеркало в репозитории: `miniapp_frontend/` (assets + `index.html`).
- Корневые экраны: Home, Assistant, Trackers, History, Profile.
- Текущий frontend содержит 93 `render*`-функции экранов/состояний.
- Backend Mini App экспонирует 59 маршрутов `/api/miniapp/...`
  (полный список областей — [PRODUCT_MAP.md](PRODUCT_MAP.md)).

## Текущий coding route

Приоритет имеет верхний раздел `AGENTS.md` от 2026-10-19:

`ChatGPT coordinator → Desktop Commander → iMac-Dimka.local → Aider 0.86.2 + local Qwen2.5-Coder 7B → focused tests/Playwright → independent coordinator review → GitHub → controlled deploy`.

- `origin/main` — стартовая точка каждого isolated worktree.
- Платный API/cloud fallback автоматически не включается.
- Если iMac/DC/GitHub/local model недоступны — работа BLOCKED, без скрытой замены исполнителя.
- Старые Router/Hermes/GPU/Claude/Codex/Kimi записи сохранены как историческая конфигурация и не имеют приоритета над актуальным `AGENTS.md`.
- Narrow scope, protected areas и controlled deploy остаются обязательными.

## Deploy / Services

- Контролируемый deploy: `ops/deploy_mama.sh`.
- Deploy restart-ит только тот backend-сервис, чей tracked source
  изменился (`mambot.service` и/или `mama-max.service`); статический
  деплой frontend не требует restart.
- `mama-watchdog.service` / `mama-watchdog.timer` защищены и не
  затрагиваются controlled deploy.
- Источник истины — GitHub `demo23rus/Mama`, branch `main`; production
  copies не переопределяют main.

## Health checks

- `http://127.0.0.1:8082/health` — backend health.
- `http://127.0.0.1:8082/api/miniapp/health` — Mini App health.
- Публичный smoke: `https://maminpomoshnik.ru/app/` — ожидается HTTP 200.

## Защищённые области

Scheduler, watchdog, fail-safe, канал/автопостинг, подписки, платежи
(YooKassa) — изменяются только по отдельному explicit owner-разрешению, не
по общему "да" на инфраструктурный JOB.

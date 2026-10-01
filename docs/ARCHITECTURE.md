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
- Текущий frontend содержит 80 `render*`-функций экранов/состояний.
- Backend Mini App экспонирует 50+ маршрутов `/api/miniapp/...`
  (полный список областей — [PRODUCT_MAP.md](PRODUCT_MAP.md)).

## Router / NGI v1

- Существующий adapter `/usr/local/bin/bot-flow` переиспользован как NGI
  Router; второй Router не создавался.
- Project profile: `/root/bot_flow_profiles/mama.profile`.
- Режим контекста: `coordinator_narrow_preflight`
  (`broad_repository_scan_by_default=false`).
- Worker chain: Claude Code (implementation) → Codex (independent
  review/repair). Kimi Code установлен, но не входит в automatic chain
  (см. [.ngi/decisions.md](../.ngi/decisions.md) D003).

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

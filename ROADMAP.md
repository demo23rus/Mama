# ROADMAP — Мамин Помощник

Канонический roadmap после NGI v1 cutover.

## ACTIVE

- Поддержание документации и текущего состояния проекта в соответствии с
  реальным кодом и production (docs-only maintenance после этого
  documentation JOB). Новые продуктовые фичи сюда не добавляются без
  отдельного owner-approved JOB.

## NEXT

- Нет активных NEXT-пунктов по security: ротация credentials и перевод на
  env-based конфигурацию отложены owner decision (см. DEFERRED).

## DONE-CLOSED

- Telegram/MAX бот + shared Mini App production baseline реконциллированы
  в GitHub (`demo23rus/Mama`, branch `main`).
- NGI Autonomous Development Standard v1 migration (Router reuse, narrow
  technical preflight, worker chain, controlled deploy, health/parity
  checks) — PASS.
- Общий Mini App backend (Telegram + MAX) с раздельными DB namespaces,
  трекеры, ассистент, дневник, персональный разбор и добровольная
  поддержка — текущий принятый функциональный baseline.
- Экономичный Router context с coordinator narrow technical preflight.
- Spec Kit pilot process установлен в control repo: Feature / Bug / Assessment workflows, automatic mode routing; runtime/production не менялись.

## DEFERRED

- Расширение автоматической worker chain (например, включение Kimi Code)
  — отложено до отдельного owner-approved решения об изменении chain (см.
  [.ngi/decisions.md](.ngi/decisions.md) D003).
- Security risk — ACCEPTED/DEFERRED by owner: публичный репозиторий
  содержит захардкоженные credential-литералы (MAX_TOKEN, YooKassa) в
  tracked source. Owner явно решил отложить ротацию credentials и не
  деплоить уже подготовленный env-based code patch (см.
  [.ngi/decisions.md](.ngi/decisions.md) D009). Это не активный блокер;
  security posture остаётся задокументирован как ACCEPTED/DEFERRED до
  отдельного будущего owner-approved security JOB. Подробности:
  [docs/SECURITY.md](docs/SECURITY.md).

## PROCESS

Авто-выбор режима по запросу владельца:
- маленькая и понятная правка → обычный JOB;
- большая функция/архитектурное изменение → SpecKit Feature;
- сложный баг с неизвестной причиной → SpecKit Bug;
- спорная идея «делать или нет» → SpecKit Assessment.

Spec Kit — pilot planning/decision layer; он не заменяет Router и не применяется к мелким задачам. Подробно: `docs/SPECKIT_PROJECT_USAGE_2026-10-06.md`.

Каждый implementation JOB после планирования: coordinator preflight → Worker Router →
focused tests → independent review → fast-forward promotion → controlled
deploy/health → PASS/BLOCKED.

Исторические BotFlow reports и backup-файлы не являются roadmap.

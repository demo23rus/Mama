# ROADMAP — Мамин Помощник

Канонический roadmap после NGI v1 cutover.

## ACTIVE

- Поддержание документации и текущего состояния проекта в соответствии с
  реальным кодом и production (docs-only maintenance после этого
  documentation JOB). Новые продуктовые фичи сюда не добавляются без
  отдельного owner-approved JOB.

## NEXT

- Security remediation JOB (см. BLOCKED-P0): ротация credentials, перевод
  MAX_TOKEN и YooKassa на env-based конфигурацию.
- После закрытия security-блокера — обновление docs/SECURITY.md и
  docs/PROJECT_STATUS.md отдельным JOB, подтверждающим чистый security
  posture.

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

## BLOCKED-P0

- Публичный репозиторий содержит захардкоженные credential-литералы
  (MAX_TOKEN, YooKassa) в tracked source. Требуется owner-approved
  security JOB: ротация credentials + перевод на env-based конфигурацию,
  до этого security posture не считается полностью чистым. Подробности:
  [docs/SECURITY.md](docs/SECURITY.md).

## DEFERRED

- Расширение автоматической worker chain (например, включение Kimi Code)
  — отложено до отдельного owner-approved решения об изменении chain (см.
  [.ngi/decisions.md](.ngi/decisions.md) D003).

## PROCESS

Каждый новый implementation JOB: coordinator preflight → Worker Router →
focused tests → independent review → fast-forward promotion → controlled
deploy/health → PASS/BLOCKED.

Исторические BotFlow reports и backup-файлы не являются roadmap.

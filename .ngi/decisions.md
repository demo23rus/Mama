# .ngi/decisions.md — Мамин Помощник

## D001 — Reuse existing Router adapter
Дата: 2026-10-01

Второй Router не создаётся. Канонический adapter — существующий /usr/local/bin/bot-flow с project profile mama.

## D002 — Narrow technical preflight is default
Дата: 2026-10-01

Перед implementation JOB Coordinator формирует exact files, symbols/functions, accepted contracts, focused tests и explicit do-not-research list. Worker стартует с этого маршрута и не делает broad repo scan.

## D003 — Preserve current worker chain
Дата: 2026-10-01

Текущая chain сохраняется: Claude Code implementation → Codex independent review/repair. Kimi Code не добавляется автоматически этой инфраструктурной миграцией. Если Kimi будет включён позже, narrow preflight обязателен.

## D004 — Economical mode
Дата: 2026-10-01

Не тратить worker context на повторное изучение проекта, backups, historical reports, unrelated frontend/modules или весь roadmap. Full-suite tests не default. Auto-purchase credits запрещён.

## D005 — GitHub main becomes source of truth after reconciliation
Дата: 2026-10-01

Существующий repo demo23rus/Mama переиспользуется. Accepted production backend и Mini App source синхронизируются в этот же repo без изменения product semantics. После hash/parity proof и fast-forward promotion main становится единственным source of truth.

## D006 — Product invariants for infrastructure JOBs
Дата: 2026-10-01

Infrastructure Router/preflight JOB не меняет product behavior, payments/subscriptions, personal-review logic, scheduler/watchdog/channel flows, DB schemas или production data. Direct routine production editing запрещено.

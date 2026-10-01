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

## D007 — Mama NGI v1 migration complete
Дата: 2026-10-01

Полный NGI v1 cutover завершён: demo23rus/Mama main — source of truth; accepted production backend + Mini App source reconciled; existing /usr/local/bin/bot-flow reused as Router adapter; Mama defaults to coordinator_narrow_preflight; current Claude Code → Codex chain preserved; shared focused preflight tests PASS; real isolated-worktree JOB_20261001_142538 passed Claude implementation + Codex REVIEW_PASS with --preflight-file and branch packaging; promotion is fast-forward only; controlled source-parity/deploy/health smoke passed without product behavior changes.

## D008 — Stable product/ops invariants (documentation consolidation)
Дата: 2026-10-01

Следующие инварианты приняты и не должны переисследоваться future workers:
- Mini App общий для Telegram и MAX: один backend (mama_max_bot.py) с auth/platform routing на обе платформы.
- Telegram и MAX используют раздельные DB namespaces (/root/mama.db и /root/mama_max.db); схемы не объединяются.
- GitHub demo23rus/Mama, branch main — единственный source of truth; production copies не переопределяют main.
- Core product experience (трекеры, дневник, ассистент и т.д.) бесплатный; добровольная поддержка и платный personal-review — отдельные необязательные flows, не блокирующие основной продукт.
- Hardcoded secrets/credentials в коде запрещены; все токены и ключи должны быть env-based. Текущие MAX_TOKEN/YooKassa литералы в tracked source — признанный P0 security blocker до отдельного owner-approved security JOB (ротация + перевод на env).
- Routine production edits (/root/mama_bot.py, /root/mama_max_bot.py, /var/www/mama-miniapp) запрещены; изменения только через controlled JOB flow и ops/deploy_mama.sh.

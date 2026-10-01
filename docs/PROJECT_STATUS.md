# PROJECT_STATUS — Мамин Помощник NGI v1

## STATUS
**MIGRATION IN PROGRESS — source reconciliation and Router proof required before final PASS.**

## SOURCE OF TRUTH TARGET
- Existing repository reused: demo23rus/Mama.
- Default branch: main.
- Production backend: /root/mama_bot.py, /root/mama_max_bot.py.
- Mini App webroot: /var/www/mama-miniapp.
- Routine direct production editing will be forbidden after cutover.

## ROUTER / PREFLIGHT
- Existing Router adapter reused: /usr/local/bin/bot-flow.
- No duplicate Router is allowed.
- Target mode: coordinator_narrow_preflight.
- CLI already supports --preflight and --preflight-file.
- Preflight must be stored in JOB metadata and preflight.txt when supplied.
- Worker prompt must ban broad repo scan, repo-wide recursive grep/find, whole-roadmap reading, backups/historical reports and unrelated modules.
- No-preflight mode must still stay narrow.

## WORKER CHAIN
Preserved: Claude Code implementation → Codex independent review/repair. Kimi Code remains optional/not automatic in this migration.

## PROTECTED
Payments/YooKassa, subscriptions, scheduler/watchdog/fail-safe, channel/autoposting, DB schemas/data and real client-message campaigns are outside infrastructure migration scope.

## ACCEPTANCE FOR MIGRATION PASS
- GitHub main reconciled to accepted production backend + Mini App source.
- .ngi/, AGENTS, ROADMAP and controlled deploy flow present with no duplicate equivalent.
- Mama profile opts into narrow technical preflight + NGI git workflow.
- Shared focused Router preflight tests PASS.
- Real isolated-worktree docs-only Router proof PASS with --preflight-file.
- Exact diff contains only source reconciliation + Router/config/docs/deploy infrastructure; no product behavior edits.
- Fast-forward promotion to main.
- Controlled deploy check/source parity PASS and health/public smoke PASS.

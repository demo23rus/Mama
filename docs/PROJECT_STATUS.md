# PROJECT_STATUS — Мамин Помощник NGI v1

## STATUS
**PASS — NGI Autonomous Development Standard v1 migration complete.**

GitHub main is reconciled to the accepted production backend + Mini App source. Existing BotFlow is reused as the Router adapter; narrow technical preflight is enabled and verified.

## SOURCE OF TRUTH — PASS
- Canonical repo: demo23rus/Mama, branch main.
- Accepted production mama_bot.py and mama_max_bot.py were reconciled byte-for-byte into GitHub.
- Accepted /var/www/mama-miniapp source/assets were reconciled into miniapp_frontend/ excluding backup files.
- Routine direct production editing is forbidden; new JOBs start from origin/main.

## ROUTER / PREFLIGHT — PASS
- Existing Router adapter reused: /usr/local/bin/bot-flow; no duplicate Router created.
- Mama profile uses TECHNICAL_PREFLIGHT_MODE=coordinator_narrow_preflight and NGI_GIT_WORKFLOW=true.
- CLI supports --preflight and --preflight-file.
- JOB metadata stores preflight; preflight.txt is created when supplied.
- Worker prompt bans broad repo scan, repo-wide recursive grep/find, whole-roadmap reading, backups/historical reports and unrelated modules.
- No-preflight mode still stays narrow.
- Shared focused Router tests: PREFLIGHT_FOCUSED_TESTS=PASS.
- Real proof JOB_20261001_142538: docs-only, --preflight-file, Claude IMPLEMENTATION_COMPLETE, Codex REVIEW_PASS, worker commit 7e31131.

## WORKER CHAIN
Preserved exactly for this migration:
1. Claude Code — implementation.
2. Codex — independent review / repair.
3. Kimi Code is installed but remains optional/not automatic; if enabled later, the same narrow-preflight rules are mandatory.

## CONTROLLED DEPLOY / HEALTH
- Controlled script: ops/deploy_mama.sh.
- Source parity check against production: PASS.
- Deploy flow restarts only the backend service whose tracked source changed; frontend static deploy requires no service restart.
- mama-watchdog.service/timer remain protected and untouched.
- Confirmed health: 127.0.0.1:8082/health = OK; /api/miniapp/health = OK; public https://maminpomoshnik.ru/app/ = HTTP 200.

## CHANGED INFRASTRUCTURE
- .ngi/project.yaml, rules.md, decisions.md, workers.yaml
- AGENTS.md, ROADMAP.md, docs/PROJECT_STATUS.md
- ops/deploy_mama.sh
- /root/bot_flow_profiles/mama.profile
- Shared Router/tests were reused because they already implement the required preflight contract; no duplicate Router/test harness was created.

## PROTECTED
Payments/YooKassa, subscriptions, scheduler/watchdog/fail-safe, channel/autoposting, DB schemas/data and real client-message campaigns were not changed.

## MIGRATION RESULT
GitHub main source of truth: PASS. Existing Router reused: PASS. Narrow technical preflight: PASS. Current worker chain preserved: PASS. Focused Router tests: PASS. Real isolated-worktree proof: PASS. Fast-forward promotion: PASS. Source parity/health/public smoke: PASS. Owner result: PASS.

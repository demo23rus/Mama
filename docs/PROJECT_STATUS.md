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

## PRODUCT STATE
- Shared Telegram + MAX Mini App backend in mama_max_bot.py handles auth/platform routing for both platforms; mama_bot.py is the Telegram bot backend.
- Mini App root screens: Home, Assistant, Trackers, History, Profile; frontend currently has 80 render* functions.
- Backend exposes 50+ /api/miniapp routes covering profile/home/today, referral, feedback, pregnancy, ask-question, personal-review, support, tantrums/emotions, psycho, reset-me, kindergarten, firstdays, breastfeeding, recovery, benefits, child, sleep, feeding, complementary-foods (complementary_food_log), symptoms, diary, growth, vaccines, emergency, photo analysis.
- Core product experience is free; voluntary support and paid personal-review are separate, non-blocking flows.
- Details: docs/PRODUCT_MAP.md.

## PLATFORM / ARCHITECTURE
- Router adapter and deploy flow unchanged from ROUTER/PREFLIGHT and CONTROLLED DEPLOY sections above.
- systemd services: mambot.service (Telegram), mama-max.service (MAX + shared Mini App backend); mama-watchdog.service/timer protected.
- Details: docs/ARCHITECTURE.md.

## DATA
- Telegram and MAX use separate production SQLite DB files: /root/mama.db (29 tables) and /root/mama_max.db (33 tables, superset of Telegram schema groups plus channel_poll_votes, command_locks, limits, max_user_chats, reviews).
- Only table names are documented, never row/user data.
- Details: docs/DATA_MODEL.md.

## SECURITY
- Repository visibility is public (demo23rus/Mama).
- Tracked source currently contains hard-coded credential literals for MAX_TOKEN and YooKassa credentials — values are never printed or copied anywhere, including here.
- OPENAI and Telegram BOT token paths are already env-based.
- ACCEPTED/DEFERRED RISK: owner explicitly decided to defer credential rotation and not deploy the pending env-based code patch (see .ngi/decisions.md D009). This is a consciously accepted risk, not an active product blocker; security posture is documented as NOT fully clean until a future owner-approved security JOB rotates credentials and moves the affected code paths to env-based configuration.
- Details: docs/SECURITY.md.

## OPERATIONS
- Deploy/health/restart policy unchanged (see CONTROLLED DEPLOY / HEALTH above).
- Protected areas: scheduler, watchdog, fail-safe, payments/YooKassa, subscriptions, channel/autoposting — require separate explicit owner approval, not covered by general docs-only approvals.

## CURRENT BLOCKERS
- None active. Public repo + hard-coded MAX_TOKEN/YooKassa credentials remain a documented ACCEPTED/DEFERRED security risk (owner decision, see .ngi/decisions.md D009), not an active blocker. See ROADMAP.md DEFERRED and docs/SECURITY.md.

## NEXT
- No active NEXT item for security: credential rotation and env-based config migration are deferred by owner decision until a future, separately owner-approved security JOB is initiated.

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

## DOCUMENTATION CONSOLIDATION (this JOB)
README.md, docs/ARCHITECTURE.md, docs/PRODUCT_MAP.md, docs/DATA_MODEL.md and docs/SECURITY.md were added; ROADMAP.md restructured into ACTIVE/NEXT/DONE-CLOSED/DEFERRED/PROCESS; this file extended with PRODUCT STATE/PLATFORM/DATA/SECURITY/OPERATIONS/CURRENT BLOCKERS/NEXT. No product code, Router, deploy script, services, DB or production files were changed.

<!-- NGI_QUIET_DEVELOPMENT_2026_10_22 -->
## NGI Quiet Development — обязательный режим для новых задач (22.10.2026)

**Приоритет над устаревшими инструкциями по исполнителям и моделям ниже.** [Единый стандарт NGI](https://github.com/demo23rus/ngi-ai-studio-controller/blob/main/docs/NGI_QUIET_DEVELOPMENT.md). Особые проектные требования безопасности, приватности, релиза и прямые решения владельца остаются обязательными.

- **Один чат — один проект; одна задача — одно изменение.** Не смешивать репозитории, не переименовывать чаты. Не запускать дополнительный аудит, перенастройку ИИ, новые интеграции или обходные работы без запроса.
- **Тихая работа:** не засорять чат рассказами о каждой команде, промежуточными логами и повторяющимися статусами. При длительной работе — только короткое существенное обновление или явный блокер; итог — «PASS/BLOCKED: изменение, проверки, commit/PR, что осталось».
- **GitHub — источник истины.** Читать только актуальные инструкции/статус и релевантный код. Изменять код в изолированной ветке/worktree; выполнять необходимые **целевые** тесты. Для авторизации, платежей, данных и безопасности сохранять усиленные проверки и независимый review, если требует проект.
- **Без самовольного production/deploy**, действий с реальными данными, оплат, рассылок, рекламы, переключения OAuth, опасных Git-команд и платных API/fallback. Просить владельца только о необходимых авторизациях, оплатах и важных необратимых решениях.
- **Не гонять модели часами.** Использовать существующий выбранный для проекта исполнитель. Qwen3 (простое) / GLM-4.7-Flash (сложное) — текущие варианты NGI Local Coder, но явный выбор владельца для отдельного проекта сохраняется. Qwen2.5-7B, Hermes, gpu_local и исторические Router-инструкции не активировать. При повторном провале — BLOCKED с причиной, не бесконечные попытки.
- **Никаких фиктивных PASS или обещаний фоновой работы.** Подробные отчёты держать в файлах/PR, обновлять существующий handoff только по необходимости.

<!-- /NGI_QUIET_DEVELOPMENT_2026_10_22 -->

## Решение владельца 2026-10-18: старый AI-контур отключён

Это решение отменяет прежние требования использовать Hermes, gpu_local, Qwen/Vast, NGI GPU bridge, durable_tasks и обязательный локальный reviewer. Не запускать старую очередь и GPU-роутеры, не создавать новую аренду и не включать платный fallback. Новый исполнитель выбирается владельцем отдельно. Код, Git-история, незавершённые изменения, правила тестирования и защиты production сохраняются.

# AGENTS.md — Мамин Помощник

Короткий вход для implementation/review workers в NGI Autonomous Development Standard v1.

Перед работой читать только:
1. .ngi/project.yaml
2. .ngi/rules.md
3. .ngi/decisions.md
4. .ngi/workers.yaml
5. docs/PROJECT_STATUS.md
6. релевантный раздел ROADMAP.md только если JOB/preflight на него ссылается.

Если координатор передал technical preflight, он является авторитетным стартовым scope для JOB.

Обязательные правила:
- one JOB = one change;
- accepted source = GitHub main;
- production вручную не редактировать;
- no broad audit/refactor;
- coding-worker начинает с exact files/symbols/contracts/tests из preflight;
- repo-wide recursive grep/find, массовый inventory, чтение всего roadmap, backups/historical reports и unrelated modules запрещены без доказанной необходимости;
- если не хватает одного контракта, открыть только непосредственно связанный файл и объяснить зачем;
- решения из .ngi/decisions.md не переисследовать;
- focused tests only;
- secrets/.env/DB/private data/backups не коммитить;
- implementation worker не deploy-ит production и не объявляет финальный product PASS.

## Spec Kit pilot routing

Spec Kit установлен как planning/decision layer, не как второй Router. Владелец пишет обычным языком; координатор сам выбирает режим:
- маленькая понятная правка → обычный JOB;
- большая функция с несколькими экранами/API/БД/ролями/платежами/крупным онбордингом → SpecKit Feature;
- сложный баг с неясной причиной → SpecKit Bug;
- спорная идея «делать или нет» → SpecKit Assessment.

Feature: specify → plan → tasks → implement → converge. Bug: assess → fix → test. Assessment: intake → research → define → shape → decide.

Spec Kit не отменяет one JOB = one change, narrow preflight, protected areas и controlled deploy. Для мелких задач Spec Kit не использовать. Подробно: `docs/SPECKIT_PROJECT_USAGE_2026-10-06.md` и `.specify/memory/constitution.md`.


## Owner GPU routing decision — 2026-10-11
Default coding execution: Hermes / ngi-gpu / qwen3.8-27b in an isolated worktree from origin/main. Complex work may use python3 /root/ngi-ai-studio-controller/gpu_worker.py --worktree <registered worktree under /root/ngi_worker_worktrees/> --prompt-file <narrow task>. No automatic Codex/Claude/Kimi calls or cloud-only legacy BotFlow. Independent coordinator review and focused tests remain required. Existing product protections, Git and controlled deploy contracts remain. This owner-authorized migration supersedes earlier execution-chain and BotFlow-default requirements only. Previous configs are retained in .ngi/*.before-gpu.yaml and Git history for rollback.

## Актуальный исполнитель для «Мамин помощник» — 2026-10-19

**Этот раздел имеет приоритет над историческими Hermes/GPU/Claude/Codex/Kimi-инструкциями ниже.** Для новых, явно заказанных владельцем технических исправлений используем только: **ChatGPT-координатор → Desktop Commander → `iMac-Dimka.local` → Aider 0.86.2 + локальная Qwen2.5-Coder 7B → точечные тесты/Playwright по необходимости → независимая проверка → GitHub**. Никаких платных API и автоматического резервного облачного исполнителя. ChatGPT как координатор при этом остаётся облачным.

- Канонический репозиторий: `demo23rus/Mama`, источник истины — `origin/main`. Одна задача = одно изменение в изолированной ветке `job/*`. Нельзя напрямую редактировать production, автопубликовать, рассылать сообщения или менять работу ботов.
- На iMac использовать проектный запуск `~/LocalAI/bin/ngi-mama-job.sh`. Перед первой задачей выполнить `~/LocalAI/bin/ngi-mama-job.sh --check`: ожидаемый результат `MAMA_LOCAL_AGENT_READY`. Для задачи: `ngi-mama-job.sh job-slug /absolute/synthetic-task.txt miniapp_frontend/scoped-file.js` (подставить реальный существующий файл, указанный в узком preflight). Он вызывает общий `ngi-local-job.sh`, при необходимости получает репозиторий, использует только локальную Qwen и не выполняет `commit`, `push`, `merge` или `deploy`.
- **Особый security gate:** этот публичный репозиторий содержит признанные владельцем и отложенные к ротации credential-литералы в `mama_bot.py` и `mama_max_bot.py` (D009). До отдельного согласованного безопасного этапа **запрещено передавать эти файлы целиком в любую модель**, цитировать токены или включать их в промпты/логи. Локальный запуск блокирует эти файлы, секретные пути, платежные и deploy-конфиги; не изменять принятый статус D009 без отдельного разрешения.
- Сохраняются проектные ограничения: не менять watchdog/scheduler/fail-safe, платежи, подписки, базы, массовые сообщения и реальные данные родителей/детей без явного scope. Не запускать общий аудит или все тесты по умолчанию. Для принятия изменений требуются точечные проверки и проверка diff; согласованное продвижение в GitHub и controlled deploy — только по действующим gates.
- Значения `.ngi/project.yaml`/`.ngi/workers.yaml` со старым Hermes/GPU Router — историческая конфигурация, **не команда его запускать**. Если iMac, DC, GitHub или локальная модель недоступны — **BLOCKED**, без скрытой замены исполнителя. Ключевой стандарт: [NGI Local Coding Standard](https://github.com/demo23rus/ngi-ai-studio-controller/blob/main/docs/LOCAL_CODING_STANDARD.md).

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

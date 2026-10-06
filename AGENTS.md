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

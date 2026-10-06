# Мамин Помощник — Project Constitution

## Core Principles

### I. GitHub main — единственный source of truth
Принятый исходный код и документация живут в `demo23rus/Mama`, branch `main`. Production-копии, backup-файлы и локальные временные изменения не переопределяют GitHub main. Любая разработка начинается от актуального `origin/main` и возвращается в main только через reviewable Git workflow.

### II. Один JOB = одна задача
Обычный implementation JOB покрывает одну понятную правку. Несвязанные изменения, широкие рефакторы и «заодно поправить» не смешиваются. Spec Kit может описывать большую функцию целиком, но реализация должна оставаться разбита на проверяемые задачи/этапы и соблюдать существующий narrow-preflight contract.

### III. Не переисследовать закрытое
Не запускать общий аудит без команды владельца. Не переоткрывать DONE-CLOSED блоки и решения из `.ngi/decisions.md` без нового воспроизводимого дефекта, новой продуктовой необходимости или прямого owner-request. Контекст читать минимально необходимый для текущей задачи.

### IV. Spec Kit используется по сложности, а не по привычке
Маленькая и ясная правка выполняется обычным JOB. Большая функция, затрагивающая несколько экранов/API/БД/ролей/платежей/крупный онбординг, ведётся через SpecKit Feature. Сложный баг с неясной причиной — через SpecKit Bug. Спорная идея, где сначала нужно решить «делать или нет», — через SpecKit Assessment.

### V. Production и секреты защищены
Spec Kit pilot сам по себе не меняет runtime и не даёт разрешения на deploy. Прямое routine-редактирование production запрещено. Секреты, `.env`, credential-файлы, базы, приватные данные и backup-артефакты не коммитятся. Protected areas проекта требуют отдельного явного owner-разрешения.

### VI. Проверка обязательна
Для больших фич: `specify → plan → tasks → implement → converge`, повторяя `implement → converge` до приемлемого результата. Для сложных багов: `bug assess → fix → test`. Для assessment: `intake → research → define → shape → decide`. Missing verification не считается PASS.

### VII. Владелец пишет обычным языком
Владелец не обязан помнить команды Spec Kit. Ассистент сам классифицирует запрос и выбирает режим. Явная команда владельца (`SpecKit фича`, `SpecKit баг`, `SpecKit оценка`) имеет приоритет, если не нарушает protected/security rules.

## Project Constraints

- Existing NGI Router (`bot-flow`) и narrow technical preflight сохраняются; Spec Kit — пилотный planning/decision layer, а не второй Router.
- Для мелких задач Spec Kit не использовать.
- Для больших задач Spec Kit artifacts должны сузить scope до конкретных файлов, контрактов и focused tests перед implementation.
- Runtime Telegram/MAX/Mini App не меняется от самого факта установки Spec Kit.
- Reports владельцу: кратко, по-русски, с итогом `PASS` или `BLOCKED` и только реально важными деталями.

## Development Workflow

| Тип запроса | Режим |
|---|---|
| Узкая правка: убрать кнопку, поправить текст, скрыть экран, обновить документ | Обычный JOB |
| Большая функция: несколько экранов, API, БД, роли, платежи, iOS, крупный онбординг | SpecKit Feature |
| Непонятно, стоит ли делать идею сейчас | SpecKit Assessment |
| Сложный баг с неясной причиной | SpecKit Bug |
| Большой анализ без решения на код | Сначала анализ или SpecKit Assessment |

Feature workflow: `$speckit-specify` → `$speckit-plan` → `$speckit-tasks` → `$speckit-implement` → `$speckit-converge`.

Bug workflow: `$speckit-bug-assess` → `$speckit-bug-fix` → `$speckit-bug-test`.

Assessment workflow: `$speckit-assess-intake` → `$speckit-assess-research` → `$speckit-assess-define` → `$speckit-assess-shape` → `$speckit-assess-decide`.

## Governance

Эта constitution определяет пилотный режим Spec Kit для проекта и дополняет, но не отменяет, `AGENTS.md`, `.ngi/rules.md`, `.ngi/decisions.md` и protected-area policy. Изменения принципов требуют owner-approved docs/process change. Если правила конфликтуют, более строгая защита production/secrets/protected areas имеет приоритет.

**Version**: 1.0.0 | **Ratified**: 2026-10-06 | **Last Amended**: 2026-10-06

# .ngi/rules.md — Мамин Помощник

## 1. One JOB = one change
Один implementation JOB покрывает одну инфраструктурную или продуктовую правку. Несвязанные изменения не смешивать.

## 2. Coordinator narrow technical preflight — default
Перед implementation JOB координатор заранее фиксирует:
- конкретные файлы;
- конкретные функции/символы;
- уже принятые контракты;
- focused tests;
- что запрещено повторно исследовать.

Предпочтительный запуск: bot-flow task --project mama --preflight-file <path> "<task>".

## 3. Worker context budget
Coding-worker начинает только с files/symbols/contracts из preflight. Запрещены по умолчанию broad repo audit, repo-wide recursive grep/find, перечисление сотен файлов/tests, чтение всего roadmap, backups/historical reports, unrelated modules/frontend и повторное исследование решений из .ngi/decisions.md.

Если не хватает одного контракта, разрешено открыть только непосредственно связанный файл и кратко объяснить зачем. Если preflight не передан, worker всё равно остаётся в минимальном scope текущего JOB.

## 4. Existing worker chain is preserved
Текущий Mama flow сохраняется: Claude Code — implementation; Codex — independent review/repair; Kimi Code установлен, но этой миграцией не добавляется в automatic chain.

Любой будущий coding-worker, особенно Kimi Code, обязан соблюдать тот же narrow-preflight contract.

## 5. No broad audit/refactor
Общий аудит, архитектурный рефакторинг, repo-wide scan и full test suite не запускаются без отдельной доказанной необходимости.

## 6. No duplicate Router
Существующий /usr/local/bin/bot-flow + profile mama используется как Router adapter. Второй параллельный Router не создавать.

## 7. Source of truth
После MIGRATION PASS accepted source — demo23rus/Mama branch main. Production/local copies не переопределяют GitHub main.

## 8. Production
Прямое routine-редактирование /root/mama_bot.py, /root/mama_max_bot.py и /var/www/mama-miniapp запрещено. Deploy только controlled flow.

## 9. Protected areas
Без отдельного owner-разрешения не менять scheduler, watchdog, fail-safe, channel/autoposting, subscriptions, payments/YooKassa, DB schemas и реальные client-message campaigns.

## 10. Verification
Только focused tests, exact diff, changed-scope check, nearest regression. Финальный owner result — PASS/BLOCKED.

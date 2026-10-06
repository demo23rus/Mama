# Spec Kit pilot — Мамин Помощник

Дата внедрения: 2026-10-06.

## Где установлен

- Control repo: `demo23rus/Mama`.
- Default branch / source of truth: `main`.
- Spec Kit infrastructure: `.specify/`.
- Codex skills: `.agents/skills/speckit-*/SKILL.md`.
- Extensions: `bug`, `assess`.
- Runtime приложения, production и deploy-конфигурация установкой не менялись.

## Зачем он нужен

Spec Kit — пилотный процесс для задач, где обычного короткого JOB недостаточно: крупные продуктовые функции, сложные баги с неясной причиной и идеи, которые сначала нужно оценить. Он не заменяет существующий NGI Router/`bot-flow`; он помогает сначала сформулировать решение и только затем передать узкий scope в привычный implementation flow.

## Автоматический выбор режима

Владелец пишет обычным языком. Ассистент сам выбирает процесс.

| Тип запроса | Режим |
|---|---|
| Узкая правка: убрать кнопку, поправить текст, скрыть экран, обновить документ | Обычный JOB |
| Большая функция: несколько экранов, API, база, роли, платежи, iOS, крупный онбординг | SpecKit Feature |
| Непонятно, стоит ли делать идею сейчас | SpecKit Assessment |
| Сложный баг с неясной причиной | SpecKit Bug |
| Большой анализ без решения на код | Сначала анализ или SpecKit Assessment |

Правило простое:
- маленькая и понятная задача → работаем как раньше;
- большая задача с архитектурным/межмодульным влиянием → SpecKit Feature;
- сначала нужно решить «делать или нет» → SpecKit Assessment;
- сложный баг, причина которого неизвестна → SpecKit Bug;
- Spec Kit не запускается ради маленьких косметических правок.

## Доступные workflows

### SpecKit Feature

Для крупных функций:

1. `$speckit-specify` — что и зачем строим;
2. `$speckit-plan` — технический план;
3. `$speckit-tasks` — проверяемые задачи;
4. `$speckit-implement` — реализация;
5. `$speckit-converge` — проверка расхождений и остатка работ.

При необходимости используются `$speckit-clarify`, `$speckit-checklist`, `$speckit-analyze`.

### SpecKit Bug

Для сложных дефектов:

1. `$speckit-bug-assess` — воспроизведение и причина;
2. `$speckit-bug-fix` — scoped repair;
3. `$speckit-bug-test` — подтверждение исходного симптома и результата.

Артефакты: `.specify/bugs/<slug>/`.

### SpecKit Assessment

Для спорных идей:

1. `$speckit-assess-intake`;
2. `$speckit-assess-research`;
3. `$speckit-assess-define`;
4. `$speckit-assess-shape`;
5. `$speckit-assess-decide`.

Финальный verdict: `go`, `needs-clarification` или `kill`. Артефакты: `.specify/assessments/<slug>/`.

## Когда НЕ использовать

Не использовать Spec Kit для просьб типа «убери кнопку», «поправь текст», «уменьши плашку», «обнови документ», если scope очевиден и архитектурного решения не требуется. Такие задачи остаются обычным JOB с narrow preflight и focused tests.

Spec Kit также не является разрешением на production deploy, работу с платежами, рассылками, watchdog/scheduler или другими protected areas. Для них по-прежнему нужно отдельное явное owner-разрешение.

## Как владелец может писать

Обычного языка достаточно:

- «Добавь подписки и оплату» → ассистент выбирает **SpecKit Feature**.
- «Проверь, стоит ли возвращать видео-анализ техники» → **SpecKit Assessment**.
- «На экране питания кнопка не работает, не понимаю почему» → **SpecKit Bug** или обычный JOB, если причина быстро и однозначно локализована.
- «Убери кнопку анализа техники» → обычный JOB.

Если владелец хочет явно указать режим:

- `SpecKit фича: добавить <что>. Цель: <зачем>. Ограничения: <что нельзя ломать>. Проверка: <как поймём, что готово>.`
- `SpecKit баг: <что сломано>. Где: <экран/устройство>. Как повторить: <шаги>. Ожидание: <как должно быть>.`
- `SpecKit оценка идеи: <идея>. Нужно решить: делать сейчас / отложить / убить.`

## Связь с текущим NGI процессом

- GitHub `main` остаётся source of truth.
- One JOB = one change остаётся обязательным правилом реализации.
- Spec Kit не создаёт второй Router и не заменяет `bot-flow`.
- Большой SpecKit plan должен в итоге давать узкие implementation tasks/preflight, а не оправдывать broad repo audit.
- Закрытые решения и DONE-CLOSED блоки не переоткрываются без нового дефекта или owner-request.
- Отчёт владельцу — краткий и на русском.

## CLI sanity-check

Установлено и проверено:

- `specify 1.1.1`;
- integration `codex` — installed/default;
- extension `bug` — enabled;
- extension `assess` — enabled.

Команды проверки:

```bash
specify check
specify integration list
specify extension list
```

# ROADMAP — Мамин Помощник

Канонический roadmap после NGI v1 cutover.

## ACTIVE

- Продолжать улучшения небольшими законченными STEP: один scope → focused tests → PR/CI → merge → production check.
- Текущий 7-step цикл от 2026-10-21 завершён. Канонический handoff: `docs/CURRENT_HANDOFF.md`.

## NEXT

- Сначала проверить live UX и агрегированное использование новых функций: «Моя неделя», «Актуально для вас», Центр уведомлений, Прикорм 6+, «Моменты малыша».
- После этого выбрать **одну** следующую доработку по реальной пользе/retention. Не запускать широкий рефакторинг.

## DONE-CLOSED

- Telegram/MAX bot + shared Mini App production baseline реконциллированы в GitHub `main`.
- NGI Autonomous Development Standard v1 migration и controlled deploy/health — PASS.
- Playwright isolated mobile coverage: Chromium + WebKit CI.
- **2026-10-21 product cycle — PASS:**
  - PR #5 — пользовательский часовой пояс;
  - PR #6 — Центр уведомлений;
  - PR #7 — реальные timezone-aware reminders;
  - PR #8 — «Моя неделя»;
  - PR #9 — Home «Актуально для вас»;
  - PR #10 — Прикорм 6+: идеи еды только из знакомых продуктов;
  - PR #11 — «Моменты малыша»;
  - PR #12 — safe schema init для `baby_moments`.
- Spec Kit pilot process установлен; runtime/production flow не заменяет.

## DEFERRED

- Расширение автоматической worker chain (например, включение Kimi Code)
  — отложено до отдельного owner-approved решения об изменении chain (см.
  [.ngi/decisions.md](.ngi/decisions.md) D003).
- Security risk — ACCEPTED/DEFERRED by owner: публичный репозиторий
  содержит захардкоженные credential-литералы (MAX_TOKEN, YooKassa) в
  tracked source. Owner явно решил отложить ротацию credentials и не
  деплоить уже подготовленный env-based code patch (см.
  [.ngi/decisions.md](.ngi/decisions.md) D009). Это не активный блокер;
  security posture остаётся задокументирован как ACCEPTED/DEFERRED до
  отдельного будущего owner-approved security JOB. Подробности:
  [docs/SECURITY.md](docs/SECURITY.md).

## PROCESS

Авто-выбор режима по запросу владельца:
- маленькая и понятная правка → обычный JOB;
- большая функция/архитектурное изменение → SpecKit Feature;
- сложный баг с неизвестной причиной → SpecKit Bug;
- спорная идея «делать или нет» → SpecKit Assessment.

Spec Kit — pilot planning/decision layer; он не заменяет Router и не применяется к мелким задачам. Подробно: `docs/SPECKIT_PROJECT_USAGE_2026-10-06.md`.

Каждый implementation JOB после планирования: coordinator preflight → Worker Router →
focused tests → independent review → fast-forward promotion → controlled
deploy/health → PASS/BLOCKED.

Исторические BotFlow reports и backup-файлы не являются roadmap.

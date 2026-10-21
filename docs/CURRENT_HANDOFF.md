# CURRENT_HANDOFF — Мамин Помощник

Дата: 2026-10-21

## Короткий статус

**PASS. Текущий продуктовый цикл завершён, GitHub main и production синхронизированы.**

Canonical repo: demo23rus/Mama
Branch: main
Последний product-code baseline перед этим docs-sync: PR #14, merge commit 82333cb
Production/source parity: **PASS**
Services: mambot.service = active, mama-max.service = active
Mini App health: /api/miniapp/health = OK
Public Mini App: https://maminpomoshnik.ru/app/ = HTTP 200
Открытых product PR: **0**

Этот handoff заменяет предыдущую версию из PR #13 и включает последующий STEP 8.

## Что завершено

### STEP 1 — Часовой пояс пользователя — PASS
PR #5.
- Профиль → «Часовой пояс».
- IANA zones, включая Europe/Moscow, Asia/Krasnoyarsk, Asia/Yekaterinburg и другие.
- Определение зоны устройством без автосохранения.
- Telegram/MAX сохраняют timezone в своих отдельных DB namespace.
- Старые пользователи получают fallback Europe/Moscow.

### STEP 2 — Центр уведомлений — PASS
PR #6.
- Профиль → «Уведомления».
- Настройки: прививка за 3 дня, прививка сегодня, рост/вес, «Моя неделя».
- Настройки хранятся отдельно для Telegram/MAX.
- Telegram сохраняет legacy default для 3-day vaccine; MAX не получает новые unsolicited defaults.

### STEP 3 — Реальные timezone-aware напоминания — PASS
PR #7.
- Реальная отправка Telegram/MAX с учётом сохранённого timezone.
- Прививки: за 3 дня / в день события.
- Рост и вес: ежемесячное напоминание.
- «Моя неделя»: еженедельное напоминание.
- Persistent delivery log защищает от дублей.
- MAX отправляет proactive message только если известен private chat_id.
- Focused test: SMART_REMINDER_FOCUSED_TESTS=PASS.

### STEP 4 — «Моя неделя» — PASS
PR #8.
- Home + экран «Сегодня» → «Моя неделя».
- 7-дневная сводка: сон, питание, самочувствие, дневник, активные дни, рост/вес, ближайшая прививка, новые продукты прикорма.
- Для беременности — срок + записи самочувствия/дневника.
- AI-вывод запускается только по кнопке.
- GitHub Chromium + WebKit CI: SUCCESS.

### STEP 5 — «Актуально для вас» — PASS
PR #9.
- На Home добавлен один динамический персональный блок вместо новых постоянных иконок.
- Приоритеты: беременность → близкая прививка → прикорм 6+.
- Использует уже загруженный /today, без отдельного лишнего API-запроса.
- Клик ведёт в релевантный рабочий раздел.
- GitHub Chromium + WebKit CI: SUCCESS.

### STEP 6 — Прикорм 6+: «Что приготовить сегодня?» — PASS
PR #10.
- Идеи еды формируются только из уже знакомых продуктов.
- Используются отметки «Пробовали» / «Понравилось».
- «Реакция» и «Не понравилось» исключаются.
- До 3 простых сочетаний, возрастная подсказка по текстуре и safety note.
- Без AI и без медицинских назначений.
- GitHub Chromium + WebKit CI: SUCCESS.

### STEP 7 — «Моменты малыша» — PASS
PR #11 + safe schema init PR #12.
- Дневник малыша → «Моменты малыша».
- Типы: первый зуб, первое слово, сел, первые шаги, первый день в садике, день рождения, другое.
- Дата + короткая заметка + хронология.
- Future date запрещена с учётом timezone пользователя.
- Telegram/MAX используют раздельные DB namespace.
- baby_moments создаётся безопасно при startup/lazy schema init.
- Focused test: MOMENTS_FOCUSED_TESTS=PASS.
- GitHub Chromium + WebKit CI: SUCCESS.

### STEP 8 — безопасная аналитика новых функций — PASS
PR #14.
- Добавлен allowlisted факт открытия только новых продуктовых функций: week, relevant, notifications, cf_ideas, moments.
- Событие backend: ui_feature_opened.
- Не отправляются пользовательские тексты, содержимое дневника, медицинские данные или детали профиля.
- Используется существующая analytics_events; новая analytics-таблица не создавалась.
- Backend focused test: UI_ANALYTICS_FOCUSED_TESTS=PASS.
- GitHub Chromium + WebKit CI: SUCCESS.

## GitHub / production на момент handoff

Merged:
- #5 — часовой пояс
- #6 — центр уведомлений
- #7 — умные напоминания
- #8 — «Моя неделя»
- #9 — «Актуально для вас»
- #10 — идеи из знакомых продуктов
- #11 — «Моменты малыша»
- #12 — safe schema init моментов
- #13 — предыдущий docs handoff
- #14 — безопасная UX-аналитика

Live checks после PR #14:
- ops/deploy_mama.sh check → SOURCE_PARITY=PASS
- mambot.service → active
- mama-max.service → active
- /api/miniapp/health → {"status":"ok"}
- public /app/ → HTTP 200
- production содержит /api/miniapp/analytics/ui

## Актуальная структура данных

Production:
- /root/mama.db — 32 пользовательские таблицы.
- /root/mama_max.db — 36 пользовательских таблиц.
- Новые группы текущего цикла: notification_settings, notification_delivery_log, baby_moments.
- analytics_events переиспользуется для безопасной UX-аналитики.

Не читать/не переносить в документацию реальные строки пользователей; для product decisions использовать только агрегаты.

## Что НЕ надо переделывать

- Не добавлять новые постоянные иконки на Home без отдельной необходимости.
- Не возвращать жёсткую привязку пользовательского времени к Москве.
- Не смешивать Telegram/MAX пользовательские данные.
- Не менять payments/YooKassa/subscriptions/watchdog/fail-safe/channel scheduler без отдельного explicit scope.
- «Мамин психолог» — AI support, не emergency/medical care.
- «Личный разбор ситуации» не называть консультацией психолога.
- Прикорм/здоровье — без диагнозов и жёстких медицинских назначений.
- UX analytics — только allowlisted feature-open events; не логировать пользовательский текст/medical content.

## Текущий исполнитель

Приоритет имеет верхний раздел AGENTS.md от 2026-10-19:
ChatGPT-координатор → Desktop Commander → iMac-Dimka.local → Aider 0.86.2 + локальная Qwen2.5-Coder 7B → focused tests/Playwright → independent coordinator review → GitHub → controlled deploy.

Старые Hermes/GPU/Claude/Codex/Kimi automatic-chain записи ниже по истории не являются командой их запускать. Если iMac/DC/GitHub/local model недоступны — BLOCKED, без скрытого cloud fallback.

## NEXT для нового чата

Текущий цикл реализации закрыт. Следующая работа должна начинаться не с новой функции наугад, а с безопасной агрегированной проверки STEP 8.

Первое действие нового чата:
1. Открыть этот handoff.
2. Проверить origin/main и live health/parity.
3. Посчитать только агрегированные ui_feature_opened по feature и platform для week, relevant, notifications, cf_ideas, moments.
4. Не читать пользовательские тексты, diary/medical content и персональные строки.
5. По фактическому использованию выбрать одну следующую маленькую доработку.
6. Выполнить её по схеме: isolated worktree → focused tests → PR/CI → merge → controlled production check.

Если данных по новым функциям ещё мало — не придумывать вывод; зафиксировать недостаточную выборку и выбрать только техническую/UX правку, подтверждённую live-проверкой.

## Команда для нового чата

Открой GitHub demo23rus/Mama, прочитай docs/CURRENT_HANDOFF.md и продолжай Мамин Помощник с NEXT. Сначала проверь агрегированную UX-аналитику новых функций, без чтения пользовательских текстов и медицинских данных.

# PRODUCT_MAP — Мамин Помощник Mini App

## Основные экраны

- Home
- Assistant
- Trackers
- History
- Profile

Frontend на сегодня содержит 80 `render*`-функций экранов/состояний внутри
`miniapp_frontend` (зеркало `/var/www/mama-miniapp`).

## Backend API (`/api/miniapp/...`)

Backend (`mama_max_bot.py`) экспонирует 50+ маршрутов, сгруппированных по
продуктовым областям:

- Профиль и общее: profile, home/today, referral, feedback, support,
  reset-me.
- Ассистент: ask-question, psycho, tantrums/emotions.
- Беременность и первые дни: pregnancy, firstdays, breastfeeding, recovery.
- Трекеры ребёнка: child, sleep, feeding, complementary-foods (6+ месяцев,
  `complementary_food_log`), growth, vaccines, symptoms, diary.
- Экстренные ситуации: emergency.
- Детский сад: kindergarten.
- Прочее: benefits, photo analysis, personal-review.

## Монетизация

- Основной пользовательский опыт (трекеры, дневник, ассистент) — бесплатный.
- Добровольная поддержка проекта и платный персональный разбор
  (personal-review) — отдельные необязательные flows, не блокирующие
  основной продукт.
- Конкретные цены/условия здесь не фиксируются сверх уже подтверждённых в
  существующих source/constants; не изобретать новые детали монетизации в
  документации.

## Платформенные особенности

- Shared Mini App backend обслуживает Telegram и MAX через единый auth/
  platform routing слой в `mama_max_bot.py`.
- Telegram и MAX используют раздельные production SQLite базы
  (`/root/mama.db`, `/root/mama_max.db`) — см. [DATA_MODEL.md](DATA_MODEL.md).

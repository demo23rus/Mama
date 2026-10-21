# DATA_MODEL — Мамин Помощник

Документируются только имена таблиц и файлы БД. Строки/пользовательские данные не документируются и не инспектируются.

## Базы данных

Telegram и MAX используют раздельные production SQLite файлы:

- `/root/mama.db` — Telegram, **32** пользовательские таблицы.
- `/root/mama_max.db` — MAX, **36** пользовательских таблиц.

## Таблицы Telegram (`mama.db`)

```
analytics_events, baby_moments, broadcast_log, channel_posts,
complementary_food_log, diary, feedback_campaign_likes, feeding, growth,
marketing_offers, notification_delivery_log, notification_settings,
payments, pending_payments, personal_reviews, processed_payments,
psycho_history, purchases, referral_bonus_questions, referrals,
requests_count, sales_events, sleep_log, subscription_history,
subscriptions, support_payments, symptoms, usage_counters, usage_periods,
user_credits, users, vaccinations
```

## Таблицы MAX (`mama_max.db`)

```
analytics_events, baby_moments, broadcast_log, channel_poll_votes,
channel_posts, command_locks, complementary_food_log, diary,
feedback_campaign_likes, feeding, growth, limits, marketing_offers,
max_user_chats, notification_delivery_log, notification_settings,
payments, pending_payments, processed_payments, psycho_history, purchases,
referral_bonus_questions, referrals, requests_count, reviews, sales_events,
sleep_log, subscription_history, subscriptions, support_payments, symptoms,
usage_counters, usage_periods, user_credits, users, vaccinations
```

## Новые группы текущего цикла

- `notification_settings` — пользовательские toggles Центра уведомлений.
- `notification_delivery_log` — persistent dedupe для proactive reminders.
- `baby_moments` — структурированная хронология «Моменты малыша».
- `analytics_events` — существующая таблица, переиспользованная STEP 8 для безопасного события `ui_feature_opened`.

STEP 8 не создаёт отдельную analytics-таблицу и не должен писать туда пользовательские тексты, содержимое дневника, медицинские данные или profile details.

## Правила доступа к данным

- Direct production editing БД запрещён; изменения схемы — только через согласованный implementation/deploy flow.
- БД, `.env` файлы и прочие secrets не коммитятся в репозиторий.
- Для product/retention решений использовать агрегаты; не читать и не документировать строки с персональными пользовательскими данными.
- Telegram/MAX namespaces не объединять.

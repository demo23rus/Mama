# DATA_MODEL — Мамин Помощник

Документируются только имена таблиц и файлы БД. Строки/пользовательские
данные не документируются и не инспектируются.

## Базы данных

Telegram и MAX используют раздельные production SQLite файлы:

- `/root/mama.db` — Telegram, 29 таблиц.
- `/root/mama_max.db` — MAX, 33 таблицы.

## Таблицы Telegram (`mama.db`)

```
analytics_events, broadcast_log, channel_posts, complementary_food_log,
diary, feedback_campaign_likes, feeding, growth, marketing_offers,
payments, pending_payments, personal_reviews, processed_payments,
psycho_history, purchases, referral_bonus_questions, referrals,
requests_count, sales_events, sleep_log, subscription_history,
subscriptions, support_payments, symptoms, usage_counters, usage_periods,
user_credits, users, vaccinations
```

## Таблицы MAX (`mama_max.db`)

Включает все группы схем Telegram (см. выше) плюс:

```
channel_poll_votes, command_locks, limits, max_user_chats, reviews
```

## Правила доступа к данным

- Direct production editing БД запрещён; изменения схемы — через отдельный
  owner-approved JOB с контролируемым deploy.
- БД, `.env` файлы и прочие secrets не коммитятся в репозиторий (см.
  `.gitignore` и [SECURITY.md](SECURITY.md)).
- Workers не читают и не документируют содержимое строк/персональные данные
  пользователей — только структуру (имена таблиц).

"""Известия при събития (Фаза 5, първи срез — docs/12-notifications-plan.md).

Канали: Telegram (Bot API), имейл (SMTP), webhook (JSON POST). Engine-ът
взима всяко локално съобщение от ingest, мачва topic_pattern на каналите и
изпраща асинхронно (опашка + работник), без да blokira приемането. Анти-спам:
min_interval_s на канал + дедуп на (канал, тема, съдържание) за 60 s."""
from .engine import NotificationEngine, render_message  # noqa: F401

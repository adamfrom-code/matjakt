# -*- coding: utf-8 -*-
"""Web Push: prenumerationer, avsändare och söndagsschemat (H1).

Tre filer, tre jobb:

  store.py     push_subscriptions + push_log i KONTOdatabasen.
  webpush.py   RFC 8291 (kryptering) + RFC 8292 (VAPID). Tiger utan nycklar.
  schedule.py  Söndag 17:00 Europe/Stockholm, en notis per konto och söndag.

SAMTYCKET BOR INTE HÄR. Det ligger i notification_prefs
(services/household/notifications.py), samma brytare som hushållsnotiserna
använder - `week`/"Ny vecka". Ett andra system bredvid hade betytt att en
användare kan stänga av veckonotiser på ett ställe och ändå få dem.
"""

from .schedule import (
    CHECK_INTERVAL_SECONDS, KIND, SEND_AT, SEND_WEEKDAY, WeeklyPushScheduler,
    week_notification,
)
from .store import PushStore
from .webpush import WebPushError, WebPushGone, WebPushSender

__all__ = [
    "CHECK_INTERVAL_SECONDS", "KIND", "SEND_AT", "SEND_WEEKDAY",
    "PushStore", "WeeklyPushScheduler", "WebPushError", "WebPushGone",
    "WebPushSender", "week_notification",
]

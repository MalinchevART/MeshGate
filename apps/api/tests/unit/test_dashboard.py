"""Т8 unit тестове: чистите функции на dashboard (кофите)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.routes.dashboard import _fill_sent_buckets


def test_sent_buckets_eight_zero_filled():
    rows = [
        {"bucket": datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0),
         "sent": 5, "failed": 1},
    ]
    out = _fill_sent_buckets(rows)
    assert len(out) == 8
    # точно една непразна кофа (ако bucket-ът съвпадне със стена)
    nonempty = [b for b in out if b["sent"] or b["failed"]]
    assert len(nonempty) <= 1
    # нарастващи стени, по 3ч
    times = [datetime.fromisoformat(b["bucket"]) for b in out]
    assert all((times[i + 1] - times[i]) == timedelta(hours=3) for i in range(7))


def test_sent_buckets_all_zero_when_empty():
    out = _fill_sent_buckets([])
    assert len(out) == 8
    assert all(b["sent"] == 0 and b["failed"] == 0 for b in out)


def test_sent_buckets_none_sent_safe():
    """asyncpg връща None за count(*) FILTER без мачове — кофата е 0, не None."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    # кофата на функцията е подравнена до стенен час кратно на 3
    bucket = now - timedelta(hours=now.hour % 3)
    rows = [{"bucket": bucket, "sent": None, "failed": 3}]
    out = _fill_sent_buckets(rows)
    nonempty = [b for b in out if b["failed"]]
    assert len(nonempty) == 1 and nonempty[0]["failed"] == 3

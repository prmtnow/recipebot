import sqlite3

import pytest

from app.store import Store

DAY = "2026-11-24"
NEXT = "2026-11-25"


def make_store(tmp_path):
    return Store(str(tmp_path / "bot.db"))


def test_mark_seen_first_true_second_false(tmp_path):
    s = make_store(tmp_path)
    assert s.mark_seen("m1") is True
    assert s.mark_seen("m1") is False
    assert s.mark_seen("m2") is True


def test_consume_quota_limit_per_user_and_day(tmp_path):
    s = make_store(tmp_path)
    assert all(s.consume_quota("u1", DAY, 5) for _ in range(5))
    assert s.consume_quota("u1", DAY, 5) is False
    assert s.consume_quota("u2", DAY, 5) is True
    assert s.consume_quota("u1", NEXT, 5) is True


def test_denied_quota_does_not_increment(tmp_path):
    s = make_store(tmp_path)
    for _ in range(5):
        s.consume_quota("u1", DAY, 5)
    s.consume_quota("u1", DAY, 5)  # denied
    db = sqlite3.connect(str(tmp_path / "bot.db"))
    (count,) = db.execute(
        "SELECT count FROM quotas WHERE igsid='u1' AND day=?", (DAY,)).fetchone()
    assert count == 5


def test_cost_accumulates_per_day(tmp_path):
    s = make_store(tmp_path)
    assert s.today_cost(DAY) == 0.0
    s.add_cost(0.1, DAY)
    s.add_cost(0.2, DAY)
    assert s.today_cost(DAY) == pytest.approx(0.3)
    assert s.today_cost(NEXT) == 0.0


def test_log_conversion_roundtrip(tmp_path):
    s = make_store(tmp_path)
    s.log_conversion("u1", "m1", "ok", "# Recipe", 0.05)
    db = sqlite3.connect(str(tmp_path / "bot.db"))
    row = db.execute(
        "SELECT igsid, message_id, status, recipe_text, cost_usd FROM conversions"
    ).fetchone()
    assert row == ("u1", "m1", "ok", "# Recipe", 0.05)

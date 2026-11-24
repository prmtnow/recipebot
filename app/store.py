import sqlite3
import threading


class Store:
    """SQLite-backed dedup, per-user quota, spend tracking and conversion log."""

    def __init__(self, db_path: str):
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._db:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS seen_messages (
                    message_id TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS quotas (
                    igsid TEXT NOT NULL,
                    day   TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (igsid, day)
                );
                CREATE TABLE IF NOT EXISTS cost (
                    day      TEXT PRIMARY KEY,
                    cost_usd REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS conversions (
                    igsid       TEXT NOT NULL,
                    message_id  TEXT NOT NULL,
                    status      TEXT NOT NULL,
                    recipe_text TEXT,
                    cost_usd    REAL NOT NULL
                );
            """)

    def mark_seen(self, message_id: str) -> bool:
        with self._lock, self._db:
            try:
                self._db.execute(
                    "INSERT INTO seen_messages (message_id) VALUES (?)", (message_id,))
                return True
            except sqlite3.IntegrityError:
                return False

    def consume_quota(self, igsid: str, day: str, limit: int) -> bool:
        with self._lock, self._db:
            cur = self._db.execute(
                "UPDATE quotas SET count = count + 1 "
                "WHERE igsid=? AND day=? AND count < ?", (igsid, day, limit))
            if cur.rowcount:
                return True
            row = self._db.execute(
                "SELECT count FROM quotas WHERE igsid=? AND day=?",
                (igsid, day)).fetchone()
            if row is None:
                self._db.execute(
                    "INSERT INTO quotas (igsid, day, count) VALUES (?, ?, 1)",
                    (igsid, day))
                return True
            return False

    def add_cost(self, cost_usd: float, day: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO cost (day, cost_usd) VALUES (?, ?) "
                "ON CONFLICT(day) DO UPDATE SET cost_usd = cost_usd + excluded.cost_usd",
                (day, cost_usd))

    def today_cost(self, day: str) -> float:
        row = self._db.execute(
            "SELECT cost_usd FROM cost WHERE day=?", (day,)).fetchone()
        return row[0] if row else 0.0

    def log_conversion(self, igsid: str, message_id: str, status: str,
                       recipe_text: str | None, cost_usd: float) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO conversions (igsid, message_id, status, recipe_text, cost_usd)"
                " VALUES (?, ?, ?, ?, ?)",
                (igsid, message_id, status, recipe_text, cost_usd))

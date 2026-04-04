from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).with_name("family_bot.db")

_conn: Optional[sqlite3.Connection] = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            role TEXT NOT NULL,
            name TEXT,
            age INTEGER,
            city TEXT,
            interests TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            kind TEXT NOT NULL,          -- 'meds', 'doctor', 'water', ...
            text TEXT NOT NULL,
            time_local TEXT NOT NULL,    -- 'HH:MM'
            enabled INTEGER NOT NULL DEFAULT 1
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            kind TEXT NOT NULL,          -- 'talk', 'reminder_done', 'sos'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS relatives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            senior_telegram_id INTEGER NOT NULL,
            relative_telegram_id INTEGER NOT NULL
        )
        """
    )

    conn.commit()


def upsert_user(
    telegram_id: int,
    role: str,
    name: str | None,
    age: int | None,
    city: str | None,
    interests: str | None,
) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO users (telegram_id, role, name, age, city, interests)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            role=excluded.role,
            name=excluded.name,
            age=excluded.age,
            city=excluded.city,
            interests=excluded.interests
        """,
        (telegram_id, role, name, age, city, interests),
    )
    conn.commit()


def list_reminders(telegram_id: int) -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, kind, text, time_local, enabled FROM reminders WHERE telegram_id=? ORDER BY time_local",
        (telegram_id,),
    )
    return [dict(row) for row in cur.fetchall()]


def add_reminder(
    telegram_id: int,
    kind: str,
    text: str,
    time_local: str,
) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO reminders (telegram_id, kind, text, time_local)
        VALUES (?, ?, ?, ?)
        """,
        (telegram_id, kind, text, time_local),
    )
    conn.commit()
    return int(cur.lastrowid)


def log_activity(telegram_id: int, kind: str) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO activity_log (telegram_id, kind) VALUES (?, ?)",
        (telegram_id, kind),
    )
    conn.commit()


def get_activity_summary(telegram_id: int) -> Dict[str, Any]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT kind, COUNT(*) AS cnt
        FROM activity_log
        WHERE telegram_id = ?
          AND created_at >= datetime('now', '-1 day')
        GROUP BY kind
        """,
        (telegram_id,),
    )
    rows = cur.fetchall()
    summary = {row["kind"]: row["cnt"] for row in rows}
    return summary


def add_relative_link(senior_telegram_id: int, relative_telegram_id: int) -> None:
    """Создать связь «пожилой ↔ родственник» (простая версия без кодов)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO relatives (senior_telegram_id, relative_telegram_id)
        VALUES (?, ?)
        """,
        (senior_telegram_id, relative_telegram_id),
    )
    conn.commit()


def get_relatives_for_senior(senior_telegram_id: int) -> List[int]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT relative_telegram_id FROM relatives WHERE senior_telegram_id=?",
        (senior_telegram_id,),
    )
    return [int(row[0]) for row in cur.fetchall()]




import sqlite3
from datetime import datetime

# ---------- Инициализация основных таблиц ----------
def init_db():
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            name TEXT,
            age INTEGER,
            city TEXT,
            interests TEXT,
            role TEXT DEFAULT 'senior'
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            kind TEXT,
            text TEXT,
            time_local TEXT,
            enabled INTEGER DEFAULT 1
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            action TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица relatives с правильной структурой (senior_id, relative_id)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='relatives'")
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(relatives)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'senior_id' not in columns or 'relative_id' not in columns:
            cursor.execute("DROP TABLE relatives")
            cursor.execute("""
                CREATE TABLE relatives (
                    senior_id INTEGER,
                    relative_id INTEGER,
                    PRIMARY KEY (senior_id, relative_id)
                )
            """)
    else:
        cursor.execute("""
            CREATE TABLE relatives (
                senior_id INTEGER,
                relative_id INTEGER,
                PRIMARY KEY (senior_id, relative_id)
            )
        """)
    
    conn.commit()
    conn.close()

def init_chat_history_table():
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_history_user_id ON chat_history(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_history_created_at ON chat_history(created_at)")
    conn.commit()
    conn.close()

def init_family_feed_table():
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS family_feed (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            author_name TEXT,
            message TEXT NOT NULL,
            message_type TEXT DEFAULT 'text',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_family_feed_family_id ON family_feed(family_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_family_feed_created_at ON family_feed(created_at)")
    conn.commit()
    conn.close()

def init_calendar_table():
    """Создаёт таблицу для календаря событий (дни рождения, праздники, встречи)."""
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_date TEXT NOT NULL,
            event_time TEXT,
            title TEXT NOT NULL,
            description TEXT,
            event_type TEXT DEFAULT 'other',
            remind_before_days INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_calendar_user_id ON calendar_events(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_calendar_date ON calendar_events(event_date)")
    conn.commit()
    conn.close()


# ---------- Пользователи ----------
def upsert_user(telegram_id, role, name=None, age=None, city=None, interests=None):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO users (telegram_id, name, age, city, interests, role)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (telegram_id, name, age, city, interests, role))
    conn.commit()
    conn.close()

def get_user(telegram_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, age, city, interests, role FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"name": row[0], "age": row[1], "city": row[2], "interests": row[3], "role": row[4]}
    return None


# ---------- Напоминания ----------
def add_reminder(telegram_id, kind, text, time_local):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reminders (telegram_id, kind, text, time_local) VALUES (?, ?, ?, ?)",
                   (telegram_id, kind, text, time_local))
    conn.commit()
    conn.close()

def list_reminders(telegram_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, kind, text, time_local, enabled FROM reminders WHERE telegram_id = ?", (telegram_id,))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "kind": r[1], "text": r[2], "time_local": r[3], "enabled": r[4]} for r in rows]


# ---------- Активности ----------
def log_activity(telegram_id, action):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO activities (telegram_id, action) VALUES (?, ?)", (telegram_id, action))
    conn.commit()
    conn.close()

def get_activity_summary(telegram_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM activities WHERE telegram_id = ? AND action = 'talk' AND created_at > datetime('now', '-1 day')", (telegram_id,))
    talk = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM activities WHERE telegram_id = ? AND action = 'reminder_done' AND created_at > datetime('now', '-1 day')", (telegram_id,))
    reminder_done = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM activities WHERE telegram_id = ? AND action = 'sos' AND created_at > datetime('now', '-1 day')", (telegram_id,))
    sos = cursor.fetchone()[0]
    conn.close()
    return {"talk": talk, "reminder_done": reminder_done, "sos": sos}


# ---------- Родственники ----------
def add_relative_link(senior_telegram_id, relative_telegram_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO relatives (senior_id, relative_id) VALUES (?, ?)", 
                   (senior_telegram_id, relative_telegram_id))
    conn.commit()
    conn.close()

def get_relatives_for_senior(senior_telegram_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT relative_id FROM relatives WHERE senior_id = ?", (senior_telegram_id,))
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]


# ---------- История диалогов ----------
def save_message(user_id: int, role: str, message: str):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO chat_history (user_id, role, message) VALUES (?, ?, ?)", (user_id, role, message))
    conn.commit()
    conn.close()

def get_chat_history(user_id: int, limit: int = 10) -> list:
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT role, message FROM chat_history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?", (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    history = [{"role": row[0], "content": row[1]} for row in reversed(rows)]
    return history

def clear_chat_history(user_id: int):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


# ---------- Семейная лента ----------
def get_family_id_for_user(user_id: int) -> int:
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE telegram_id = ?", (user_id,))
    row = cursor.fetchone()
    if row and row[0] == "senior":
        conn.close()
        return user_id
    cursor.execute("SELECT senior_id FROM relatives WHERE relative_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]
    return None

def add_to_family_feed(family_id: int, author_id: int, author_name: str, message: str, message_type: str = "text"):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO family_feed (family_id, author_id, author_name, message, message_type)
        VALUES (?, ?, ?, ?, ?)
    """, (family_id, author_id, author_name, message, message_type))
    conn.commit()
    conn.close()

def get_family_feed(family_id: int, limit: int = 20) -> list:
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT author_name, message, message_type, created_at
        FROM family_feed
        WHERE family_id = ?
        ORDER BY created_at DESC LIMIT ?
    """, (family_id, limit))
    rows = cursor.fetchall()
    conn.close()
    feed = []
    for row in reversed(rows):
        feed.append({
            "author_name": row[0],
            "message": row[1],
            "message_type": row[2],
            "created_at": row[3]
        })
    return feed


# ---------- Календарь событий ----------
def add_event(user_id: int, event_date: str, title: str, description: str = None,
              event_time: str = None, event_type: str = "other", remind_before_days: int = 1) -> int:
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO calendar_events (user_id, event_date, event_time, title, description, event_type, remind_before_days)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, event_date, event_time, title, description, event_type, remind_before_days))
    event_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return event_id

def get_events_for_user(user_id: int, from_date: str = None, limit: int = 50) -> list:
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    if from_date:
        cursor.execute("""
            SELECT id, event_date, event_time, title, description, event_type, remind_before_days
            FROM calendar_events
            WHERE user_id = ? AND event_date >= ?
            ORDER BY event_date ASC, event_time ASC
            LIMIT ?
        """, (user_id, from_date, limit))
    else:
        cursor.execute("""
            SELECT id, event_date, event_time, title, description, event_type, remind_before_days
            FROM calendar_events
            WHERE user_id = ?
            ORDER BY event_date ASC, event_time ASC
            LIMIT ?
        """, (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [{
        "id": r[0],
        "date": r[1],
        "time": r[2],
        "title": r[3],
        "description": r[4],
        "type": r[5],
        "remind_before_days": r[6]
    } for r in rows]

def get_event_by_id(event_id: int):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, user_id, event_date, event_time, title, description, event_type, remind_before_days
        FROM calendar_events WHERE id = ?
    """, (event_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "id": row[0],
            "user_id": row[1],
            "date": row[2],
            "time": row[3],
            "title": row[4],
            "description": row[5],
            "type": row[6],
            "remind_before_days": row[7]
        }
    return None

def delete_event(event_id: int, user_id: int) -> bool:
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM calendar_events WHERE id = ? AND user_id = ?", (event_id, user_id))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def get_events_by_date(target_date: str) -> list:
    """Возвращает события на конкретную дату (для ежедневных напоминаний)."""
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, user_id, event_date, event_time, title, description, event_type, remind_before_days
        FROM calendar_events
        WHERE event_date = ?
    """, (target_date,))
    rows = cursor.fetchall()
    conn.close()
    return [{
        "id": r[0],
        "user_id": r[1],
        "date": r[2],
        "time": r[3],
        "title": r[4],
        "description": r[5],
        "type": r[6],
        "remind_before_days": r[7]
    } for r in rows]

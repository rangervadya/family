import sqlite3
import csv
import io
from datetime import datetime, timedelta
import secrets

# ---------- Инициализация всех таблиц ----------
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
            role TEXT DEFAULT 'senior',
            language TEXT DEFAULT 'ru'
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS relatives (
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
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            target_user_id INTEGER,
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

def init_games_table():
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS games_state (
            user_id INTEGER PRIMARY KEY,
            game_name TEXT,
            game_data TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def init_media_table():
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS media_albums (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            author_name TEXT,
            file_type TEXT NOT NULL,
            file_id TEXT NOT NULL,
            caption TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_family_id ON media_albums(family_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_created_at ON media_albums(created_at)")
    conn.commit()
    conn.close()

def init_health_table():
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS health_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            record_date TEXT NOT NULL,
            record_time TEXT,
            systolic INTEGER,
            diastolic INTEGER,
            pulse INTEGER,
            blood_sugar REAL,
            weight REAL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_health_user_date ON health_records(user_id, record_date)")
    conn.commit()
    conn.close()

def init_budget_table():
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS budget_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            family_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            type TEXT NOT NULL,
            transaction_date TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS budget_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            type TEXT NOT NULL,
            icon TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_budget_family_date ON budget_transactions(family_id, transaction_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_budget_user ON budget_transactions(user_id)")
    conn.commit()
    cursor.execute("SELECT COUNT(*) FROM budget_categories")
    if cursor.fetchone()[0] == 0:
        default_categories = [
            ("Зарплата", "income", "💰"), ("Пенсия", "income", "🏦"), ("Подарок", "income", "🎁"),
            ("Продукты", "expense", "🍎"), ("Лекарства", "expense", "💊"), ("Коммунальные услуги", "expense", "🏠"),
            ("Транспорт", "expense", "🚗"), ("Развлечения", "expense", "🎬"), ("Одежда", "expense", "👕"),
            ("Здоровье", "expense", "🏥"), ("Другое", "expense", "📦")
        ]
        for name, typ, icon in default_categories:
            cursor.execute("INSERT INTO budget_categories (name, type, icon) VALUES (?, ?, ?)", (name, typ, icon))
    conn.commit()
    conn.close()

def init_premium_tables():
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS premium_users (
            user_id INTEGER PRIMARY KEY,
            expires_at TIMESTAMP NOT NULL,
            activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS premium_codes (
            code TEXT PRIMARY KEY,
            days INTEGER NOT NULL,
            used_by INTEGER,
            used_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
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

def set_user_language(telegram_id, lang):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET language = ? WHERE telegram_id = ?", (lang, telegram_id))
    conn.commit()
    conn.close()

def get_user_language(telegram_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT language FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 'ru'

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
              event_time: str = None, event_type: str = "other", remind_before_days: int = 1,
              target_user_id: int = None) -> int:
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO calendar_events (user_id, target_user_id, event_date, event_time, title, description, event_type, remind_before_days)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, target_user_id, event_date, event_time, title, description, event_type, remind_before_days))
    event_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return event_id

def get_events_for_user(user_id: int, from_date: str = None, limit: int = 50) -> list:
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    if from_date:
        cursor.execute("""
            SELECT id, event_date, event_time, title, description, event_type, remind_before_days, target_user_id
            FROM calendar_events
            WHERE user_id = ? AND event_date >= ?
            ORDER BY event_date ASC, event_time ASC
            LIMIT ?
        """, (user_id, from_date, limit))
    else:
        cursor.execute("""
            SELECT id, event_date, event_time, title, description, event_type, remind_before_days, target_user_id
            FROM calendar_events
            WHERE user_id = ?
            ORDER BY event_date ASC, event_time ASC
            LIMIT ?
        """, (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [{
        "id": r[0], "date": r[1], "time": r[2], "title": r[3], "description": r[4],
        "type": r[5], "remind_before_days": r[6], "target_user_id": r[7]
    } for r in rows]

def delete_event(event_id: int, user_id: int) -> bool:
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM calendar_events WHERE id = ? AND user_id = ?", (event_id, user_id))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def get_events_by_date(target_date: str) -> list:
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, user_id, event_date, event_time, title, description, event_type, remind_before_days, target_user_id
        FROM calendar_events
        WHERE event_date = ?
    """, (target_date,))
    rows = cursor.fetchall()
    conn.close()
    return [{
        "id": r[0], "user_id": r[1], "date": r[2], "time": r[3], "title": r[4], "description": r[5],
        "type": r[6], "remind_before_days": r[7], "target_user_id": r[8]
    } for r in rows]

def get_birthdays_for_date(target_date: str, family_id: int = None) -> list:
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    if family_id:
        cursor.execute("SELECT relative_id FROM relatives WHERE senior_id = ?", (family_id,))
        relatives = [row[0] for row in cursor.fetchall()]
        relatives.append(family_id)
        placeholders = ','.join('?' for _ in relatives)
        query = f"""
            SELECT id, user_id, target_user_id, title, description
            FROM calendar_events
            WHERE event_date = ? AND event_type = 'birthday' AND user_id IN ({placeholders})
        """
        cursor.execute(query, (target_date, *relatives))
    else:
        cursor.execute("""
            SELECT id, user_id, target_user_id, title, description
            FROM calendar_events
            WHERE event_date = ? AND event_type = 'birthday'
        """, (target_date,))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "user_id": r[1], "target_user_id": r[2], "title": r[3], "description": r[4]} for r in rows]

# ---------- Игры ----------
def save_game_state(user_id: int, game_name: str, game_data: str):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO games_state (user_id, game_name, game_data) VALUES (?, ?, ?)",
                   (user_id, game_name, game_data))
    conn.commit()
    conn.close()

def get_game_state(user_id: int):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT game_name, game_data FROM games_state WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"game_name": row[0], "game_data": row[1]}
    return None

def clear_game_state(user_id: int):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM games_state WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# ---------- Медиа ----------
def save_media(family_id: int, author_id: int, author_name: str, file_type: str, file_id: str, caption: str = None):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO media_albums (family_id, author_id, author_name, file_type, file_id, caption)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (family_id, author_id, author_name, file_type, file_id, caption))
    conn.commit()
    conn.close()

def get_family_media(family_id: int, limit: int = 20) -> list:
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, author_name, file_type, file_id, caption, created_at
        FROM media_albums
        WHERE family_id = ?
        ORDER BY created_at DESC LIMIT ?
    """, (family_id, limit))
    rows = cursor.fetchall()
    conn.close()
    media_list = []
    for row in reversed(rows):
        media_list.append({
            "id": row[0], "author": row[1], "type": row[2], "file_id": row[3], "caption": row[4], "date": row[5]
        })
    return media_list

# ---------- Медицинский дневник ----------
def add_health_record(user_id, record_date, systolic=None, diastolic=None, pulse=None,
                      blood_sugar=None, weight=None, notes=None, record_time=None):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO health_records (user_id, record_date, record_time, systolic, diastolic, pulse, blood_sugar, weight, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, record_date, record_time, systolic, diastolic, pulse, blood_sugar, weight, notes))
    conn.commit()
    conn.close()

def get_health_records(user_id, days=30):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, record_date, record_time, systolic, diastolic, pulse, blood_sugar, weight, notes, created_at
        FROM health_records
        WHERE user_id = ? AND record_date >= date('now', '-' || ? || ' days')
        ORDER BY record_date DESC, record_time DESC
    """, (user_id, days))
    rows = cursor.fetchall()
    conn.close()
    return [{
        "id": r[0], "date": r[1], "time": r[2],
        "systolic": r[3], "diastolic": r[4], "pulse": r[5],
        "blood_sugar": r[6], "weight": r[7], "notes": r[8], "created_at": r[9]
    } for r in rows]

def get_health_stats(user_id, days=30):
    records = get_health_records(user_id, days)
    if not records:
        return None
    systolic_vals = [r['systolic'] for r in records if r['systolic']]
    diastolic_vals = [r['diastolic'] for r in records if r['diastolic']]
    pulse_vals = [r['pulse'] for r in records if r['pulse']]
    sugar_vals = [r['blood_sugar'] for r in records if r['blood_sugar']]
    weight_vals = [r['weight'] for r in records if r['weight']]
    return {
        "systolic_avg": sum(systolic_vals)/len(systolic_vals) if systolic_vals else None,
        "diastolic_avg": sum(diastolic_vals)/len(diastolic_vals) if diastolic_vals else None,
        "pulse_avg": sum(pulse_vals)/len(pulse_vals) if pulse_vals else None,
        "sugar_avg": sum(sugar_vals)/len(sugar_vals) if sugar_vals else None,
        "weight_avg": sum(weight_vals)/len(weight_vals) if weight_vals else None,
        "last_systolic": systolic_vals[-1] if systolic_vals else None,
        "last_diastolic": diastolic_vals[-1] if diastolic_vals else None,
        "last_pulse": pulse_vals[-1] if pulse_vals else None,
        "last_sugar": sugar_vals[-1] if sugar_vals else None,
        "last_weight": weight_vals[-1] if weight_vals else None,
        "records_count": len(records)
    }

# ---------- Экспорт CSV ----------
def export_chat_history(user_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT role, message, created_at FROM chat_history WHERE user_id = ? ORDER BY created_at", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Роль", "Сообщение", "Дата и время"])
    for row in rows:
        writer.writerow(row)
    return output.getvalue()

def export_health_records(user_id):
    records = get_health_records(user_id, days=365)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Дата", "Время", "Давление", "Пульс", "Сахар", "Вес", "Заметки"])
    for r in records:
        bp = f"{r['systolic']}/{r['diastolic']}" if r['systolic'] and r['diastolic'] else ""
        writer.writerow([r['date'], r['time'] or "", bp, r['pulse'] or "", r['blood_sugar'] or "", r['weight'] or "", r['notes'] or ""])
    return output.getvalue()

def export_family_feed(family_id):
    feed = get_family_feed(family_id, limit=1000)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Автор", "Сообщение", "Тип", "Дата"])
    for f in feed:
        writer.writerow([f['author_name'], f['message'], f['message_type'], f['created_at']])
    return output.getvalue()

# ---------- Бюджет ----------
def add_transaction(user_id, family_id, amount, category, transaction_type, transaction_date, description=None):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO budget_transactions (user_id, family_id, amount, category, type, transaction_date, description)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, family_id, amount, category, transaction_type, transaction_date, description))
    conn.commit()
    conn.close()

def get_transactions(family_id, limit=50):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, user_id, amount, category, type, transaction_date, description, created_at
        FROM budget_transactions
        WHERE family_id = ?
        ORDER BY transaction_date DESC LIMIT ?
    """, (family_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "user_id": r[1], "amount": r[2], "category": r[3], "type": r[4], "date": r[5], "description": r[6], "created_at": r[7]} for r in rows]

def get_budget_summary(family_id, start_date=None, end_date=None):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    query_income = "SELECT SUM(amount) FROM budget_transactions WHERE family_id = ? AND type = 'income'"
    query_expense = "SELECT SUM(amount) FROM budget_transactions WHERE family_id = ? AND type = 'expense'"
    params = [family_id]
    if start_date:
        query_income += " AND transaction_date >= ?"
        query_expense += " AND transaction_date >= ?"
        params.append(start_date)
    if end_date:
        query_income += " AND transaction_date <= ?"
        query_expense += " AND transaction_date <= ?"
        params.append(end_date)
    cursor.execute(query_income, params)
    income = cursor.fetchone()[0] or 0
    cursor.execute(query_expense, params)
    expense = cursor.fetchone()[0] or 0
    conn.close()
    return {"income": income, "expense": expense, "balance": income - expense}

def get_categories():
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, type, icon FROM budget_categories ORDER BY type, name")
    rows = cursor.fetchall()
    conn.close()
    return [{"name": r[0], "type": r[1], "icon": r[2]} for r in rows]

def get_category_breakdown(family_id, start_date=None, end_date=None):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    query = """
        SELECT category, type, SUM(amount) as total
        FROM budget_transactions
        WHERE family_id = ?
    """
    params = [family_id]
    if start_date:
        query += " AND transaction_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND transaction_date <= ?"
        params.append(end_date)
    query += " GROUP BY category, type"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    breakdown = {}
    for row in rows:
        breakdown[row[0]] = {"type": row[1], "total": row[2]}
    return breakdown

# ---------- Премиум ----------
def is_premium(user_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT expires_at FROM premium_users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return False
    expires_at = datetime.fromisoformat(row[0])
    return expires_at > datetime.now()

def add_premium_user(user_id, days):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    expires_at = datetime.now() + timedelta(days=days)
    cursor.execute("INSERT OR REPLACE INTO premium_users (user_id, expires_at) VALUES (?, ?)",
                   (user_id, expires_at.isoformat()))
    conn.commit()
    conn.close()

def generate_code(days):
    code = secrets.token_hex(8).upper()
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO premium_codes (code, days) VALUES (?, ?)", (code, days))
    conn.commit()
    conn.close()
    return code

def activate_code(code, user_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT days, used_by FROM premium_codes WHERE code = ?", (code,))
    row = cursor.fetchone()
    if not row or row[1] is not None:
        conn.close()
        return False
    days = row[0]
    cursor.execute("UPDATE premium_codes SET used_by = ?, used_at = CURRENT_TIMESTAMP WHERE code = ?", (user_id, code))
    conn.commit()
    conn.close()
    add_premium_user(user_id, days)
    return True

def get_premium_expiry(user_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT expires_at FROM premium_users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return datetime.fromisoformat(row[0])
    return None

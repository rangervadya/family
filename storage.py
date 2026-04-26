import sqlite3
import json
from datetime import datetime, timedelta, date
import random
import string

DB_NAME = "family_bot.db"

def get_db():
    return sqlite3.connect(DB_NAME)

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Исправление таблицы users (если колонка называется id)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'user_id' not in columns:
            cursor.execute("ALTER TABLE users RENAME TO users_old")
            cursor.execute('''
                CREATE TABLE users (
                    user_id INTEGER PRIMARY KEY,
                    role TEXT,
                    name TEXT,
                    age INTEGER,
                    city TEXT,
                    interests TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute("SELECT id, role, name, age, city, interests, created_at FROM users_old")
            rows = cursor.fetchall()
            cursor.executemany('''
                INSERT INTO users (user_id, role, name, age, city, interests, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', rows)
            cursor.execute("DROP TABLE users_old")
    else:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                role TEXT,
                name TEXT,
                age INTEGER,
                city TEXT,
                interests TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    
    # ПРИНУДИТЕЛЬНОЕ ПЕРЕСОЗДАНИЕ ТАБЛИЦЫ relatives (если она существует, но не имеет senior_id)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='relatives'")
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(relatives)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'senior_id' not in columns:
            cursor.execute("DROP TABLE relatives")
            cursor.execute('''
                CREATE TABLE relatives (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    senior_id INTEGER NOT NULL,
                    relative_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(senior_id, relative_id)
                )
            ''')
    else:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS relatives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                senior_id INTEGER NOT NULL,
                relative_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(senior_id, relative_id)
            )
        ''')
    
    # Все остальные таблицы (без изменений)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            text TEXT,
            time_local TEXT,
            enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS family_feed (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER,
            user_id INTEGER,
            author_name TEXT,
            message TEXT,
            type TEXT DEFAULT 'message',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            event_date TEXT,
            event_time TEXT,
            title TEXT,
            description TEXT,
            event_type TEXT,
            remind_before_days INTEGER DEFAULT 1,
            target_user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS game_states (
            user_id INTEGER PRIMARY KEY,
            game_name TEXT,
            game_data TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER,
            user_id INTEGER,
            author TEXT,
            file_id TEXT,
            type TEXT,
            caption TEXT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS health_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            record_date TEXT,
            record_time TEXT,
            systolic INTEGER,
            diastolic INTEGER,
            pulse INTEGER,
            blood_sugar REAL,
            weight REAL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budget_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            family_id INTEGER,
            amount REAL,
            category TEXT,
            type TEXT,
            transaction_date TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budget_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            icon TEXT,
            type TEXT
        )
    ''')
    cursor.execute("SELECT COUNT(*) FROM budget_categories")
    if cursor.fetchone()[0] == 0:
        default_cats = [
            ('Еда', '🍔', 'expense'), ('Транспорт', '🚗', 'expense'), ('Жильё', '🏠', 'expense'),
            ('Здоровье', '💊', 'expense'), ('Развлечения', '🎬', 'expense'), ('Зарплата', '💰', 'income'),
            ('Подарки', '🎁', 'income'), ('Другое', '📦', 'expense')
        ]
        for name, icon, typ in default_cats:
            cursor.execute("INSERT INTO budget_categories (name, icon, type) VALUES (?, ?, ?)", (name, icon, typ))
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS premium_users (
            user_id INTEGER PRIMARY KEY,
            expiry_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS premium_codes (
            code TEXT PRIMARY KEY,
            days INTEGER,
            used_by INTEGER,
            used_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS family_codes (
            code TEXT PRIMARY KEY,
            senior_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# ---------- Пользователи ----------
def upsert_user(user_id, role, name=None, age=None, city=None, interests=None):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (user_id, role, name, age, city, interests)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            role=excluded.role,
            name=COALESCE(excluded.name, name),
            age=COALESCE(excluded.age, age),
            city=COALESCE(excluded.city, city),
            interests=COALESCE(excluded.interests, interests)
    ''', (user_id, role, name, age, city, interests))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, role, name, age, city, interests FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "role": row[1], "name": row[2], "age": row[3], "city": row[4], "interests": row[5]}
    return None

# ---------- Напоминания ----------
def add_reminder(user_id, typ, text, time_local):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO reminders (user_id, type, text, time_local)
        VALUES (?, ?, ?, ?)
    ''', (user_id, typ, text, time_local))
    conn.commit()
    conn.close()

def list_reminders(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, type, text, time_local, enabled FROM reminders WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "type": r[1], "text": r[2], "time_local": r[3], "enabled": bool(r[4])} for r in rows]

# ---------- Активность ----------
def log_activity(user_id, action):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO activity_log (user_id, action) VALUES (?, ?)", (user_id, action))
    conn.commit()
    conn.close()

def get_activity_summary(user_id, hours=24):
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT action FROM activity_log WHERE user_id = ? AND created_at > ?", (user_id, cutoff))
    rows = cursor.fetchall()
    conn.close()
    actions = [r[0] for r in rows]
    return {"talk": actions.count("talk"), "reminder_done": actions.count("reminder_done"), "sos": actions.count("sos")}

# ---------- Привязка родственников ----------
def add_relative_link(senior_id, relative_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO relatives (senior_id, relative_id) VALUES (?, ?)", (senior_id, relative_id))
    conn.commit()
    conn.close()

def get_relatives_for_senior(senior_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT relative_id FROM relatives WHERE senior_id = ?", (senior_id,))
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_family_id_for_user(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT senior_id FROM relatives WHERE relative_id = ?", (user_id,))
    row = cursor.fetchone()
    if row:
        family_id = row[0]
    else:
        cursor.execute("SELECT user_id FROM users WHERE user_id = ? AND role = 'senior'", (user_id,))
        if cursor.fetchone():
            family_id = user_id
        else:
            family_id = None
    conn.close()
    return family_id

# ---------- История чата ----------
def init_chat_history_table():
    pass

def save_message(user_id, role, content):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)", (user_id, role, content))
    conn.commit()
    conn.close()

def clear_chat_history(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_chat_history(user_id, limit=50):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?", (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

# ---------- Семейная лента ----------
def init_family_feed_table():
    pass

def add_to_family_feed(family_id, user_id, author_name, message, msg_type="message"):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO family_feed (family_id, user_id, author_name, message, type)
        VALUES (?, ?, ?, ?, ?)
    ''', (family_id, user_id, author_name, message, msg_type))
    conn.commit()
    conn.close()

def get_family_feed(family_id, limit=50):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT author_name, message, type, created_at FROM family_feed
        WHERE family_id = ? ORDER BY created_at DESC LIMIT ?
    ''', (family_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [{"author_name": r[0], "message": r[1], "type": r[2], "created_at": r[3]} for r in rows]

# ---------- Календарь ----------
def init_calendar_table():
    pass

def add_event(user_id, event_date, title, description=None, event_time=None, event_type="other", remind_before_days=1, target_user_id=None):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO calendar_events (user_id, event_date, event_time, title, description, event_type, remind_before_days, target_user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, event_date, event_time, title, description, event_type, remind_before_days, target_user_id))
    conn.commit()
    conn.close()

def get_events_for_user(user_id, from_date=None, limit=20):
    conn = get_db()
    cursor = conn.cursor()
    if from_date:
        cursor.execute('''
            SELECT id, event_date, event_time, title, description, event_type, remind_before_days, target_user_id
            FROM calendar_events WHERE user_id = ? AND event_date >= ? ORDER BY event_date ASC LIMIT ?
        ''', (user_id, from_date, limit))
    else:
        cursor.execute('''
            SELECT id, event_date, event_time, title, description, event_type, remind_before_days, target_user_id
            FROM calendar_events WHERE user_id = ? ORDER BY event_date ASC LIMIT ?
        ''', (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "date": r[1], "time": r[2], "title": r[3], "description": r[4], "type": r[5], "remind_before_days": r[6], "target_user_id": r[7]} for r in rows]

def get_events_by_date(date_str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, title FROM calendar_events WHERE event_date = ?
    ''', (date_str,))
    rows = cursor.fetchall()
    conn.close()
    return [{"user_id": r[0], "title": r[1]} for r in rows]

def delete_event(event_id, user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM calendar_events WHERE id = ? AND user_id = ?", (event_id, user_id))
    done = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return done

def get_birthdays_for_date(date_str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, target_user_id FROM calendar_events WHERE event_date = ? AND event_type = 'birthday'
    ''', (date_str,))
    rows = cursor.fetchall()
    conn.close()
    return [{"user_id": r[0], "target_user_id": r[1]} for r in rows]

# ---------- Игры ----------
def init_games_table():
    pass

def save_game_state(user_id, game_name, game_data):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO game_states (user_id, game_name, game_data, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    ''', (user_id, game_name, game_data))
    conn.commit()
    conn.close()

def get_game_state(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT game_name, game_data FROM game_states WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"game_name": row[0], "game_data": row[1]}
    return None

def clear_game_state(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM game_states WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# ---------- Медиа ----------
def init_media_table():
    pass

def save_media(family_id, user_id, author, file_id, media_type, caption=None):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO media (family_id, user_id, author, file_id, type, caption)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (family_id, user_id, author, file_id, media_type, caption))
    conn.commit()
    conn.close()

def get_family_media(family_id, limit=20):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT file_id, type, caption, author, date FROM media WHERE family_id = ? ORDER BY date DESC LIMIT ?
    ''', (family_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [{"file_id": r[0], "type": r[1], "caption": r[2], "author": r[3], "date": r[4]} for r in rows]

# ---------- Здоровье ----------
def init_health_table():
    pass

def add_health_record(user_id, record_date, record_time, systolic, diastolic, pulse, blood_sugar, weight, notes):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO health_records (user_id, record_date, record_time, systolic, diastolic, pulse, blood_sugar, weight, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, record_date, record_time, systolic, diastolic, pulse, blood_sugar, weight, notes))
    conn.commit()
    conn.close()

def get_health_records(user_id, days=30):
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT record_date, record_time, systolic, diastolic, pulse, blood_sugar, weight, notes
        FROM health_records WHERE user_id = ? AND record_date >= ? ORDER BY record_date DESC
    ''', (user_id, cutoff))
    rows = cursor.fetchall()
    conn.close()
    return [{"date": r[0], "time": r[1], "systolic": r[2], "diastolic": r[3], "pulse": r[4], "blood_sugar": r[5], "weight": r[6], "notes": r[7]} for r in rows]

def get_health_stats(user_id, days=30):
    records = get_health_records(user_id, days)
    if not records:
        return {"records_count": 0}
    count = len(records)
    systolic_vals = [r['systolic'] for r in records if r['systolic']]
    diastolic_vals = [r['diastolic'] for r in records if r['diastolic']]
    pulse_vals = [r['pulse'] for r in records if r['pulse']]
    sugar_vals = [r['blood_sugar'] for r in records if r['blood_sugar']]
    weight_vals = [r['weight'] for r in records if r['weight']]
    return {
        "records_count": count,
        "systolic_avg": sum(systolic_vals)/len(systolic_vals) if systolic_vals else 0,
        "diastolic_avg": sum(diastolic_vals)/len(diastolic_vals) if diastolic_vals else 0,
        "pulse_avg": sum(pulse_vals)/len(pulse_vals) if pulse_vals else 0,
        "sugar_avg": sum(sugar_vals)/len(sugar_vals) if sugar_vals else 0,
        "weight_avg": sum(weight_vals)/len(weight_vals) if weight_vals else 0,
    }

# ---------- Экспорт ----------
def export_chat_history(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT role, content, created_at FROM chat_history WHERE user_id = ? ORDER BY created_at", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp", "role", "content"])
    for r in rows:
        writer.writerow([r[2], r[0], r[1]])
    return output.getvalue()

def export_health_records(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT record_date, record_time, systolic, diastolic, pulse, blood_sugar, weight, notes
        FROM health_records WHERE user_id = ? ORDER BY record_date
    ''', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "time", "systolic", "diastolic", "pulse", "blood_sugar", "weight", "notes"])
    for r in rows:
        writer.writerow(r)
    return output.getvalue()

def export_family_feed(family_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT author_name, message, type, created_at FROM family_feed WHERE family_id = ? ORDER BY created_at
    ''', (family_id,))
    rows = cursor.fetchall()
    conn.close()
    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp", "author", "type", "message"])
    for r in rows:
        writer.writerow([r[3], r[0], r[2], r[1]])
    return output.getvalue()

# ---------- Бюджет ----------
def init_budget_table():
    pass

def add_transaction(user_id, family_id, amount, category, trans_type, transaction_date, description=None):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO budget_transactions (user_id, family_id, amount, category, type, transaction_date, description)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, family_id, amount, category, trans_type, transaction_date, description))
    conn.commit()
    conn.close()

def get_transactions(family_id, limit=50):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT amount, category, type, transaction_date, description FROM budget_transactions
        WHERE family_id = ? ORDER BY transaction_date DESC LIMIT ?
    ''', (family_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [{"amount": r[0], "category": r[1], "type": r[2], "date": r[3], "description": r[4]} for r in rows]

def get_budget_summary(family_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(amount) FROM budget_transactions WHERE family_id = ? AND type = 'income'", (family_id,))
    income = cursor.fetchone()[0] or 0.0
    cursor.execute("SELECT SUM(amount) FROM budget_transactions WHERE family_id = ? AND type = 'expense'", (family_id,))
    expense = cursor.fetchone()[0] or 0.0
    conn.close()
    return {"income": income, "expense": expense, "balance": income - expense}

def get_categories():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT name, icon, type FROM budget_categories")
    rows = cursor.fetchall()
    conn.close()
    return [{"name": r[0], "icon": r[1], "type": r[2]} for r in rows]

def get_category_breakdown(family_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT category, SUM(amount) FROM budget_transactions
        WHERE family_id = ? AND type = 'expense' GROUP BY category
    ''', (family_id,))
    rows = cursor.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}

# ---------- Премиум ----------
def init_premium_tables():
    pass

def is_premium(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT expiry_date FROM premium_users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return False
    expiry = datetime.fromisoformat(row[0])
    return expiry > datetime.now()

def add_premium_user(user_id, days=30):
    expiry = (datetime.now() + timedelta(days=days)).isoformat()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO premium_users (user_id, expiry_date) VALUES (?, ?)", (user_id, expiry))
    conn.commit()
    conn.close()

def get_premium_expiry(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT expiry_date FROM premium_users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return datetime.fromisoformat(row[0]) if row else None

def generate_code(days):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO premium_codes (code, days) VALUES (?, ?)", (code, days))
    conn.commit()
    conn.close()
    return code

def activate_code(code, user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT days FROM premium_codes WHERE code = ? AND used_by IS NULL", (code,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
    days = row[0]
    cursor.execute("UPDATE premium_codes SET used_by = ?, used_at = CURRENT_TIMESTAMP WHERE code = ?", (user_id, code))
    conn.commit()
    conn.close()
    add_premium_user(user_id, days)
    return True

# ---------- Язык ----------
def set_user_language(user_id, lang):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS user_language (user_id INTEGER PRIMARY KEY, lang TEXT)")
    cursor.execute("INSERT OR REPLACE INTO user_language (user_id, lang) VALUES (?, ?)", (user_id, lang))
    conn.commit()
    conn.close()

def get_user_language(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS user_language (user_id INTEGER PRIMARY KEY, lang TEXT)")
    cursor.execute("SELECT lang FROM user_language WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

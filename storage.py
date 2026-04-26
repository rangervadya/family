import sqlite3
import json
from datetime import datetime, date, timedelta
import random
import string

DB_PATH = "family_bot.db"

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Таблица пользователей
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
    
    # Таблица родственников (исправленная)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS relatives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            senior_id INTEGER NOT NULL,
            relative_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(senior_id, relative_id)
        )
    ''')
    
    # Таблица напоминаний
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT,
            text TEXT,
            time_local TEXT,
            enabled INTEGER DEFAULT 1
        )
    ''')
    
    # Таблица активности
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Остальные таблицы (история чатов, лента, календарь, игры, медиа, здоровье, бюджет, премиум)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT,
            content TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS family_feed (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER NOT NULL,
            author_id INTEGER,
            author_name TEXT,
            message TEXT,
            type TEXT DEFAULT 'message',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
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
        CREATE TABLE IF NOT EXISTS games_state (
            user_id INTEGER PRIMARY KEY,
            game_name TEXT,
            game_data TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER NOT NULL,
            author_id INTEGER,
            author_name TEXT,
            file_id TEXT,
            type TEXT,
            caption TEXT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS health_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
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
            user_id INTEGER NOT NULL,
            family_id INTEGER NOT NULL,
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
            name TEXT PRIMARY KEY,
            type TEXT,
            icon TEXT
        )
    ''')
    
    # Добавим стандартные категории, если их нет
    default_categories = [
        ('Зарплата', 'income', '💰'), ('Подарок', 'income', '🎁'), ('Возврат долга', 'income', '↩️'),
        ('Продукты', 'expense', '🍎'), ('Транспорт', 'expense', '🚗'), ('ЖКХ', 'expense', '🏠'), ('Здоровье', 'expense', '💊'),
        ('Развлечения', 'expense', '🎬'), ('Одежда', 'expense', '👕'), ('Прочее', 'expense', '📌')
    ]
    for cat in default_categories:
        cursor.execute("INSERT OR IGNORE INTO budget_categories (name, type, icon) VALUES (?, ?, ?)", cat)
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS premium_users (
            user_id INTEGER PRIMARY KEY,
            expiry_date TEXT,
            activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS premium_codes (
            code TEXT PRIMARY KEY,
            days INTEGER,
            used INTEGER DEFAULT 0,
            used_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

# ---------- РАБОТА С ПОЛЬЗОВАТЕЛЯМИ ----------
def upsert_user(user_id, role, name=None, age=None, city=None, interests=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (user_id, role, name, age, city, interests)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            role = excluded.role,
            name = COALESCE(excluded.name, name),
            age = COALESCE(excluded.age, age),
            city = COALESCE(excluded.city, city),
            interests = COALESCE(excluded.interests, interests)
    ''', (user_id, role, name, age, city, interests))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, role, name, age, city, interests FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "role": row[1], "name": row[2], "age": row[3], "city": row[4], "interests": row[5]}
    return None

# ---------- РОДСТВЕННИКИ ----------
def add_relative_link(senior_id, relative_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO relatives (senior_id, relative_id) VALUES (?, ?)", (senior_id, relative_id))
    conn.commit()
    conn.close()

def get_relatives_for_senior(senior_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT relative_id FROM relatives WHERE senior_id = ?", (senior_id,))
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]

def get_family_id_for_user(user_id):
    # Проверяем, является ли пользователь старшим
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT senior_id FROM relatives WHERE relative_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]  # family_id = senior_id
    # Если нет, то он может быть старшим
    user = get_user(user_id)
    if user and user.get('role') == 'senior':
        return user_id
    return None

# ---------- НАПОМИНАНИЯ ----------
def add_reminder(user_id, type_, text, time_local):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reminders (user_id, type, text, time_local) VALUES (?, ?, ?, ?)",
                   (user_id, type_, text, time_local))
    conn.commit()
    conn.close()

def list_reminders(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, type, text, time_local, enabled FROM reminders WHERE user_id = ? ORDER BY time_local", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "type": r[1], "text": r[2], "time_local": r[3], "enabled": r[4]} for r in rows]

# ---------- АКТИВНОСТЬ ----------
def log_activity(user_id, action):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO activity (user_id, action) VALUES (?, ?)", (user_id, action))
    conn.commit()
    conn.close()

def get_activity_summary(user_id, hours=24):
    since = datetime.now() - timedelta(hours=hours)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT action, COUNT(*) FROM activity WHERE user_id = ? AND created_at > ? GROUP BY action", (user_id, since))
    rows = cursor.fetchall()
    conn.close()
    summary = {"talk": 0, "reminder_done": 0, "sos": 0}
    for action, count in rows:
        if action in summary:
            summary[action] = count
    return summary

# ---------- ИСТОРИЯ ЧАТОВ ----------
def init_chat_history_table():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        role TEXT,
        content TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.close()

def save_message(user_id, role, content):
    conn = get_connection()
    conn.execute("INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)", (user_id, role, content))
    conn.commit()
    conn.close()

def clear_chat_history(user_id):
    conn = get_connection()
    conn.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def export_chat_history(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, role, content FROM chat_history WHERE user_id = ? ORDER BY timestamp", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    import io
    output = io.StringIO()
    output.write("timestamp,role,content\n")
    for row in rows:
        output.write(f"{row[0]},{row[1]},{row[2]}\n")
    return output.getvalue()

# ---------- СЕМЕЙНАЯ ЛЕНТА ----------
def init_family_feed_table():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS family_feed (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        family_id INTEGER NOT NULL,
        author_id INTEGER,
        author_name TEXT,
        message TEXT,
        type TEXT DEFAULT 'message',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.close()

def add_to_family_feed(family_id, author_id, author_name, message, type_="message"):
    conn = get_connection()
    conn.execute("INSERT INTO family_feed (family_id, author_id, author_name, message, type) VALUES (?, ?, ?, ?, ?)",
                 (family_id, author_id, author_name, message, type_))
    conn.commit()
    conn.close()

def get_family_feed(family_id, limit=50):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT author_name, message, created_at FROM family_feed WHERE family_id = ? ORDER BY created_at DESC LIMIT ?", (family_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [{"author_name": r[0], "message": r[1], "created_at": r[2]} for r in rows]

def export_family_feed(family_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT created_at, author_name, message FROM family_feed WHERE family_id = ? ORDER BY created_at", (family_id,))
    rows = cursor.fetchall()
    conn.close()
    import io
    output = io.StringIO()
    output.write("timestamp,author,message\n")
    for row in rows:
        output.write(f"{row[0]},{row[1]},{row[2]}\n")
    return output.getvalue()

# ---------- КАЛЕНДАРЬ ----------
def init_calendar_table():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS calendar_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        event_date TEXT,
        event_time TEXT,
        title TEXT,
        description TEXT,
        event_type TEXT,
        remind_before_days INTEGER DEFAULT 1,
        target_user_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.close()

def add_event(user_id, event_date, title, description=None, event_time=None, event_type="other", remind_before_days=1, target_user_id=None):
    conn = get_connection()
    conn.execute("""
        INSERT INTO calendar_events (user_id, event_date, event_time, title, description, event_type, remind_before_days, target_user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, event_date, event_time, title, description, event_type, remind_before_days, target_user_id))
    conn.commit()
    conn.close()

def get_events_for_user(user_id, from_date=None, limit=50):
    conn = get_connection()
    cursor = conn.cursor()
    if from_date:
        cursor.execute("SELECT id, event_date, event_time, title, description, event_type, remind_before_days FROM calendar_events WHERE user_id = ? AND event_date >= ? ORDER BY event_date LIMIT ?", (user_id, from_date, limit))
    else:
        cursor.execute("SELECT id, event_date, event_time, title, description, event_type, remind_before_days FROM calendar_events WHERE user_id = ? ORDER BY event_date LIMIT ?", (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "date": r[1], "time": r[2], "title": r[3], "description": r[4], "type": r[5], "remind_before_days": r[6]} for r in rows]

def get_events_by_date(date_str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, title, remind_before_days FROM calendar_events WHERE event_date = ?", (date_str,))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "user_id": r[1], "title": r[2], "remind_before_days": r[3]} for r in rows]

def delete_event(event_id, user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM calendar_events WHERE id = ? AND user_id = ?", (event_id, user_id))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0

def get_birthdays_for_date(date_str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, target_user_id, title FROM calendar_events WHERE event_type = 'birthday' AND event_date = ?", (date_str,))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "user_id": r[1], "target_user_id": r[2], "title": r[3]} for r in rows]

# ---------- ИГРЫ ----------
def init_games_table():
    conn = get_connection()
    conn.execute("CREATE TABLE IF NOT EXISTS games_state (user_id INTEGER PRIMARY KEY, game_name TEXT, game_data TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    conn.close()

def save_game_state(user_id, game_name, game_data):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO games_state (user_id, game_name, game_data) VALUES (?, ?, ?)", (user_id, game_name, game_data))
    conn.commit()
    conn.close()

def get_game_state(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT game_name, game_data FROM games_state WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"game_name": row[0], "game_data": row[1]}
    return None

def clear_game_state(user_id):
    conn = get_connection()
    conn.execute("DELETE FROM games_state WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# ---------- МЕДИА ----------
def init_media_table():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS media (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        family_id INTEGER NOT NULL,
        author_id INTEGER,
        author_name TEXT,
        file_id TEXT,
        type TEXT,
        caption TEXT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.close()

def save_media(family_id, author_id, author_name, file_id, type_, caption=None):
    conn = get_connection()
    conn.execute("INSERT INTO media (family_id, author_id, author_name, file_id, type, caption) VALUES (?, ?, ?, ?, ?, ?)",
                 (family_id, author_id, author_name, file_id, type_, caption))
    conn.commit()
    conn.close()

def get_family_media(family_id, limit=50):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT file_id, type, caption, date, author_name FROM media WHERE family_id = ? ORDER BY date DESC LIMIT ?", (family_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [{"file_id": r[0], "type": r[1], "caption": r[2], "date": r[3], "author": r[4]} for r in rows]

# ---------- ЯЗЫК ----------
def set_user_language(user_id, lang):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO users (user_id, role, name, age, city, interests) VALUES (?, ?, ?, ?, ?, ?)",
                 (user_id, None, None, None, None, None))
    # Для языка нужна отдельная таблица или поле. Создадим поле language в users
    conn.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'ru'")
    conn.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))
    conn.commit()
    conn.close()

def get_user_language(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 'ru'

# ---------- ЗДОРОВЬЕ ----------
def init_health_table():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS health_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        record_date TEXT,
        record_time TEXT,
        systolic INTEGER,
        diastolic INTEGER,
        pulse INTEGER,
        blood_sugar REAL,
        weight REAL,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.close()

def add_health_record(user_id, record_date, record_time=None, systolic=None, diastolic=None, pulse=None, blood_sugar=None, weight=None, notes=None):
    conn = get_connection()
    conn.execute("""
        INSERT INTO health_records (user_id, record_date, record_time, systolic, diastolic, pulse, blood_sugar, weight, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, record_date, record_time, systolic, diastolic, pulse, blood_sugar, weight, notes))
    conn.commit()
    conn.close()

def get_health_records(user_id, days=30):
    start_date = (date.today() - timedelta(days=days)).isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT record_date, record_time, systolic, diastolic, pulse, blood_sugar, weight FROM health_records WHERE user_id = ? AND record_date >= ? ORDER BY record_date DESC", (user_id, start_date))
    rows = cursor.fetchall()
    conn.close()
    return [{"date": r[0], "time": r[1], "systolic": r[2], "diastolic": r[3], "pulse": r[4], "blood_sugar": r[5], "weight": r[6]} for r in rows]

def get_health_stats(user_id, days=30):
    start_date = (date.today() - timedelta(days=days)).isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT AVG(systolic), AVG(diastolic), AVG(pulse), AVG(blood_sugar), AVG(weight), COUNT(*)
        FROM health_records
        WHERE user_id = ? AND record_date >= ?
    """, (user_id, start_date))
    row = cursor.fetchone()
    conn.close()
    if row and row[5] > 0:
        return {
            "systolic_avg": row[0] or 0,
            "diastolic_avg": row[1] or 0,
            "pulse_avg": row[2] or 0,
            "sugar_avg": row[3] or 0,
            "weight_avg": row[4] or 0,
            "records_count": row[5]
        }
    return {"records_count": 0}

def export_health_records(user_id):
    records = get_health_records(user_id, days=365*10)
    import io
    output = io.StringIO()
    output.write("date,time,systolic,diastolic,pulse,blood_sugar,weight\n")
    for r in records:
        output.write(f"{r['date']},{r['time'] or ''},{r['systolic'] or ''},{r['diastolic'] or ''},{r['pulse'] or ''},{r['blood_sugar'] or ''},{r['weight'] or ''}\n")
    return output.getvalue()

# ---------- БЮДЖЕТ ----------
def init_budget_table():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS budget_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        family_id INTEGER NOT NULL,
        amount REAL,
        category TEXT,
        type TEXT,
        transaction_date TEXT,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS budget_categories (
        name TEXT PRIMARY KEY,
        type TEXT,
        icon TEXT
    )''')
    default_categories = [
        ('Зарплата', 'income', '💰'), ('Подарок', 'income', '🎁'), ('Возврат долга', 'income', '↩️'),
        ('Продукты', 'expense', '🍎'), ('Транспорт', 'expense', '🚗'), ('ЖКХ', 'expense', '🏠'),
        ('Здоровье', 'expense', '💊'), ('Развлечения', 'expense', '🎬'), ('Одежда', 'expense', '👕'),
        ('Прочее', 'expense', '📌')
    ]
    for cat in default_categories:
        conn.execute("INSERT OR IGNORE INTO budget_categories (name, type, icon) VALUES (?, ?, ?)", cat)
    conn.commit()
    conn.close()

def add_transaction(user_id, family_id, amount, category, type_, transaction_date, description=None):
    conn = get_connection()
    conn.execute("""
        INSERT INTO budget_transactions (user_id, family_id, amount, category, type, transaction_date, description)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, family_id, amount, category, type_, transaction_date, description))
    conn.commit()
    conn.close()

def get_transactions(family_id, limit=100):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT transaction_date, category, amount, type, description FROM budget_transactions WHERE family_id = ? ORDER BY transaction_date DESC LIMIT ?", (family_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [{"date": r[0], "category": r[1], "amount": r[2], "type": r[3], "description": r[4]} for r in rows]

def get_budget_summary(family_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(amount) FROM budget_transactions WHERE family_id = ? AND type = 'income'", (family_id,))
    income = cursor.fetchone()[0] or 0.0
    cursor.execute("SELECT SUM(amount) FROM budget_transactions WHERE family_id = ? AND type = 'expense'", (family_id,))
    expense = cursor.fetchone()[0] or 0.0
    conn.close()
    return {"income": income, "expense": expense, "balance": income - expense}

def get_categories():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, type, icon FROM budget_categories")
    rows = cursor.fetchall()
    conn.close()
    return [{"name": r[0], "type": r[1], "icon": r[2]} for r in rows]

def get_category_breakdown(family_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT category, SUM(amount)
        FROM budget_transactions
        WHERE family_id = ? AND type = 'expense'
        GROUP BY category
    """, (family_id,))
    rows = cursor.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}

# ---------- ПРЕМИУМ ----------
def init_premium_tables():
    conn = get_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS premium_users (
        user_id INTEGER PRIMARY KEY,
        expiry_date TEXT,
        activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS premium_codes (
        code TEXT PRIMARY KEY,
        days INTEGER,
        used INTEGER DEFAULT 0,
        used_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

def is_premium(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT expiry_date FROM premium_users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        expiry = datetime.fromisoformat(row[0])
        if expiry > datetime.now():
            return True
    return False

def add_premium_user(user_id, days=30):
    expiry = (datetime.now() + timedelta(days=days)).isoformat()
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO premium_users (user_id, expiry_date) VALUES (?, ?)", (user_id, expiry))
    conn.commit()
    conn.close()

def generate_code(days):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    conn = get_connection()
    conn.execute("INSERT INTO premium_codes (code, days, used) VALUES (?, ?, 0)", (code, days))
    conn.commit()
    conn.close()
    return code

def activate_code(code, user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT days, used FROM premium_codes WHERE code = ?", (code,))
    row = cursor.fetchone()
    if row and row[1] == 0:
        days = row[0]
        add_premium_user(user_id, days)
        cursor.execute("UPDATE premium_codes SET used = 1, used_by = ? WHERE code = ?", (user_id, code))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def get_premium_expiry(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT expiry_date FROM premium_users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return datetime.fromisoformat(row[0])
    return None

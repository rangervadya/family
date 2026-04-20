import sqlite3
import csv
import io
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
    cursor.execute("PRAGMA table_info(calendar_events)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'target_user_id' not in columns:
        cursor.execute("ALTER TABLE calendar_events ADD COLUMN target_user_id INTEGER")
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
            file_type TEXT NOT NULL,  -- 'photo', 'video'
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
    cursor.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'language' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'ru'")
    cursor.execute("UPDATE users SET language = ? WHERE telegram_id = ?", (lang, telegram_id))
    conn.commit()
    conn.close()

def get_user_language(telegram_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'language' not in columns:
        conn.close()
        return 'ru'
    cursor.execute("SELECT language FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row and row[0] else 'ru'


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
        "id": r[0],
        "date": r[1],
        "time": r[2],
        "title": r[3],
        "description": r[4],
        "type": r[5],
        "remind_before_days": r[6],
        "target_user_id": r[7]
    } for r in rows]

def get_event_by_id(event_id: int):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, user_id, event_date, event_time, title, description, event_type, remind_before_days, target_user_id
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
            "remind_before_days": row[7],
            "target_user_id": row[8]
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
        "id": r[0],
        "user_id": r[1],
        "date": r[2],
        "time": r[3],
        "title": r[4],
        "description": r[5],
        "type": r[6],
        "remind_before_days": r[7],
        "target_user_id": r[8]
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


# ---------- Аналитика и статистика ----------
def get_user_stats(user_id: int, days: int = 7) -> dict:
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT COUNT(*) FROM activities
        WHERE telegram_id = ? AND action = 'talk' AND created_at > datetime('now', '-' || ? || ' days')
    """, (user_id, days))
    talks = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT COUNT(*) FROM activities
        WHERE telegram_id = ? AND action = 'reminder_done' AND created_at > datetime('now', '-' || ? || ' days')
    """, (user_id, days))
    reminders_done = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT COUNT(*) FROM activities
        WHERE telegram_id = ? AND action = 'sos' AND created_at > datetime('now', '-' || ? || ' days')
    """, (user_id, days))
    sos_count = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT COUNT(*) FROM activities
        WHERE telegram_id = ? AND action = 'voice' AND created_at > datetime('now', '-' || ? || ' days')
    """, (user_id, days))
    voice_count = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT COUNT(*) FROM activities
        WHERE telegram_id = ? AND created_at > datetime('now', '-' || ? || ' days')
    """, (user_id, days))
    total_activities = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        "talks": talks,
        "reminders_done": reminders_done,
        "sos": sos_count,
        "voice": voice_count,
        "total": total_activities,
        "days": days
    }

def get_family_stats(family_id: int, days: int = 7) -> list:
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT relative_id FROM relatives WHERE senior_id = ?", (family_id,))
    relatives = [row[0] for row in cursor.fetchall()]
    if family_id not in relatives:
        relatives.append(family_id)
    
    stats = []
    for member_id in relatives:
        cursor.execute("SELECT name FROM users WHERE telegram_id = ?", (member_id,))
        name_row = cursor.fetchone()
        member_name = name_row[0] if name_row else f"User_{member_id}"
        
        member_stats = get_user_stats(member_id, days)
        member_stats["user_id"] = member_id
        member_stats["name"] = member_name
        stats.append(member_stats)
    
    conn.close()
    return stats

def get_reminder_completion_rate(user_id: int, days: int = 30) -> dict:
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT COUNT(*) FROM reminders
        WHERE telegram_id = ? AND enabled = 1
    """, (user_id,))
    total_reminders = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT COUNT(*) FROM activities
        WHERE telegram_id = ? AND action = 'reminder_done' AND created_at > datetime('now', '-' || ? || ' days')
    """, (user_id, days))
    completed = cursor.fetchone()[0]
    
    conn.close()
    
    if total_reminders == 0:
        rate = 100.0
    else:
        rate = (completed / (total_reminders * days)) * 100 if total_reminders > 0 else 0
    
    return {
        "total_reminders": total_reminders,
        "completed": completed,
        "completion_rate": min(100, rate),
        "days": days
    }

def generate_health_report(user_id: int, days: int = 7) -> str:
    stats = get_user_stats(user_id, days)
    reminder_stats = get_reminder_completion_rate(user_id, days)
    
    report = f"📊 *Отчёт о здоровье за {days} дней*\n\n"
    report += f"💬 Разговоров с ботом: {stats['talks']}\n"
    report += f"💊 Приёмов лекарств (выполнено): {stats['reminders_done']}\n"
    if reminder_stats['total_reminders'] > 0:
        report += f"📈 Процент выполнения: {reminder_stats['completion_rate']:.1f}%\n"
    report += f"🆘 Нажатий SOS: {stats['sos']}\n"
    if stats['voice'] > 0:
        report += f"🎤 Голосовых сообщений: {stats['voice']}\n"
    report += f"\n🏆 *Всего активностей:* {stats['total']}\n"
    
    if reminder_stats['completion_rate'] < 50:
        report += "\n⚠️ *Рекомендация:* старайтесь не пропускать приём лекарств!"
    if stats['talks'] == 0:
        report += "\n💡 *Совет:* общайтесь с ботом – это поднимает настроение!"
    
    return report

def generate_family_report(family_id: int, days: int = 7) -> str:
    members_stats = get_family_stats(family_id, days)
    
    report = f"👨‍👩‍👧 *Семейный отчёт за {days} дней*\n\n"
    total_talks = 0
    total_reminders = 0
    total_sos = 0
    
    for m in members_stats:
        report += f"👤 *{m['name']}*\n"
        report += f"   💬 Разговоров: {m['talks']}\n"
        report += f"   💊 Приёмов лекарств: {m['reminders_done']}\n"
        report += f"   🆘 SOS: {m['sos']}\n\n"
        total_talks += m['talks']
        total_reminders += m['reminders_done']
        total_sos += m['sos']
    
    report += f"📊 *Общая активность семьи:*\n"
    report += f"   💬 Всего диалогов: {total_talks}\n"
    report += f"   💊 Всего приёмов: {total_reminders}\n"
    report += f"   🆘 Всего SOS: {total_sos}\n"
    
    return report


# ---------- Игры и викторины ----------
def save_game_state(user_id: int, game_name: str, game_data: str):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO games_state (user_id, game_name, game_data, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    """, (user_id, game_name, game_data))
    conn.commit()
    conn.close()

def get_game_state(user_id: int) -> dict:
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


# ---------- Медиафайлы и альбомы ----------
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
            "id": row[0],
            "author": row[1],
            "type": row[2],
            "file_id": row[3],
            "caption": row[4],
            "date": row[5]
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


# ---------- Экспорт данных в CSV ----------
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
    writer.writerow(["Дата", "Время", "Давление (верх/низ)", "Пульс", "Сахар", "Вес", "Заметки"])
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

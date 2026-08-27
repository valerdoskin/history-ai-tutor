"""
SQLite база данных History AI Tutor.

Хранит: пользователей, прогресс, геймификацию (XP, streak, достижения, ранги),
историю диалогов, результаты практики ОГЭ/ЕГЭ.
"""

import json
import os
import sqlite3
import time
from contextlib import contextmanager

import config


class Database:
    def __init__(self, db_path=None):
        self.db_path = db_path or config.DB_PATH
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self):
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    level INTEGER DEFAULT 1,
                    xp INTEGER DEFAULT 0,
                    streak INTEGER DEFAULT 0,
                    last_active INTEGER DEFAULT 0,
                    rank TEXT DEFAULT 'Новичок',
                    created_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS progress (
                    user_id INTEGER,
                    book_id TEXT,
                    chapter_number TEXT,
                    paragraph_title TEXT,
                    status TEXT DEFAULT 'not_started',
                    score REAL DEFAULT 0,
                    attempts INTEGER DEFAULT 0,
                    updated_at INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, book_id, chapter_number, paragraph_title)
                );

                CREATE TABLE IF NOT EXISTS achievements (
                    user_id INTEGER,
                    achievement_id TEXT,
                    unlocked_at INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, achievement_id)
                );

                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    role TEXT,
                    content TEXT,
                    created_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS exam_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    exam_type TEXT,
                    question TEXT,
                    user_answer TEXT,
                    correct_answer TEXT,
                    is_correct INTEGER,
                    topic TEXT,
                    created_at INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS weak_topics (
                    user_id INTEGER,
                    topic TEXT,
                    error_count INTEGER DEFAULT 0,
                    last_seen INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, topic)
                );
                """
            )

    # ============================================================
    # Пользователи
    # ============================================================
    def get_or_create_user(self, user_id, username=None, first_name=None):
        now = int(time.time())
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
            if row:
                return dict(row)
            conn.execute(
                "INSERT INTO users (user_id, username, first_name, created_at) VALUES (?,?,?,?)",
                (user_id, username, first_name, now),
            )
            return {
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "level": 1,
                "xp": 0,
                "streak": 0,
                "rank": "Новичок",
                "created_at": now,
            }

    def update_user(self, user_id, **kwargs):
        allowed = {"username", "first_name", "level", "xp", "streak", "rank", "last_active"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [user_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE users SET {sets} WHERE user_id=?", values)

    def add_xp(self, user_id, amount):
        """Добавляет XP и обновляет уровень."""
        with self._conn() as conn:
            row = conn.execute("SELECT xp, level FROM users WHERE user_id=?", (user_id,)).fetchone()
            if not row:
                return
            new_xp = row["xp"] + amount
            # Уровень растёт каждые 100 XP
            new_level = 1 + new_xp // 100
            conn.execute(
                "UPDATE users SET xp=?, level=?, last_active=? WHERE user_id=?",
                (new_xp, new_level, int(time.time()), user_id),
            )
            return new_level

    def update_streak(self, user_id):
        """Обновляет streak (серия дней)."""
        now = int(time.time())
        day = 86400
        with self._conn() as conn:
            row = conn.execute("SELECT streak, last_active FROM users WHERE user_id=?", (user_id,)).fetchone()
            if not row:
                return 0
            last = row["last_active"]
            if last == 0:
                new_streak = 1
            elif now - last < day * 2:  # вчера или сегодня
                new_streak = row["streak"] + 1 if now - last >= day else row["streak"]
                if now - last >= day:
                    new_streak = row["streak"] + 1
                else:
                    new_streak = row["streak"]
            else:
                new_streak = 1
            conn.execute("UPDATE users SET streak=?, last_active=? WHERE user_id=?", (new_streak, now, user_id))
            return new_streak

    # ============================================================
    # Прогресс
    # ============================================================
    def update_progress(self, user_id, book_id, chapter_number, paragraph_title, status, score=0):
        now = int(time.time())
        with self._conn() as conn:
            row = conn.execute(
                "SELECT attempts FROM progress WHERE user_id=? AND book_id=? AND chapter_number=? AND paragraph_title=?",
                (user_id, book_id, chapter_number, paragraph_title),
            ).fetchone()
            attempts = (row["attempts"] if row else 0) + 1
            conn.execute(
                """
                INSERT INTO progress (user_id, book_id, chapter_number, paragraph_title, status, score, attempts, updated_at)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(user_id, book_id, chapter_number, paragraph_title)
                DO UPDATE SET status=excluded.status, score=excluded.score, attempts=excluded.attempts, updated_at=excluded.updated_at
                """,
                (user_id, book_id, chapter_number, paragraph_title, status, score, attempts, now),
            )

    def get_progress(self, user_id):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM progress WHERE user_id=? ORDER BY updated_at DESC", (user_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ============================================================
    # Достижения
    # ============================================================
    def unlock_achievement(self, user_id, achievement_id):
        now = int(time.time())
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO achievements (user_id, achievement_id, unlocked_at) VALUES (?,?,?)",
                (user_id, achievement_id, now),
            )

    def get_achievements(self, user_id):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT achievement_id FROM achievements WHERE user_id=?", (user_id,)
            ).fetchall()
            return [r["achievement_id"] for r in rows]

    # ============================================================
    # История диалогов
    # ============================================================
    def add_message(self, user_id, role, content):
        now = int(time.time())
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO chat_history (user_id, role, content, created_at) VALUES (?,?,?,?)",
                (user_id, role, content, now),
            )

    def get_history(self, user_id, limit=20):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content FROM chat_history WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    # ============================================================
    # Результаты практики
    # ============================================================
    def add_exam_result(self, user_id, exam_type, question, user_answer, correct_answer, is_correct, topic):
        now = int(time.time())
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO exam_results (user_id, exam_type, question, user_answer, correct_answer, is_correct, topic, created_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (user_id, exam_type, question, user_answer, correct_answer, int(is_correct), topic, now),
            )
            # Обновляем слабые темы
            if not is_correct:
                conn.execute(
                    """
                    INSERT INTO weak_topics (user_id, topic, error_count, last_seen)
                    VALUES (?,?,1,?)
                    ON CONFLICT(user_id, topic)
                    DO UPDATE SET error_count=error_count+1, last_seen=excluded.last_seen
                    """,
                    (user_id, topic, now),
                )

    def get_weak_topics(self, user_id, limit=10):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT topic, error_count FROM weak_topics WHERE user_id=? ORDER BY error_count DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_stats(self, user_id):
        with self._conn() as conn:
            user = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
            total_q = conn.execute(
                "SELECT COUNT(*) as c FROM exam_results WHERE user_id=?", (user_id,)
            ).fetchone()["c"]
            correct_q = conn.execute(
                "SELECT COUNT(*) as c FROM exam_results WHERE user_id=? AND is_correct=1", (user_id,)
            ).fetchone()["c"]
            return {
                "user": dict(user) if user else None,
                "total_questions": total_q,
                "correct_questions": correct_q,
                "accuracy": round(correct_q / total_q * 100, 1) if total_q else 0,
            }


# Глобальный экземпляр
db = Database()

"""User database for Telegram Bot."""

from __future__ import annotations

import aiosqlite
import json
import logging
from typing import Any
from typing import Any, Optional

from config.settings import get_settings
from src.models.user import User, UserSubscription, ChatMessage

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    is_active BOOLEAN DEFAULT 0,
    is_admin BOOLEAN DEFAULT 0,
    language TEXT DEFAULT 'zh',
    subscribed_exchanges TEXT,
    min_alert_threshold REAL DEFAULT 500000,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    source_type TEXT,
    enabled BOOLEAN DEFAULT 1,
    threshold REAL,
    FOREIGN KEY (user_id) REFERENCES users(telegram_id)
);

CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    role TEXT,
    content TEXT,
    timestamp INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(telegram_id)
);

CREATE INDEX IF NOT EXISTS idx_chat_history_user ON chat_history(user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_user_subscriptions_user ON user_subscriptions(user_id);
"""


class UserDatabase:
    """Database for Telegram user management."""

    def __init__(self) -> None:
        self._db_path = str(get_settings().abs_user_db_path)
        self._conn: Optional[aiosqlite.Connection] = None

    async def start(self) -> None:
        """Initialize database connection."""
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()
        logger.info("User database initialized at %s", self._db_path)

    async def stop(self) -> None:
        """Close database connection."""
        if self._conn:
            await self._conn.close()

    async def get_or_create_user(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        language: str = "zh",
    ) -> User:
        """Create a new user or return existing one."""
        async with self._conn.cursor() as cursor:
            await cursor.execute(
                """
                INSERT OR IGNORE INTO users 
                (telegram_id, username, first_name, last_name, language)
                VALUES (?, ?, ?, ?, ?)
                """,
                (telegram_id, username, first_name, last_name, language),
            )
            await self._conn.commit()
        return await self.get_user(telegram_id)

    async def get_user(self, telegram_id: int) -> Optional[User]:
        """Get user by telegram ID."""
        async with self._conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return self._row_to_user(row)

    async def update_user_info(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        language: Optional[str] = None,
    ) -> None:
        """Update basic user info."""
        updates = []
        params = []
        if username is not None:
            updates.append("username = ?")
            params.append(username)
        if first_name is not None:
            updates.append("first_name = ?")
            params.append(first_name)
        if last_name is not None:
            updates.append("last_name = ?")
            params.append(last_name)
        if language is not None:
            updates.append("language = ?")
            params.append(language)

        if updates:
            params.append(telegram_id)
            await self._conn.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE telegram_id = ?",
                params,
            )
            await self._conn.commit()

    async def activate_user(self, telegram_id: int) -> None:
        """Activate user (admin approval)."""
        await self._conn.execute(
            "UPDATE users SET is_active = 1 WHERE telegram_id = ?",
            (telegram_id,),
        )
        await self._conn.commit()

    async def deactivate_user(self, telegram_id: int) -> None:
        """Deactivate user."""
        await self._conn.execute(
            "UPDATE users SET is_active = 0 WHERE telegram_id = ?",
            (telegram_id,),
        )
        await self._conn.commit()

    async def update_user_subscription(
        self,
        telegram_id: int,
        subscribed_exchanges:Optional[ list[str]] = None,
        min_alert_threshold:Optional[ float] = None,
    ) -> None:
        """Update user subscription settings."""
        updates = []
        params = []

        if subscribed_exchanges is not None:
            updates.append("subscribed_exchanges = ?")
            params.append(json.dumps(subscribed_exchanges))

        if min_alert_threshold is not None:
            updates.append("min_alert_threshold = ?")
            params.append(min_alert_threshold)

        if updates:
            params.append(telegram_id)
            await self._conn.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE telegram_id = ?",
                params,
            )
            await self._conn.commit()

    async def update_last_active(self, telegram_id: int) -> None:
        """Update user's last active timestamp."""
        await self._conn.execute(
            "UPDATE users SET last_active_at = strftime('%s', 'now') WHERE telegram_id = ?",
            (telegram_id,),
        )
        await self._conn.commit()

    async def get_all_active_users(self) -> list[User]:
        """Get all active users."""
        async with self._conn.execute(
            "SELECT * FROM users WHERE is_active = 1"
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_user(row) for row in rows]

    async def add_chat_message(
        self,
        user_id: int,
        role: str,
        content: str,
    ) -> None:
        """Add message to chat history."""
        await self._conn.execute(
            """INSERT INTO chat_history (user_id, role, content, timestamp)
               VALUES (?, ?, ?, strftime('%s', 'now'))""",
            (user_id, role, content),
        )
        await self._conn.commit()

    async def get_chat_history(
        self,
        user_id: int,
        limit: int = 10,
    ) -> list[ChatMessage]:
        """Get recent chat history for a user."""
        async with self._conn.execute(
            """SELECT * FROM chat_history
               WHERE user_id = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                ChatMessage(
                    id=row["id"],
                    user_id=row["user_id"],
                    role=row["role"],
                    content=row["content"],
                    timestamp=row["timestamp"],
                )
                for row in reversed(rows)
            ]

    def _row_to_user(self, row: aiosqlite.Row) -> User:
        """Convert database row to User model."""
        return User(
            telegram_id=row["telegram_id"],
            username=row["username"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            is_active=bool(row["is_active"]),
            is_admin=bool(row["is_admin"]),
            subscribed_exchanges=json.loads(row["subscribed_exchanges"] or "[]"),
            min_alert_threshold=row["min_alert_threshold"],
            created_at=row["created_at"],
            last_active_at=row["last_active_at"],
        )

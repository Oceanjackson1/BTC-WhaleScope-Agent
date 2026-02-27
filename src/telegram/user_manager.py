"""User manager for Telegram Bot."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from config.settings import get_settings
from src.models.user import User

if TYPE_CHECKING:
    from src.storage.user_database import UserDatabase

logger = logging.getLogger(__name__)


class UserManager:
    """Manages Telegram user lifecycle and permissions."""

    def __init__(self, db: "UserDatabase") -> None:
        self.db = db
        self.settings = get_settings()

    async def register_user(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        language: str = "zh",
    ) -> User:
        """Register a new user or return existing one."""
        user = await self.db.get_or_create_user(
            telegram_id, username, first_name, last_name, language
        )
        logger.info(
            "User registered: %d (%s) - Active: %s, Admin: %s",
            user.telegram_id,
            user.username or "N/A",
            user.is_active,
            user.is_admin,
        )
        return user

    async def approve_user(self, telegram_id: int, approver_id: int) -> bool:
        """Approve a user (admin only)."""
        if not await self.is_admin(approver_id):
            logger.warning(
                "Non-admin user %d attempted to approve user %d", approver_id, telegram_id
            )
            return False

        await self.db.activate_user(telegram_id)
        logger.info("User %d approved by admin %d", telegram_id, approver_id)
        return True

    async def revoke_user(self, telegram_id: int, revoker_id: int) -> bool:
        """Revoke a user (admin only)."""
        if not await self.is_admin(revoker_id):
            logger.warning(
                "Non-admin user %d attempted to revoke user %d", revoker_id, telegram_id
            )
            return False

        await self.db.deactivate_user(telegram_id)
        logger.info("User %d revoked by admin %d", telegram_id, revoker_id)
        return True

    async def is_admin(self, telegram_id: int) -> bool:
        """Check if user is admin."""
        user = await self.db.get_user(telegram_id)
        if not user:
            return False
        return user.is_admin or telegram_id in self.settings.tg_admin_id_list

    async def is_active(self, telegram_id: int) -> bool:
        """Check if user is active."""
        user = await self.db.get_user(telegram_id)
        if not user:
            return False
        return user.is_active

    async def update_subscription(
        self,
        telegram_id: int,
        subscribed_exchanges: Optional[list[str]] = None,
        min_alert_threshold: Optional[float] = None,
        language: Optional[str] = None,
    ) -> None:
        """Update user subscription configuration."""
        if subscribed_exchanges is not None or min_alert_threshold is not None or language is not None:
            # Note: We store language along with subscription info for simplicity here,
            # but User model treats it as user info.
            await self.db.update_user_info(
                telegram_id,
                language=language
            )

        if subscribed_exchanges is not None:
            await self.db._conn.execute(
                "UPDATE users SET subscribed_exchanges = ? WHERE telegram_id = ?",
                (json.dumps(subscribed_exchanges), telegram_id),
            )
            await self.db._conn.commit()

        if min_alert_threshold is not None:
            await self.db._conn.execute(
                "UPDATE users SET min_alert_threshold = ? WHERE telegram_id = ?",
                (min_alert_threshold, telegram_id),
            )
            await self.db._conn.commit()

        logger.info(
            "Subscription updated for user %d: exchanges=%s, threshold=%s, language=%s",
            telegram_id,
            subscribed_exchanges,
            min_alert_threshold,
            language,
        )

    async def get_active_users_for_alert(
        self, exchange: str, amount_usd: float
    ) -> list[User]:
        """Get all active users who should receive this alert."""
        all_users = await self.db.get_all_active_users()
        return [
            user
            for user in all_users
            if user.is_subscribed_to_exchange(exchange)
            and user.should_receive_alert(amount_usd)
        ]

    async def update_activity(self, telegram_id: int) -> None:
        """Update user's last activity timestamp."""
        await self.db.update_last_active(telegram_id)

    async def get_user(self, telegram_id: int) ->Optional[ User]:
        """Get user by ID."""
        return await self.db.get_user(telegram_id)

    async def get_all_users(self) -> list[User]:
        """Get all users."""
        async with self.db._conn.execute("SELECT * FROM users") as cursor:
            rows = await cursor.fetchall()
            return [self.db._row_to_user(row) for row in rows]

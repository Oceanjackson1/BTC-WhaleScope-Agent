"""User model for Telegram Bot."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    pass


class User(BaseModel):
    """Telegram user model."""

    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_active: bool = False
    is_admin: bool = False
    language: str = "zh"
    subscribed_exchanges: list[str] = Field(default_factory=list)
    min_alert_threshold: float = 500_000
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_active_at: Optional[datetime] = None

    def is_subscribed_to_exchange(self, exchange: str) -> bool:
        """Check if user is subscribed to a specific exchange."""
        if not self.subscribed_exchanges:
            return True
        return exchange in self.subscribed_exchanges

    def should_receive_alert(self, amount_usd: float) -> bool:
        """Check if user should receive an alert based on threshold."""
        return amount_usd >= self.min_alert_threshold


class UserSubscription(BaseModel):
    """User subscription configuration."""

    id: Optional[int] = None
    user_id: int
    source_type: str  # cex_futures, cex_spot, onchain
    enabled: bool = True
    threshold: Optional[float] = None


class ChatMessage(BaseModel):
    """Chat history message."""

    id:Optional[ int] = None
    user_id: int
    role: str  # user | assistant
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

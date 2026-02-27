"""Push dispatcher for Telegram Bot."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from telegram import Bot

from src.models.user import User
from src.models.whale_order import WhaleOrder

logger = logging.getLogger(__name__)


class PushDispatcher:
    """Manages pushing whale order alerts to Telegram users."""

    def __init__(self, bot: "Bot") -> None:
        self.bot = bot
        self._message_queue: asyncio.Optional[Queue] = None
        self._worker_task: asyncio.Optional[Task] = None
        self._running = False

    async def start(self) -> None:
        """Start the push dispatcher."""
        self._message_queue = asyncio.Queue()
        self._worker_task = asyncio.create_task(self._worker_loop())
        self._running = True
        logger.info("Push dispatcher started")

    async def stop(self) -> None:
        """Stop the push dispatcher."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("Push dispatcher stopped")

    async def push_alert(
        self,
        users: list[User],
        order: WhaleOrder,
        ai_analysis:Optional[ dict] = None,
    ) -> None:
        """Push alert to multiple users."""
        for user in users:
            await self._message_queue.put((user, order, ai_analysis))
        logger.debug("Queued alert for %d users", len(users))

    async def _worker_loop(self) -> None:
        """Worker loop for sending messages."""
        while self._running:
            try:
                user, order, ai_analysis = await asyncio.wait_for(
                    self._message_queue.get(), timeout=1.0
                )
                await self._send_alert(user, order, ai_analysis)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("Error in worker loop: %s", e, exc_info=True)

    async def _send_alert(self, user: User, order: WhaleOrder, ai_analysis:Optional[ dict] = None) -> None:
        """Send alert to a single user."""
        try:
            # Build alert message
            message = self._format_alert_message(order, ai_analysis)
            await self.bot.send_message(
                chat_id=user.telegram_id,
                text=message,
                parse_mode="Markdown",
            )
            logger.debug(
                "Alert sent to user %d for order %s",
                user.telegram_id,
                order.id,
            )
        except Exception as e:
            logger.error(
                "Failed to send alert to user %d: %s",
                user.telegram_id,
                e,
            )

    def _format_alert_message(self, order: WhaleOrder, ai_analysis:Optional[ dict] = None) -> str:
        """Format alert message for Telegram."""
        emoji = "🟢" if order.side.value == "buy" else "🔴"
        direction = "买入" if order.side.value == "buy" else "卖出"

        message = f"""
*{emoji} 鲸鱼大单告警*

📊 **交易所:** {order.exchange}
💱 **交易对:** {order.symbol}
{emoji} **方向:** {direction}
💰 **金额:** ${order.amount_usd:,.0f}
📈 **价格:** ${order.price:,.2f}
📝 **类型:** {order.order_type.value}
⏰ **时间:** {datetime.fromtimestamp(order.timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')}"""

        # Add AI analysis if available
        if ai_analysis and ai_analysis.get("analysis"):
            signal_emoji = {
                "bullish": "📈",
                "bearish": "📉",
                "neutral": "➡️",
            }.get(ai_analysis.get("signal", "neutral"), "➡️")

            message += f"""

---
*🤖 AI 分析*

📊 **分析:** {ai_analysis.get('analysis', '分析中...')}
🎯 **交易信号:** {signal_emoji} {ai_analysis.get('signal', 'neutral').upper()}
🎲 **置信度:** {ai_analysis.get('confidence', 0)}/100
⚠️ **风险等级:** {ai_analysis.get('risk_level', 'medium').upper()}
💡 **建议:** {ai_analysis.get('suggestion', '建议观望')}"""

        return message.strip()

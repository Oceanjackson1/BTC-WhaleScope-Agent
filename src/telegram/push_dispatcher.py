"""Push dispatcher for Telegram Bot."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
import time
from typing import TYPE_CHECKING, Any, Optional

import httpx

if TYPE_CHECKING:
    from telegram import Bot

from src.models.user import User
from src.models.whale_order import WhaleOrder

logger = logging.getLogger(__name__)


class PushDispatcher:
    """Manages pushing whale order alerts to Telegram users."""

    def __init__(self, bot: "Bot") -> None:
        self.bot = bot
        self._message_queue: Optional[asyncio.Queue] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._webhook_client: Optional[httpx.AsyncClient] = None
        self._running = False

    async def start(self) -> None:
        """Start the push dispatcher."""
        self._message_queue = asyncio.Queue()
        self._webhook_client = httpx.AsyncClient(timeout=httpx.Timeout(8.0))
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
        if self._webhook_client:
            await self._webhook_client.aclose()
        logger.info("Push dispatcher stopped")

    async def push_alert(
        self,
        users: list[User],
        order: WhaleOrder,
        ai_analysis: Optional[dict] = None,
    ) -> None:
        """Push alert to multiple users."""
        dedup_targets: set[tuple[str, str]] = set()
        for user in users:
            if not user.alerts_enabled:
                continue
            key = self._target_key(user)
            if key in dedup_targets:
                continue
            dedup_targets.add(key)
            await self._message_queue.put((user, order, ai_analysis))
        logger.debug("Queued alert for %d targets", len(dedup_targets))

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

    async def _send_alert(
        self,
        user: User,
        order: WhaleOrder,
        ai_analysis: Optional[dict] = None,
    ) -> None:
        """Send alert to a single user."""
        try:
            message = self._format_alert_message(order, ai_analysis)
            channel = (user.push_channel or "dm").lower()

            if channel == "group":
                chat_id = user.push_group_chat_id or user.telegram_id
                await self.bot.send_message(chat_id=chat_id, text=message)
                logger.debug("Alert sent to group/chat %s for user %d", chat_id, user.telegram_id)
                return

            if channel == "webhook":
                webhook_url = (user.custom_webhook_url or "").strip()
                if webhook_url:
                    await self._send_webhook(user, webhook_url, order, ai_analysis)
                    return
                logger.warning("User %d selected webhook but URL is empty; fallback to DM", user.telegram_id)

            await self.bot.send_message(chat_id=user.telegram_id, text=message)
            logger.debug("Alert sent to user %d for order %s", user.telegram_id, order.id)
        except Exception as e:
            logger.error("Failed to send alert to user %d: %s", user.telegram_id, e)

    async def _send_webhook(
        self,
        user: User,
        url: str,
        order: WhaleOrder,
        ai_analysis: Optional[dict[str, Any]] = None,
    ) -> None:
        """Send alert payload to a user-defined webhook URL."""
        if not self._webhook_client:
            return

        payload = {
            "event": "hyperliquid_whale_open_alert",
            "user_id": user.telegram_id,
            "channel": "webhook",
            "order": order.to_push_payload(),
            "ai_analysis": ai_analysis or {},
            "summary": order.summary(),
            "timestamp": int(time.time() * 1000),
        }
        try:
            resp = await self._webhook_client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code >= 400:
                logger.warning(
                    "User webhook %s returned %d for user %d",
                    self._mask_url(url),
                    resp.status_code,
                    user.telegram_id,
                )
            else:
                logger.debug("User webhook sent for user %d", user.telegram_id)
        except Exception as exc:
            logger.error("User webhook failed for user %d: %s", user.telegram_id, exc)

    @staticmethod
    def _target_key(user: User) -> tuple[str, str]:
        """Build dedupe key for push target."""
        channel = (user.push_channel or "dm").lower()
        if channel == "group":
            return ("group", str(user.push_group_chat_id or user.telegram_id))
        if channel == "webhook":
            return ("webhook", (user.custom_webhook_url or "").strip().lower())
        return ("dm", str(user.telegram_id))

    @staticmethod
    def _mask_url(url: str) -> str:
        if len(url) <= 18:
            return "***"
        return f"{url[:12]}...{url[-6:]}"

    def _format_alert_message(self, order: WhaleOrder, ai_analysis: Optional[dict] = None) -> str:
        """Format alert message for Telegram."""
        emoji = "🟢" if order.side.value == "buy" else "🔴"
        direction = "LONG 开仓" if order.side.value == "buy" else "SHORT 开仓"
        ts = datetime.fromtimestamp(order.timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')
        wallet = str(order.metadata.get("wallet", "")) if isinstance(order.metadata, dict) else ""
        liq_price = order.metadata.get("liq_price") if isinstance(order.metadata, dict) else None
        tier = "标准"
        if order.amount_usd >= 10_000_000:
            tier = "超级"
        elif order.amount_usd >= 5_000_000:
            tier = "重点"

        message = (
            f"{emoji} Hyperliquid 鲸鱼开仓预警\n\n"
            f"交易所: {order.exchange}\n"
            f"标的: {order.symbol}\n"
            f"方向: {direction}\n"
            f"名义价值: ${order.amount_usd:,.0f}\n"
            f"开仓价: ${order.price:,.2f}\n"
            f"仓位规模: {order.quantity:,.4f}\n"
            f"风险分层: {tier}\n"
            f"时间: {ts} UTC"
        )
        if wallet:
            message += f"\n钱包: {wallet}"
        if liq_price:
            try:
                message += f"\n预估清算价: ${float(liq_price):,.2f}"
            except Exception:
                message += f"\n预估清算价: {liq_price}"

        # Add AI analysis if available
        if ai_analysis and ai_analysis.get("analysis"):
            signal_emoji = {
                "bullish": "📈",
                "bearish": "📉",
                "neutral": "➡️",
            }.get(ai_analysis.get("signal", "neutral"), "➡️")

            message += (
                "\n\n"
                "AI 分析:\n"
                f"分析: {ai_analysis.get('analysis', '分析中...')}\n"
                f"信号: {signal_emoji} {ai_analysis.get('signal', 'neutral').upper()}\n"
                f"置信度: {ai_analysis.get('confidence', 0)}/100\n"
                f"风险等级: {ai_analysis.get('risk_level', 'medium').upper()}\n"
                f"建议: {ai_analysis.get('suggestion', '建议观望')}"
            )

        return message.strip()

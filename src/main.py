from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any, Optional

import uvicorn

from config.settings import get_settings
from src.api.coinglass_client import CoinGlassClient
from src.api.coinglass_ws import CoinGlassWSClient
from src.collectors.large_order import FuturesLargeOrderCollector, SpotLargeOrderCollector
from src.collectors.liquidation import LiquidationCollector, parse_ws_liquidation
from src.collectors.hyperliquid import HyperliquidWhaleCollector
from src.collectors.onchain import OnchainTransferCollector
from src.engine.aggregator import Aggregator
from src.engine.alert_rules import AlertEngine
from src.push.webhook import WebhookDispatcher
from src.storage.database import Database
from src.storage.user_database import UserDatabase
from src.models.whale_order import WhaleOrder
from src.server import app, ws_manager, inject_dependencies
from src.telegram.bot import TelegramBot
from src.telegram.push_dispatcher import PushDispatcher
from src.telegram.user_manager import UserManager
from src.telegram.dialog_handler import DialogHandler
from src.ai.deepseek_client import DeepseekClient
from src.ai.analyzer import AIAnalyzer
from src.ai.analyzer import AIAnalyzer


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("whale_monitor")


class WhaleMonitor:
    """Orchestrates all components of the whale order monitoring system."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.db = Database()
        self.user_db = UserDatabase()
        self.cg_client = CoinGlassClient()
        self.alert_engine = AlertEngine()
        self.webhook = WebhookDispatcher()
        self.deepseek = DeepseekClient()
        self.ai_analyzer:Optional[ AIAnalyzer] = None
        if self.settings.deepseek_api_key:
            self.ai_analyzer = AIAnalyzer(self.deepseek, self.db)

        # Initialize Telegram Bot if enabled
        self.tg_bot:Optional[ TelegramBot] = None
        self.tg_push_dispatcher:Optional[ PushDispatcher] = None
        self.user_manager:Optional[ UserManager] = None
        self.dialog_handler:Optional[ DialogHandler] = None

        if self.settings.tg_enabled:
            from telegram import Bot as TelegramBotInstance

            tg_bot_instance = TelegramBotInstance(
                token=self.settings.tg_bot_token
            )
            self.tg_push_dispatcher = PushDispatcher(tg_bot_instance)
            self.user_manager = UserManager(self.user_db)
            self.dialog_handler = DialogHandler(
                self.user_db, self.db, self.ai_analyzer
            )
            self.tg_bot = TelegramBot(
                self.user_db,
                self.tg_push_dispatcher,
                self.dialog_handler,
                db=self.db,
                ai_client=self.deepseek,
            )

        self.aggregator = Aggregator(
            db=self.db,
            alert_engine=self.alert_engine,
            push_callback=self._on_alert,
            ai_analyzer=self.ai_analyzer,
        )

        self._collectors: list[Any] = []
        self._cg_ws:Optional[ CoinGlassWSClient] = None

    async def _on_alert(self, order: WhaleOrder, matched_rules: list[str], ai_analysis:Optional[ dict] = None) -> None:
        """Dispatch alert to all push channels."""
        tasks = []
        if self.settings.ws_push_enabled:
            tasks.append(ws_manager.broadcast(order, matched_rules))
        if self.settings.webhook_push_enabled:
            tasks.append(self.webhook.dispatch(order, matched_rules))

        # Push to Telegram users
        if self.tg_push_dispatcher and self.user_manager:
            try:
                users = await self.user_manager.get_active_users_for_alert(
                    exchange=order.exchange, amount_usd=order.amount_usd
                )
                if users:
                    await self.tg_push_dispatcher.push_alert(users, order, ai_analysis)
                    logger.info(
                        "Alert pushed to %d Telegram users for order %s",
                        len(users),
                        order.id,
                    )
            except Exception as e:
                logger.error("Telegram push error: %s", e, exc_info=True)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _on_ws_message(self, channel: str, data: list[dict[str, Any]]) -> None:
        """Handle incoming WebSocket messages from CoinGlass."""
        if channel == "liquidationOrders":
            orders = parse_ws_liquidation(data)
            if orders:
                await self.aggregator.ingest(orders)

    async def start(self) -> None:
        logger.info("=" * 60)
        logger.info("  BTC Whale Order Monitor v2.0.0")
        logger.info("  Exchanges: %s", self.settings.exchange_list)
        logger.info("  Large order threshold: $%s", f"{self.settings.large_order_threshold:,.0f}")
        logger.info("  Liquidation threshold: $%s", f"{self.settings.liquidation_threshold:,.0f}")
        logger.info("  Telegram Bot: %s", "enabled" if self.settings.tg_enabled else "disabled")
        logger.info("  Deepseek AI: %s", "enabled" if self.settings.deepseek_api_key else "disabled")
        logger.info("=" * 60)

        # Start databases
        await self.db.start()
        await self.user_db.start()

        # Start external services
        await self.cg_client.start()
        await self.webhook.start()
        await self.deepseek.start()

        # Initialize AI analyzer if Deepseek is configured
        if self.ai_analyzer:
            logger.info("AI analyzer initialized")

        # Start Telegram Bot
        if self.tg_bot:
            await self.tg_push_dispatcher.start()
            await self.tg_bot.start()

        inject_dependencies(self.db, self.aggregator, self.settings)

        ingest = self.aggregator.ingest

        self._collectors = [
            FuturesLargeOrderCollector(self.cg_client, ingest),
            SpotLargeOrderCollector(self.cg_client, ingest),
            LiquidationCollector(self.cg_client, ingest),
            HyperliquidWhaleCollector(self.cg_client, ingest),
            OnchainTransferCollector(self.cg_client, ingest),
        ]

        for c in self._collectors:
            await c.start()

        self._cg_ws = CoinGlassWSClient(handler=self._on_ws_message)
        await self._cg_ws.start()

        logger.info("All collectors started. System ready.")

    async def stop(self) -> None:
        logger.info("Shutting down...")
        if self._cg_ws:
            await self._cg_ws.stop()
        for c in self._collectors:
            await c.stop()

        # Stop Telegram Bot
        if self.tg_bot:
            await self.tg_bot.stop()
        if self.tg_push_dispatcher:
            await self.tg_push_dispatcher.stop()

        await self.webhook.stop()
        await self.deepseek.stop()
        await self.cg_client.stop()
        await self.user_db.stop()
        await self.db.stop()
        logger.info("Shutdown complete.")


async def run() -> None:
    monitor = WhaleMonitor()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(monitor.stop()))

    await monitor.start()

    config = uvicorn.Config(
        app,
        host=monitor.settings.host,
        port=monitor.settings.port,
        log_level=monitor.settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")


if __name__ == "__main__":
    main()

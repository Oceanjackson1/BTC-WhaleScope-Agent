from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any, Optional

import uvicorn

from config.settings import get_settings
from src.api.coinglass_client import CoinGlassClient
from src.collectors.hyperliquid import HyperliquidWhaleCollector
from src.engine.aggregator import Aggregator
from src.engine.alert_rules import AlertEngine
from src.push.heartbeat import HeartbeatReporter
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


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("whale_monitor")

# Suppress request-level client logs that can expose credential-bearing URLs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class WhaleMonitor:
    """Orchestrates all components of the whale order monitoring system."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.db = Database()
        self.user_db = UserDatabase()
        self.cg_client = CoinGlassClient()
        self.alert_engine = AlertEngine()
        self.heartbeat = HeartbeatReporter()
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
        self._stopped = False
        self._stop_task: Optional[asyncio.Task[None]] = None

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

    async def start(self) -> None:
        await self.heartbeat.start()
        await self.heartbeat.report("working", "BTC WhaleScope Agent 启动中")

        logger.info("=" * 60)
        logger.info("  Hyperliquid Whale Open Monitor v3.0.0")
        logger.info("  Scope: Hyperliquid whale OPEN positions only")
        logger.info("  Large order threshold: $%s", f"{self.settings.large_order_threshold:,.0f}")
        logger.info("  Telegram Bot: %s", "enabled" if self.settings.tg_enabled else "disabled")
        logger.info("  Deepseek AI: %s", "enabled" if self.settings.deepseek_api_key else "disabled")
        logger.info("  Agent ID: %s", self.settings.agent_id)
        logger.info("  Agent Name: %s", self.settings.agent_name)
        logger.info("  Bot Username: %s", self.settings.bot_username or "unknown")
        logger.info("  App Version: %s", self.settings.app_version)
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
            HyperliquidWhaleCollector(self.cg_client, ingest),
        ]

        for c in self._collectors:
            await c.start()

        logger.info("All collectors started. System ready.")
        await self.heartbeat.report("working", "BTC WhaleScope Agent 运行中")

    async def stop(self, report_idle: bool = True) -> None:
        if self._stopped:
            return

        if self._stop_task:
            await self._stop_task
            return

        self._stop_task = asyncio.create_task(self._shutdown(report_idle))
        await self._stop_task

    async def _shutdown(self, report_idle: bool) -> None:
        self._stopped = True

        logger.info("Shutting down...")
        if report_idle:
            await self.heartbeat.report("idle", "")
        for c in self._collectors:
            await self._shutdown_step(f"collector:{c.name}", c.stop())

        # Stop Telegram Bot
        if self.tg_bot:
            await self._shutdown_step("Telegram Bot", self.tg_bot.stop())
        if self.tg_push_dispatcher:
            await self._shutdown_step("Telegram push dispatcher", self.tg_push_dispatcher.stop())

        await self._shutdown_step("Webhook dispatcher", self.webhook.stop())
        await self._shutdown_step("Deepseek client", self.deepseek.stop())
        await self._shutdown_step("CoinGlass REST client", self.cg_client.stop())
        await self._shutdown_step("User database", self.user_db.stop())
        await self._shutdown_step("Order database", self.db.stop())
        logger.info("Shutdown complete.")

        await self.heartbeat.stop()

    async def report_exception(self, exc: Optional[BaseException], phase: str) -> None:
        await self.heartbeat.report_exception(exc, phase)

    async def _shutdown_step(
        self,
        label: str,
        operation: Any,
        timeout: float = 5.0,
    ) -> None:
        try:
            await asyncio.wait_for(operation, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Shutdown step timed out: %s", label)
        except Exception as exc:
            logger.error("Shutdown step failed [%s]: %s", label, exc, exc_info=True)


async def run() -> None:
    monitor = WhaleMonitor()
    loop = asyncio.get_running_loop()
    should_report_idle = True

    def handle_loop_exception(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        exc = context.get("exception")
        message = context.get("message", "Unhandled event loop exception")
        logger.error("Unhandled event loop exception: %s", message, exc_info=exc)
        loop.create_task(monitor.report_exception(exc, f"事件循环异常: {message}"))
        loop.default_exception_handler(context)

    loop.set_exception_handler(handle_loop_exception)

    try:
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
    except Exception as exc:
        should_report_idle = False
        await monitor.report_exception(exc, "进程异常退出")
        raise
    finally:
        await monitor.stop(report_idle=should_report_idle)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")


if __name__ == "__main__":
    main()

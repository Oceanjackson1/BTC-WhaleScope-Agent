from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Awaitable

import websockets
from websockets.asyncio.client import ClientConnection

from config.settings import get_settings

logger = logging.getLogger(__name__)

MessageHandler = Callable[[str, list[dict[str, Any]]], Awaitable[None]]


class CoinGlassWSClient:
    """WebSocket client for CoinGlass real-time data streams."""

    CHANNELS = ["liquidationOrders", "tradeOrders"]

    def __init__(self, handler: MessageHandler) -> None:
        self.settings = get_settings()
        self._handler = handler
        self._ws:Optional[ ClientConnection] = None
        self._running = False
        self._task: asyncio.Optional[Task] = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_forever())
        logger.info("CoinGlass WebSocket client started")

    async def stop(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CoinGlass WebSocket client stopped")

    async def _run_forever(self) -> None:
        backoff = 1
        while self._running:
            try:
                async with websockets.connect(
                    self.settings.cg_ws_url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._ws = ws
                    backoff = 1
                    logger.info("WebSocket connected to CoinGlass")

                    subscribe_msg = json.dumps({
                        "method": "subscribe",
                        "channels": self.CHANNELS,
                    })
                    await ws.send(subscribe_msg)
                    logger.info("Subscribed to channels: %s", self.CHANNELS)

                    async for raw_msg in ws:
                        if raw_msg == "pong":
                            continue
                        try:
                            msg = json.loads(raw_msg)
                            channel = msg.get("channel", "")
                            data = msg.get("data", [])
                            if channel and data:
                                await self._handler(channel, data)
                        except json.JSONDecodeError:
                            if "upgrade" in str(raw_msg).lower():
                                logger.info("WS channel requires plan upgrade: %s", raw_msg[:100])
                            else:
                                logger.debug("Non-JSON WS message: %s", raw_msg[:200])

            except websockets.ConnectionClosed as e:
                logger.warning("WebSocket connection closed: %s. Reconnecting in %ds...", e, backoff)
            except Exception as e:
                logger.error("WebSocket error: %s. Reconnecting in %ds...", e, backoff)

            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Callable, Awaitable

from src.models.whale_order import WhaleOrder
from src.api.coinglass_client import CoinGlassClient, CoinGlassAPIError

logger = logging.getLogger(__name__)

OrderCallback = Callable[[list[WhaleOrder]], Awaitable[None]]


class BaseCollector(ABC):
    """Base class for all polling data collectors."""

    name: str = "base"

    def __init__(self, client: CoinGlassClient, callback: OrderCallback, interval: int = 10) -> None:
        self.client = client
        self.callback = callback
        self.interval = interval
        self._task: asyncio.Optional[Task] = None
        self._running = False
        self._disabled = False

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Collector [%s] started (interval=%ds)", self.name, self.interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Collector [%s] stopped", self.name)

    async def _poll_loop(self) -> None:
        while self._running:
            if self._disabled:
                await asyncio.sleep(self.interval)
                continue
            try:
                orders = await self.collect()
                if orders:
                    await self.callback(orders)
                    logger.debug("[%s] collected %d orders", self.name, len(orders))
            except CoinGlassAPIError as e:
                if "Upgrade plan" in e.message or "upgrade" in e.message.lower():
                    logger.warning("[%s] API plan insufficient, collector paused. Upgrade your CoinGlass plan to enable.", self.name)
                    self._disabled = True
                else:
                    logger.error("[%s] API error: %s", self.name, e)
            except Exception as e:
                logger.error("[%s] collection error: %s", self.name, e, exc_info=True)
            await asyncio.sleep(self.interval)

    @abstractmethod
    async def collect(self) -> list[WhaleOrder]:
        ...

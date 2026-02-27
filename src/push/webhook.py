from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from src.models.whale_order import WhaleOrder
from config.settings import get_settings

logger = logging.getLogger(__name__)


class WebhookDispatcher:
    """Dispatches whale order alerts to configured webhook URLs."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: httpx.Optional[AsyncClient] = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        logger.info(
            "Webhook dispatcher started (targets: %d)",
            len(self.settings.webhook_url_list),
        )

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()

    async def dispatch(self, order: WhaleOrder, matched_rules: list[str]) -> None:
        urls = self.settings.webhook_url_list
        if not urls:
            return

        payload = {
            "event": "whale_alert",
            "rules": matched_rules,
            "order": order.to_push_payload(),
            "summary": order.summary(),
            "timestamp": int(time.time() * 1000),
        }

        tasks = [self._send(url, payload) for url in urls]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _send(self, url: str, payload: dict[str, Any]) -> None:
        try:
            resp = await self._client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code >= 400:
                logger.warning("Webhook %s returned %d", url, resp.status_code)
            else:
                logger.debug("Webhook %s -> %d", url, resp.status_code)
        except Exception as e:
            logger.error("Webhook %s failed: %s", url, e)

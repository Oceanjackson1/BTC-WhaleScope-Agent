from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from config.settings import get_settings

logger = logging.getLogger(__name__)


class HeartbeatReporter:
    """Reports process state to the external Pixel Office monitor."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def enabled(self) -> bool:
        return bool(
            self.settings.heartbeat_enabled
            and self.settings.heartbeat_url
            and self.settings.heartbeat_api_key
            and self.settings.heartbeat_agent_id
        )

    async def start(self) -> None:
        """Initialize the heartbeat client."""
        if not self.enabled:
            logger.info("Heartbeat reporter disabled")
            return

        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        logger.info(
            "Heartbeat reporter started for agent %s",
            self.settings.heartbeat_agent_id,
        )

    async def stop(self) -> None:
        """Close heartbeat resources."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def report(self, status: str, current_task: str = "") -> None:
        """Send a heartbeat state update without breaking the main app."""
        if not self.enabled:
            return

        if not self._client:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))

        payload = {
            "id": self.settings.heartbeat_agent_id,
            "status": status,
            "current_task": self._trim_task(current_task),
            "name": self.settings.heartbeat_name,
            "role": self.settings.heartbeat_role,
            "role_label_zh": self.settings.heartbeat_role_label_zh,
        }

        try:
            response = await self._client.post(
                self.settings.heartbeat_url,
                json=payload,
                headers=self._headers(),
            )
            if response.status_code >= 400:
                logger.warning(
                    "Heartbeat report failed with status %d: %s",
                    response.status_code,
                    response.text[:200],
                )
        except Exception as exc:
            logger.warning("Heartbeat report failed: %s", exc)

    async def report_exception(
        self,
        exc: Optional[BaseException],
        phase: str = "运行异常",
    ) -> None:
        """Report an exception summary to the heartbeat endpoint."""
        error_name = type(exc).__name__ if exc else "UnknownError"
        detail = f"{phase}: {error_name}"
        await self.report("thinking", detail)

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.settings.heartbeat_api_key,
            "Authorization": f"Bearer {self.settings.heartbeat_token}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        }

    def _trim_task(self, current_task: str, max_length: int = 120) -> str:
        if len(current_task) <= max_length:
            return current_task
        return current_task[: max_length - 3] + "..."

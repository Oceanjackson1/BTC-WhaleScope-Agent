from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from config.settings import get_settings

logger = logging.getLogger(__name__)


class CoinGlassAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"CoinGlass API error {status_code}: {message}")


class RateLimiter:
    """Token-bucket rate limiter for API requests."""

    def __init__(self, max_per_minute: int = 280):
        self._semaphore = asyncio.Semaphore(max_per_minute)
        self._max = max_per_minute
        self._refill_task: asyncio.Optional[Task] = None

    async def start(self) -> None:
        self._refill_task = asyncio.create_task(self._refill_loop())

    async def _refill_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            deficit = self._max - self._semaphore._value
            for _ in range(deficit):
                self._semaphore.release()

    async def acquire(self) -> None:
        await self._semaphore.acquire()

    async def stop(self) -> None:
        if self._refill_task:
            self._refill_task.cancel()


class CoinGlassClient:
    """Async HTTP client for CoinGlass REST API v4."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: httpx.Optional[AsyncClient] = None
        self._rate_limiter = RateLimiter()

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.settings.cg_rest_base,
            headers={
                "CG-API-KEY": self.settings.cg_api_key,
                "accept": "application/json",
            },
            timeout=httpx.Timeout(30.0),
        )
        await self._rate_limiter.start()
        logger.info("CoinGlass REST client started")

    async def stop(self) -> None:
        await self._rate_limiter.stop()
        if self._client:
            await self._client.aclose()
        logger.info("CoinGlass REST client stopped")

    async def _get(self, path: str, params:Optional[ dict[str, Any]] = None) -> Any:
        if not self._client:
            raise RuntimeError("Client not started. Call start() first.")

        await self._rate_limiter.acquire()
        try:
            resp = await self._client.get(path, params=params)
            if resp.status_code != 200:
                raise CoinGlassAPIError(resp.status_code, resp.text)
            data = resp.json()
            if data.get("code") != "0":
                raise CoinGlassAPIError(int(data.get("code", -1)), data.get("msg", "unknown"))
            return data.get("data")
        except httpx.HTTPError as e:
            logger.error("HTTP request failed: %s %s -> %s", "GET", path, e)
            raise

    # ── Futures Order Book ──

    async def get_large_orders(self, exchange: str, symbol: str = "BTCUSDT") -> list[dict]:
        return await self._get(
            "/api/futures/orderbook/large-limit-order",
            {"exchange": exchange, "symbol": symbol},
        ) or []

    async def get_large_order_history(
        self, exchange: str, symbol: str, start_time: int, end_time: int, state: int = 2
    ) -> list[dict]:
        return await self._get(
            "/api/futures/orderbook/large-limit-order-history",
            {
                "exchange": exchange,
                "symbol": symbol,
                "start_time": start_time,
                "end_time": end_time,
                "state": state,
            },
        ) or []

    # ── Spot Order Book ──

    async def get_spot_large_orders(self, exchange: str, symbol: str = "BTCUSDT") -> list[dict]:
        return await self._get(
            "/api/spot/orderbook/large-limit-order",
            {"exchange": exchange, "symbol": symbol},
        ) or []

    async def get_spot_large_order_history(
        self, exchange: str, symbol: str, start_time: int, end_time: int, state: int = 2
    ) -> list[dict]:
        return await self._get(
            "/api/spot/orderbook/large-limit-order-history",
            {
                "exchange": exchange,
                "symbol": symbol,
                "start_time": start_time,
                "end_time": end_time,
                "state": state,
            },
        ) or []

    # ── Liquidation ──

    async def get_liquidation_orders(
        self,
        exchange: str,
        symbol: str = "BTC",
        min_amount: float = 100_000,
        start_time:Optional[ int] = None,
        end_time:Optional[ int] = None,
    ) -> list[dict]:
        params: dict[str, Any] = {
            "exchange": exchange,
            "symbol": symbol,
            "min_liquidation_amount": str(int(min_amount)),
        }
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        return await self._get("/api/futures/liquidation/order", params) or []

    # ── Hyperliquid ──

    async def get_hyperliquid_whale_alerts(self) -> list[dict]:
        return await self._get("/api/hyperliquid/whale-alert") or []

    async def get_hyperliquid_whale_positions(self) -> list[dict]:
        return await self._get("/api/hyperliquid/whale-position") or []

    # ── On-chain ──

    async def get_exchange_chain_transfers(self) -> list[dict]:
        return await self._get("/api/exchange/chain/tx/list") or []

    # ── Market helpers ──

    async def get_supported_exchanges(self) -> list[dict]:
        return await self._get("/api/futures/supported-exchange-pairs") or []

    async def get_supported_coins(self) -> list[dict]:
        return await self._get("/api/futures/supported-coins") or []

    # ── Whale Index ──

    async def get_whale_index(
        self,
        exchange: str = "Binance",
        symbol: str = "BTCUSDT",
        interval: str = "1h",
        limit: int = 100,
    ) -> list[dict]:
        return await self._get(
            "/api/futures/whale-index/history",
            {"exchange": exchange, "symbol": symbol, "interval": interval, "limit": limit},
        ) or []

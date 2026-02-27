from __future__ import annotations

import logging
from typing import Any

from src.collectors.base import BaseCollector, OrderCallback
from src.api.coinglass_client import CoinGlassClient
from src.models.whale_order import WhaleOrder, OrderSource, OrderType, OrderSide, OrderStatus
from config.settings import get_settings

logger = logging.getLogger(__name__)


def _parse_liquidation(raw: dict[str, Any]) -> WhaleOrder:
    side = OrderSide.BUY if raw.get("side") == 1 else OrderSide.SELL
    return WhaleOrder(
        source=OrderSource.CEX_FUTURES,
        order_type=OrderType.LIQUIDATION,
        exchange=raw.get("exchange_name", raw.get("exName", "")),
        symbol=raw.get("symbol", ""),
        side=side,
        price=float(raw.get("price", 0)),
        amount_usd=float(raw.get("usd_value", raw.get("volUsd", 0))),
        quantity=0,
        status=OrderStatus.FILLED,
        timestamp=int(raw.get("time", 0)),
        metadata={"base_asset": raw.get("base_asset", raw.get("baseAsset", "BTC"))},
    )


class LiquidationCollector(BaseCollector):
    """Poll-based liquidation order collector (fallback for WS)."""

    name = "liquidation_poll"

    def __init__(self, client: CoinGlassClient, callback: OrderCallback) -> None:
        settings = get_settings()
        super().__init__(client, callback, settings.poll_interval_liquidation)
        self.exchanges = settings.exchange_list
        self.threshold = settings.liquidation_threshold

    async def collect(self) -> list[WhaleOrder]:
        orders: list[WhaleOrder] = []
        for exchange in self.exchanges:
            raw_list = await self.client.get_liquidation_orders(
                exchange, "BTC", min_amount=self.threshold
            )
            for raw in raw_list:
                orders.append(_parse_liquidation(raw))
        return orders


def parse_ws_liquidation(data: list[dict[str, Any]]) -> list[WhaleOrder]:
    """Parse liquidation orders from WebSocket stream."""
    orders = []
    for raw in data:
        base = raw.get("baseAsset", "")
        if base.upper() != "BTC":
            continue
        orders.append(_parse_liquidation(raw))
    return orders

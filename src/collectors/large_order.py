from __future__ import annotations

import logging
from typing import Any

from src.collectors.base import BaseCollector, OrderCallback
from src.api.coinglass_client import CoinGlassClient, CoinGlassAPIError
from src.models.whale_order import WhaleOrder, OrderSource, OrderType, OrderSide, OrderStatus
from config.settings import get_settings

logger = logging.getLogger(__name__)


def _parse_side(val: int) -> OrderSide:
    return OrderSide.BUY if val == 2 else OrderSide.SELL if val == 1 else OrderSide.UNKNOWN


def _parse_state(val: int) -> OrderStatus:
    mapping = {1: OrderStatus.OPEN, 2: OrderStatus.FILLED, 3: OrderStatus.CANCELLED}
    return mapping.get(val, OrderStatus.UNKNOWN)


def _raw_to_order(raw: dict[str, Any], source: OrderSource) -> WhaleOrder:
    return WhaleOrder(
        id=str(raw.get("id", "")),
        source=source,
        order_type=OrderType.LARGE_LIMIT,
        exchange=raw.get("exchange_name", ""),
        symbol=raw.get("symbol", ""),
        side=_parse_side(raw.get("order_side", 0)),
        price=float(raw.get("price", 0)),
        amount_usd=float(raw.get("current_usd_value") or raw.get("start_usd_value", 0)),
        quantity=float(raw.get("current_quantity") or raw.get("start_quantity", 0)),
        status=_parse_state(raw.get("order_state", 0)),
        timestamp=int(raw.get("start_time", 0)),
        metadata={
            "start_usd": raw.get("start_usd_value"),
            "executed_usd": raw.get("executed_usd_value"),
            "trade_count": raw.get("trade_count"),
        },
    )


class FuturesLargeOrderCollector(BaseCollector):
    name = "futures_large_order"

    def __init__(self, client: CoinGlassClient, callback: OrderCallback) -> None:
        settings = get_settings()
        super().__init__(client, callback, settings.poll_interval_large_order)
        self.exchanges = settings.exchange_list
        self.threshold = settings.large_order_threshold

    async def collect(self) -> list[WhaleOrder]:
        orders: list[WhaleOrder] = []
        for exchange in self.exchanges:
            raw_list = await self.client.get_large_orders(exchange, "BTCUSDT")
            for raw in raw_list:
                order = _raw_to_order(raw, OrderSource.CEX_FUTURES)
                if order.amount_usd >= self.threshold:
                    orders.append(order)
        return orders


class SpotLargeOrderCollector(BaseCollector):
    name = "spot_large_order"

    def __init__(self, client: CoinGlassClient, callback: OrderCallback) -> None:
        settings = get_settings()
        super().__init__(client, callback, settings.poll_interval_large_order)
        self.exchanges = settings.exchange_list
        self.threshold = settings.large_order_threshold

    async def collect(self) -> list[WhaleOrder]:
        orders: list[WhaleOrder] = []
        for exchange in self.exchanges:
            raw_list = await self.client.get_spot_large_orders(exchange, "BTCUSDT")
            for raw in raw_list:
                order = _raw_to_order(raw, OrderSource.CEX_SPOT)
                if order.amount_usd >= self.threshold:
                    orders.append(order)
        return orders

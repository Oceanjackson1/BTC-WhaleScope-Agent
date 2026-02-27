from __future__ import annotations

import logging
from typing import Any

from src.collectors.base import BaseCollector, OrderCallback
from src.api.coinglass_client import CoinGlassClient
from src.models.whale_order import WhaleOrder, OrderSource, OrderType, OrderSide, OrderStatus
from config.settings import get_settings

logger = logging.getLogger(__name__)


class HyperliquidWhaleCollector(BaseCollector):
    name = "hyperliquid_whale"

    def __init__(self, client: CoinGlassClient, callback: OrderCallback) -> None:
        settings = get_settings()
        super().__init__(client, callback, settings.poll_interval_whale_alert)
        self._seen_ids: set[str] = set()

    async def collect(self) -> list[WhaleOrder]:
        orders: list[WhaleOrder] = []
        try:
            raw_list = await self.client.get_hyperliquid_whale_alerts()
            for raw in raw_list:
                if raw.get("symbol", "").upper() != "BTC":
                    continue
                uid = f"{raw.get('user','')}:{raw.get('create_time','')}"
                if uid in self._seen_ids:
                    continue
                self._seen_ids.add(uid)
                # keep seen set bounded
                if len(self._seen_ids) > 5000:
                    self._seen_ids = set(list(self._seen_ids)[-2500:])

                size = float(raw.get("position_size", 0))
                side = OrderSide.BUY if size > 0 else OrderSide.SELL
                action = raw.get("position_action", 0)
                order_type = OrderType.WHALE_POSITION

                orders.append(WhaleOrder(
                    source=OrderSource.DEX_HYPERLIQUID,
                    order_type=order_type,
                    exchange="Hyperliquid",
                    symbol=f"BTC-PERP",
                    side=side,
                    price=float(raw.get("entry_price", 0)),
                    amount_usd=float(raw.get("position_value_usd", 0)),
                    quantity=abs(size),
                    status=OrderStatus.OPEN if action == 1 else OrderStatus.FILLED,
                    timestamp=int(raw.get("create_time", 0)),
                    metadata={
                        "wallet": raw.get("user", ""),
                        "liq_price": raw.get("liq_price"),
                        "action": "open" if action == 1 else "close",
                    },
                ))
        except Exception as e:
            logger.warning("[%s] collection error: %s", self.name, e)
        return orders

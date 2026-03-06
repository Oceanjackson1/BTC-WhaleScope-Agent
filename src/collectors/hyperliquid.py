from __future__ import annotations

import logging
from typing import Any

from src.collectors.base import BaseCollector, OrderCallback
from src.api.coinglass_client import CoinGlassClient
from src.models.whale_order import WhaleOrder, OrderSource, OrderType, OrderSide, OrderStatus
from config.settings import get_settings

logger = logging.getLogger(__name__)


def _normalize_ts_ms(raw_ts: Any) -> int:
    try:
        ts = int(float(raw_ts or 0))
    except (TypeError, ValueError):
        return 0
    if ts <= 0:
        return 0
    return ts * 1000 if ts < 10_000_000_000 else ts


def _normalize_symbol(raw: dict[str, Any]) -> str:
    symbol = str(raw.get("symbol") or raw.get("asset_symbol") or "UNKNOWN").upper()
    if symbol.endswith("-PERP"):
        return symbol
    if symbol in {"BTC", "ETH", "SOL"} or symbol.isalpha():
        return f"{symbol}-PERP"
    return symbol


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
                action_val = raw.get("position_action", raw.get("action", raw.get("positionAction", 0)))
                try:
                    action = int(action_val)
                except (TypeError, ValueError):
                    action = 0
                # Product re-definition: only whale OPEN events.
                if action != 1:
                    continue

                wallet = str(raw.get("user", raw.get("wallet", ""))).strip()
                ts_raw = raw.get("create_time", raw.get("createTime", raw.get("timestamp", 0)))
                uid = f"{wallet}:{ts_raw}"
                if uid in self._seen_ids:
                    continue
                self._seen_ids.add(uid)
                # keep seen set bounded
                if len(self._seen_ids) > 5000:
                    self._seen_ids = set(list(self._seen_ids)[-2500:])

                size = float(raw.get("position_size", raw.get("size", 0)) or 0)
                if size == 0:
                    continue
                side = OrderSide.BUY if size > 0 else OrderSide.SELL
                order_type = OrderType.WHALE_POSITION
                ts_ms = _normalize_ts_ms(ts_raw)
                symbol = _normalize_symbol(raw)

                orders.append(WhaleOrder(
                    source=OrderSource.DEX_HYPERLIQUID,
                    order_type=order_type,
                    exchange="Hyperliquid",
                    symbol=symbol,
                    side=side,
                    price=float(raw.get("entry_price", 0)),
                    amount_usd=float(raw.get("position_value_usd", 0)),
                    quantity=abs(size),
                    status=OrderStatus.OPEN,
                    timestamp=ts_ms,
                    metadata={
                        "wallet": wallet,
                        "liq_price": raw.get("liq_price"),
                        "action": "open",
                        "leverage": raw.get("leverage"),
                    },
                ))
        except Exception as e:
            logger.warning("[%s] collection error: %s", self.name, e)
        return orders

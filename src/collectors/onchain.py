from __future__ import annotations

import logging
from typing import Any

from src.collectors.base import BaseCollector, OrderCallback
from src.api.coinglass_client import CoinGlassClient
from src.models.whale_order import WhaleOrder, OrderSource, OrderType, OrderSide, OrderStatus
from config.settings import get_settings

logger = logging.getLogger(__name__)


def _to_milliseconds(raw_ts: Any) -> int:
    """Normalize unix timestamp to milliseconds."""
    try:
        ts = int(float(raw_ts or 0))
    except (TypeError, ValueError):
        return 0
    if ts <= 0:
        return 0
    # CoinGlass on-chain endpoint may return seconds precision.
    return ts * 1000 if ts < 10_000_000_000 else ts


class OnchainTransferCollector(BaseCollector):
    name = "onchain_transfer"

    def __init__(self, client: CoinGlassClient, callback: OrderCallback) -> None:
        settings = get_settings()
        super().__init__(client, callback, settings.poll_interval_onchain)
        self._seen_ids: set[str] = set()

    async def collect(self) -> list[WhaleOrder]:
        orders: list[WhaleOrder] = []
        try:
            raw_list = await self.client.get_exchange_chain_transfers()
            for raw in raw_list:
                tx_hash = (
                    raw.get("tx_hash")
                    or raw.get("txHash")
                    or raw.get("transaction_hash")
                    or raw.get("transactionHash")
                    or ""
                )
                if not tx_hash or tx_hash in self._seen_ids:
                    continue
                self._seen_ids.add(tx_hash)
                if len(self._seen_ids) > 10000:
                    self._seen_ids = set(list(self._seen_ids)[-5000:])

                amount_usd = float(raw.get("amount_usd", raw.get("amountUsd", 0)))
                if amount_usd < get_settings().large_order_threshold:
                    continue

                symbol = str(raw.get("asset_symbol") or raw.get("symbol") or "BTC")
                timestamp_ms = _to_milliseconds(
                    raw.get("transaction_time", raw.get("time", raw.get("timestamp", 0)))
                )

                orders.append(WhaleOrder(
                    source=OrderSource.ONCHAIN,
                    order_type=OrderType.CHAIN_TRANSFER,
                    exchange=raw.get("exchange_name", raw.get("exchangeName", "unknown")),
                    symbol=symbol,
                    side=OrderSide.UNKNOWN,
                    price=0,
                    amount_usd=amount_usd,
                    quantity=float(
                        raw.get("asset_quantity", raw.get("amount", raw.get("quantity", 0)))
                    ),
                    status=OrderStatus.FILLED,
                    timestamp=timestamp_ms,
                    metadata={
                        "tx_hash": tx_hash,
                        "from": raw.get("from_address", raw.get("from", "")),
                        "to": raw.get("to_address", raw.get("to", "")),
                        "transfer_type": raw.get("transfer_type", raw.get("type", "")),
                    },
                ))
        except Exception as e:
            logger.warning("[%s] collection error: %s", self.name, e)
        return orders

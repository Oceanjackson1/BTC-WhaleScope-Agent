from __future__ import annotations

import enum
import time
import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field


class OrderSource(str, enum.Enum):
    CEX_FUTURES = "cex_futures"
    CEX_SPOT = "cex_spot"
    DEX_HYPERLIQUID = "dex_hyperliquid"
    ONCHAIN = "onchain"


class OrderType(str, enum.Enum):
    LARGE_LIMIT = "large_limit"
    LIQUIDATION = "liquidation"
    WHALE_POSITION = "whale_position"
    CHAIN_TRANSFER = "chain_transfer"


class OrderSide(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"
    UNKNOWN = "unknown"


class OrderStatus(str, enum.Enum):
    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class WhaleOrder(BaseModel):
    id: str = ""
    source: OrderSource
    order_type: OrderType
    exchange: str
    symbol: str
    side: OrderSide
    price: float
    amount_usd: float
    quantity: float = 0.0
    status: OrderStatus = OrderStatus.UNKNOWN
    timestamp: int = Field(default_factory=lambda: int(time.time() * 1000))
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if not self.id:
            raw = f"{self.source}:{self.exchange}:{self.symbol}:{self.price}:{self.amount_usd}:{self.timestamp}"
            self.id = hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_push_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source.value,
            "type": self.order_type.value,
            "exchange": self.exchange,
            "symbol": self.symbol,
            "side": self.side.value,
            "price": self.price,
            "amount_usd": self.amount_usd,
            "quantity": self.quantity,
            "status": self.status.value,
            "timestamp": self.timestamp,
        }

    def summary(self) -> str:
        direction = "🟢 买入" if self.side == OrderSide.BUY else "🔴 卖出"
        return (
            f"[{self.source.value}] {self.exchange} {self.symbol} "
            f"{direction} ${self.amount_usd:,.0f} @ {self.price:,.2f} "
            f"({self.order_type.value})"
        )

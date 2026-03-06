from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.models.whale_order import WhaleOrder, OrderSource, OrderType, OrderSide

logger = logging.getLogger(__name__)


@dataclass
class AlertRule:
    name: str
    enabled: bool = True
    min_amount_usd:Optional[ float] = None
    sources:Optional[ list[OrderSource]] = None
    order_types:Optional[ list[OrderType]] = None
    exchanges:Optional[ list[str]] = None
    sides:Optional[ list[OrderSide]] = None

    def matches(self, order: WhaleOrder) -> bool:
        if not self.enabled:
            return False
        if self.min_amount_usd and order.amount_usd < self.min_amount_usd:
            return False
        if self.sources and order.source not in self.sources:
            return False
        if self.order_types and order.order_type not in self.order_types:
            return False
        if self.exchanges and order.exchange not in self.exchanges:
            return False
        if self.sides and order.side not in self.sides:
            return False
        return True


class AlertEngine:
    """Evaluates orders against configured alert rules."""

    def __init__(self) -> None:
        self.rules: list[AlertRule] = self._default_rules()

    def _default_rules(self) -> list[AlertRule]:
        return [
            AlertRule(
                name="hyperliquid_open_standard",
                min_amount_usd=1_000_000,
                sources=[OrderSource.DEX_HYPERLIQUID],
                order_types=[OrderType.WHALE_POSITION],
                exchanges=["Hyperliquid"],
            ),
            AlertRule(
                name="hyperliquid_open_focus",
                min_amount_usd=5_000_000,
                sources=[OrderSource.DEX_HYPERLIQUID],
                order_types=[OrderType.WHALE_POSITION],
                exchanges=["Hyperliquid"],
            ),
            AlertRule(
                name="hyperliquid_open_mega",
                min_amount_usd=10_000_000,
                sources=[OrderSource.DEX_HYPERLIQUID],
                order_types=[OrderType.WHALE_POSITION],
                exchanges=["Hyperliquid"],
            ),
        ]

    def evaluate(self, order: WhaleOrder) -> list[str]:
        """Return names of matched rules for the given order."""
        return [r.name for r in self.rules if r.matches(order)]

    def add_rule(self, rule: AlertRule) -> None:
        self.rules.append(rule)
        logger.info("Added alert rule: %s", rule.name)

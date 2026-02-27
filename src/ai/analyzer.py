"""AI analyzer for whale orders."""

from __future__ import annotations

import asyncio
import logging
import hashlib
import json
from typing import TYPE_CHECKING, Any
from datetime import datetime, timedelta

if TYPE_CHECKING:
    from src.storage.database import Database

from src.models.whale_order import WhaleOrder
from src.ai.deepseek_client import DeepseekClient

logger = logging.getLogger(__name__)


class AIAnalyzer:
    """Analyzes whale orders and generates trading signals."""

    def __init__(self, deepseek_client: DeepseekClient, db: "Database") -> None:
        self.deepseek = deepseek_client
        self.db = db
        self._analysis_cache: dict[str, tuple[dict, datetime]] = {}
        self._cache_ttl = timedelta(minutes=5)

    async def analyze_order(
        self, order: WhaleOrder
    ) -> dict[str, Any]:
        """Analyze a single order and generate trading signal."""
        # Check cache
        cache_key = self._generate_cache_key(order)
        if cache_key in self._analysis_cache:
            cached_result, cached_at = self._analysis_cache[cache_key]
            if datetime.utcnow() - cached_at < self._cache_ttl:
                logger.debug("Using cached analysis for order %s", order.id)
                return cached_result

        # Fetch historical context
        context = await self._fetch_historical_context(order)

        # Build order data for AI
        order_data = {
            "exchange": order.exchange,
            "symbol": order.symbol,
            "side": order.side.value,
            "amount_usd": order.amount_usd,
            "price": order.price,
            "order_type": order.order_type.value,
        }

        # Call Deepseek AI
        analysis = await self.deepseek.analyze_large_order(order_data, context)

        # Cache result
        self._analysis_cache[cache_key] = (analysis, datetime.utcnow())

        # Cleanup old cache entries
        await self._cleanup_cache()

        logger.info(
            "AI analysis for order %s: signal=%s, confidence=%d",
            order.id,
            analysis.get("signal"),
            analysis.get("confidence"),
        )

        return analysis

    async def fetch_orders_for_query(
        self,
        user_id:Optional[ int] = None,
        source:Optional[ str] = None,
        exchange:Optional[ str] = None,
        min_amount:Optional[ float] = None,
        hours: int = 1,
    ) -> list[WhaleOrder]:
        """Fetch orders for user queries."""
        # Calculate time range
        end_time = int(datetime.utcnow().timestamp() * 1000)
        start_time = int(
            (datetime.utcnow() - timedelta(hours=hours)).timestamp() * 1000
        )

        # Build query conditions
        conditions = []
        params = []

        conditions.append("timestamp >= ?")
        params.append(start_time)
        conditions.append("timestamp <= ?")
        params.append(end_time)

        if source:
            conditions.append("source = ?")
            params.append(source)

        if exchange:
            conditions.append("exchange = ?")
            params.append(exchange)

        if min_amount:
            conditions.append("amount_usd >= ?")
            params.append(min_amount)

        query = f"SELECT * FROM whale_orders WHERE {' AND '.join(conditions)} ORDER BY timestamp DESC LIMIT 100"

        async with self.db._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [
                WhaleOrder(
                    id=row["id"],
                    source=row["source"],
                    order_type=row["order_type"],
                    exchange=row["exchange"],
                    symbol=row["symbol"],
                    side=row["side"],
                    price=row["price"],
                    amount_usd=row["amount_usd"],
                    quantity=row.get("quantity", 0),
                    status=row["status"],
                    timestamp=row["timestamp"],
                    metadata=json.loads(row["metadata"] or "{}"),
                )
                for row in rows
            ]

    async def get_market_summary(
        self, hours: int = 1
    ) -> dict[str, Any]:
        """Get market summary for AI analysis."""
        end_time = int(datetime.utcnow().timestamp() * 1000)
        start_time = int(
            (datetime.utcnow() - timedelta(hours=hours)).timestamp() * 1000
        )

        # Get total orders
        async with self.db._conn.execute(
            "SELECT COUNT(*) as count, AVG(amount_usd) as avg_amount FROM whale_orders WHERE timestamp >= ? AND timestamp <= ?",
            (start_time, end_time),
        ) as cursor:
            row = await cursor.fetchone()

        # Get by exchange
        async with self.db._conn.execute(
            """SELECT exchange, COUNT(*) as count, SUM(amount_usd) as total
               FROM whale_orders
               WHERE timestamp >= ? AND timestamp <= ?
               GROUP BY exchange
               ORDER BY total DESC
               LIMIT 5""",
            (start_time, end_time),
        ) as cursor:
            by_exchange = await cursor.fetchall()

        # Get by side
        async with self.db._conn.execute(
            """SELECT side, COUNT(*) as count, SUM(amount_usd) as total
               FROM whale_orders
               WHERE timestamp >= ? AND timestamp <= ?
               GROUP BY side""",
            (start_time, end_time),
        ) as cursor:
            by_side = await cursor.fetchall()

        total_count = row["count"] if row else 0
        avg_amount = row["avg_amount"] if row else 0

        # Calculate buy/sell ratio
        total_buy = sum(s["count"] for s in by_side if s["side"] == "buy")
        total_sell = sum(s["count"] for s in by_side if s["side"] == "sell")
        buy_ratio = (
            (total_buy / (total_buy + total_sell) * 100)
            if (total_buy + total_sell) > 0
            else 50
        )

        return {
            "period_hours": hours,
            "total_orders": total_count,
            "avg_amount_usd": avg_amount,
            "buy_ratio": round(buy_ratio, 2),
            "sell_ratio": round(100 - buy_ratio, 2),
            "top_exchanges": [
                {"name": e["exchange"], "count": e["count"], "total": e["total"]}
                for e in by_exchange
            ],
            "by_side": [
                {"side": s["side"], "count": s["count"], "total": s["total"]}
                for s in by_side
            ],
        }

    async def _fetch_historical_context(
        self, order: WhaleOrder
    ) -> dict[str, Any]:
        """Fetch historical context for an order."""
        # Get orders in last hour for the same exchange
        end_time = int(datetime.utcnow().timestamp() * 1000)
        start_time = int(
            (datetime.utcnow() - timedelta(hours=1)).timestamp() * 1000
        )

        async with self.db._conn.execute(
            """SELECT COUNT(*) as count,
                      AVG(amount_usd) as avg_amount,
                      SUM(CASE WHEN side = ? THEN 1 ELSE 0 END) as same_side_count
               FROM whale_orders
               WHERE exchange = ?
               AND timestamp >= ? AND timestamp <= ?""",
            (order.side.value, order.exchange, start_time, end_time),
        ) as cursor:
            row = await cursor.fetchone()

        history_count = row["count"] if row else 0
        avg_amount = row["avg_amount"] if row else 0
        same_side_count = row["same_side_count"] if row else 0

        direction_ratio = (
            (same_side_count / history_count * 100) if history_count > 0 else 50
        )

        return {
            "history_count": history_count,
            "avg_amount": avg_amount,
            "direction_ratio": round(direction_ratio, 2),
        }

    def _generate_cache_key(self, order: WhaleOrder) -> str:
        """Generate cache key for an order."""
        key_str = f"{order.exchange}:{order.symbol}:{order.side.value}:{order.amount_usd}:{order.order_type.value}"
        return hashlib.sha256(key_str.encode()).hexdigest()[:16]

    async def _cleanup_cache(self) -> None:
        """Remove expired cache entries."""
        now = datetime.utcnow()
        expired_keys = [
            key
            for key, (_, timestamp) in self._analysis_cache.items()
            if now - timestamp > self._cache_ttl
        ]

        for key in expired_keys:
            del self._analysis_cache[key]

        if expired_keys:
            logger.debug("Cleaned up %d expired cache entries", len(expired_keys))

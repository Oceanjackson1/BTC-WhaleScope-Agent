from __future__ import annotations

import json
import logging
from typing import Any

import aiosqlite

from config.settings import get_settings
from src.models.whale_order import WhaleOrder

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS whale_orders (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    order_type  TEXT NOT NULL,
    exchange    TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    side        TEXT NOT NULL,
    price       REAL NOT NULL,
    amount_usd  REAL NOT NULL,
    quantity    REAL DEFAULT 0,
    status      TEXT DEFAULT 'unknown',
    timestamp   INTEGER NOT NULL,
    metadata    TEXT DEFAULT '{}',
    created_at  INTEGER NOT NULL DEFAULT (strftime('%s','now') * 1000)
);

CREATE INDEX IF NOT EXISTS idx_ts ON whale_orders(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_exchange ON whale_orders(exchange);
CREATE INDEX IF NOT EXISTS idx_source ON whale_orders(source);
CREATE INDEX IF NOT EXISTS idx_amount ON whale_orders(amount_usd DESC);
"""


class Database:
    def __init__(self) -> None:
        self._db_path = str(get_settings().abs_db_path)
        self._conn: aiosqlite.Optional[Connection] = None

    async def start(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()
        logger.info("Database initialized at %s", self._db_path)

    async def stop(self) -> None:
        if self._conn:
            await self._conn.close()

    async def insert_order(self, order: WhaleOrder) -> bool:
        """Insert an order. Returns True if it was new (not duplicate)."""
        try:
            changes_before = self._conn.total_changes
            await self._conn.execute(
                """INSERT OR IGNORE INTO whale_orders
                   (id, source, order_type, exchange, symbol, side, price,
                    amount_usd, quantity, status, timestamp, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    order.id,
                    order.source.value,
                    order.order_type.value,
                    order.exchange,
                    order.symbol,
                    order.side.value,
                    order.price,
                    order.amount_usd,
                    order.quantity,
                    order.status.value,
                    order.timestamp,
                    json.dumps(order.metadata),
                ),
            )
            await self._conn.commit()
            return self._conn.total_changes > changes_before
        except Exception as e:
            logger.error("Failed to insert order %s: %s", order.id, e)
            return False

    async def insert_orders(self, orders: list[WhaleOrder]) -> int:
        """Batch insert. Returns count of newly inserted orders."""
        new_count = 0
        for order in orders:
            if await self.insert_order(order):
                new_count += 1
        return new_count

    async def get_recent_orders(
        self,
        limit: int = 50,
        source:Optional[ str] = None,
        exchange:Optional[ str] = None,
        min_amount:Optional[ float] = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM whale_orders WHERE 1=1"
        params: list[Any] = []

        if source:
            query += " AND source = ?"
            params.append(source)
        if exchange:
            query += " AND exchange = ?"
            params.append(exchange)
        if min_amount:
            query += " AND amount_usd >= ?"
            params.append(min_amount)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_stats(self) -> dict[str, Any]:
        stats: dict[str, Any] = {}
        async with self._conn.execute("SELECT COUNT(*) as cnt FROM whale_orders") as cur:
            row = await cur.fetchone()
            stats["total_orders"] = row["cnt"]
        async with self._conn.execute(
            "SELECT source, COUNT(*) as cnt FROM whale_orders GROUP BY source"
        ) as cur:
            stats["by_source"] = {r["source"]: r["cnt"] for r in await cur.fetchall()}
        async with self._conn.execute(
            "SELECT exchange, COUNT(*) as cnt FROM whale_orders GROUP BY exchange ORDER BY cnt DESC"
        ) as cur:
            stats["by_exchange"] = {r["exchange"]: r["cnt"] for r in await cur.fetchall()}
        return stats

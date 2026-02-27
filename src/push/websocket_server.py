from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from src.models.whale_order import WhaleOrder

logger = logging.getLogger(__name__)


class WebSocketPushManager:
    """Manages connected WebSocket clients and broadcasts whale order alerts."""

    def __init__(self) -> None:
        self._clients: dict[str, WebSocket] = {}
        self._counter = 0

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def connect(self, ws: WebSocket) -> str:
        await ws.accept()
        self._counter += 1
        client_id = f"client_{self._counter}"
        self._clients[client_id] = ws
        logger.info("WS client connected: %s (total: %d)", client_id, len(self._clients))

        await ws.send_json({
            "type": "connected",
            "client_id": client_id,
            "message": "Connected to BTC Whale Order Monitor",
            "timestamp": int(time.time() * 1000),
        })
        return client_id

    async def disconnect(self, client_id: str) -> None:
        self._clients.pop(client_id, None)
        logger.info("WS client disconnected: %s (total: %d)", client_id, len(self._clients))

    async def broadcast(self, order: WhaleOrder, matched_rules: list[str]) -> None:
        if not self._clients:
            return

        payload = {
            "type": "whale_alert",
            "rules": matched_rules,
            "order": order.to_push_payload(),
            "summary": order.summary(),
            "timestamp": int(time.time() * 1000),
        }
        msg = json.dumps(payload, ensure_ascii=False)

        dead_clients: list[str] = []
        for cid, ws in self._clients.items():
            try:
                await ws.send_text(msg)
            except Exception:
                dead_clients.append(cid)

        for cid in dead_clients:
            self._clients.pop(cid, None)
            logger.debug("Removed dead WS client: %s", cid)

    async def handle_client(self, ws: WebSocket) -> None:
        client_id = await self.connect(ws)
        try:
            while True:
                data = await ws.receive_text()
                if data == "ping":
                    await ws.send_text("pong")
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.debug("WS client %s error: %s", client_id, e)
        finally:
            await self.disconnect(client_id)

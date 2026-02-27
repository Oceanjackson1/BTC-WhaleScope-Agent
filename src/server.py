from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.push.websocket_server import WebSocketPushManager

app = FastAPI(
    title="BTC Whale Order Monitor",
    description="比特币大额订单实时监控系统",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ws_manager = WebSocketPushManager()

# These will be injected by main.py at startup
_db = None
_aggregator = None
_settings = None


def inject_dependencies(db: Any, aggregator: Any, settings: Any) -> None:
    global _db, _aggregator, _settings
    _db = db
    _aggregator = aggregator
    _settings = settings


# ── Health ──

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": int(time.time() * 1000)}


# ── Pull API ──

@app.get("/api/orders")
async def get_orders(
    limit: int = Query(50, ge=1, le=500),
    source: Optional[str] = Query(None, description="cex_futures | cex_spot | dex_hyperliquid | onchain"),
    exchange: Optional[str] = Query(None),
    min_amount: Optional[float] = Query(None, description="Minimum USD amount"),
):
    """获取最近的大额订单列表（Pull 模式）。"""
    rows = await _db.get_recent_orders(
        limit=limit, source=source, exchange=exchange, min_amount=min_amount
    )
    return {"code": 0, "data": rows, "count": len(rows)}


@app.get("/api/stats")
async def get_stats():
    """获取系统统计信息。"""
    db_stats = await _db.get_stats()
    agg_stats = _aggregator.stats if _aggregator else {}
    return {
        "code": 0,
        "data": {
            "database": db_stats,
            "aggregator": agg_stats,
            "ws_clients": ws_manager.client_count,
        },
    }


@app.get("/api/config")
async def get_config():
    """获取当前监控配置（脱敏）。"""
    return {
        "code": 0,
        "data": {
            "exchanges": _settings.exchange_list,
            "large_order_threshold": _settings.large_order_threshold,
            "liquidation_threshold": _settings.liquidation_threshold,
            "poll_intervals": {
                "large_order": _settings.poll_interval_large_order,
                "liquidation": _settings.poll_interval_liquidation,
                "whale_alert": _settings.poll_interval_whale_alert,
                "onchain": _settings.poll_interval_onchain,
            },
            "push": {
                "websocket": _settings.ws_push_enabled,
                "webhook": _settings.webhook_push_enabled,
                "webhook_targets": len(_settings.webhook_url_list),
            },
        },
    }


# ── Push WebSocket ──

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket 推送端点。
    连接后自动接收大额订单告警。
    发送 'ping' 可接收 'pong' 心跳。
    """
    await ws_manager.handle_client(websocket)

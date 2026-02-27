"""
BTC Whale Order Monitor - 完整测试套件
测试范围：数据模型、告警引擎、数据库存储、API客户端、采集器、推送层
运行后在桌面生成测试数据报告
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from pathlib import Path
from datetime import datetime
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from src.models.whale_order import WhaleOrder, OrderSource, OrderType, OrderSide, OrderStatus
from src.engine.alert_rules import AlertEngine, AlertRule
from src.storage.database import Database
from src.api.coinglass_client import CoinGlassClient, CoinGlassAPIError
from src.collectors.large_order import _raw_to_order, _parse_side, _parse_state
from src.collectors.liquidation import _parse_liquidation, parse_ws_liquidation
from src.collectors.hyperliquid import HyperliquidWhaleCollector
from src.push.websocket_server import WebSocketPushManager
from src.push.webhook import WebhookDispatcher
from src.engine.aggregator import Aggregator


DESKTOP = Path.home() / "Desktop"
REPORT_DIR = DESKTOP / "BTC_Whale_Test_Data"

results: list[dict[str, Any]] = []
collected_data: dict[str, Any] = {}


def record(name: str, passed: bool, detail: str = "", data: Any = None):
    results.append({
        "test": name,
        "passed": passed,
        "detail": detail,
        "time": datetime.now().strftime("%H:%M:%S"),
    })
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  {status} | {name}")
    if not passed and detail:
        print(f"         └─ {detail}")
    if data is not None:
        collected_data[name] = data


# ═══════════════════════════════════════════════
# 1. 数据模型测试
# ═══════════════════════════════════════════════

def test_model_creation():
    """测试 WhaleOrder 模型创建与字段验证"""
    o = WhaleOrder(
        source=OrderSource.CEX_FUTURES,
        order_type=OrderType.LARGE_LIMIT,
        exchange="Binance",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        price=95000.0,
        amount_usd=2_500_000,
        quantity=26.3,
        status=OrderStatus.OPEN,
    )
    checks = [
        (len(o.id) == 16, f"id length={len(o.id)}, expected 16"),
        (o.source == OrderSource.CEX_FUTURES, f"source={o.source}"),
        (o.price == 95000.0, f"price={o.price}"),
        (o.amount_usd == 2_500_000, f"amount_usd={o.amount_usd}"),
        (o.quantity == 26.3, f"quantity={o.quantity}"),
    ]
    failed = [msg for ok, msg in checks if not ok]
    record("model_creation", not failed, "; ".join(failed), o.model_dump())


def test_model_id_deterministic():
    """测试相同输入产生相同 ID"""
    kwargs = dict(source=OrderSource.CEX_FUTURES, order_type=OrderType.LARGE_LIMIT,
                  exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY,
                  price=95000, amount_usd=2_500_000, timestamp=1700000000000)
    o1 = WhaleOrder(**kwargs)
    o2 = WhaleOrder(**kwargs)
    record("model_id_deterministic", o1.id == o2.id, f"id1={o1.id}, id2={o2.id}")


def test_model_id_unique():
    """测试不同输入产生不同 ID"""
    o1 = WhaleOrder(source=OrderSource.CEX_FUTURES, order_type=OrderType.LARGE_LIMIT,
                    exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY,
                    price=95000, amount_usd=2_500_000)
    o2 = WhaleOrder(source=OrderSource.CEX_FUTURES, order_type=OrderType.LARGE_LIMIT,
                    exchange="OKX", symbol="BTCUSDT", side=OrderSide.BUY,
                    price=95000, amount_usd=2_500_000)
    record("model_id_unique", o1.id != o2.id, f"id1={o1.id}, id2={o2.id}")


def test_model_push_payload():
    """测试 to_push_payload 输出格式"""
    o = WhaleOrder(source=OrderSource.DEX_HYPERLIQUID, order_type=OrderType.WHALE_POSITION,
                   exchange="Hyperliquid", symbol="BTC-PERP", side=OrderSide.SELL,
                   price=65000, amount_usd=5_000_000, quantity=77.0, status=OrderStatus.OPEN)
    p = o.to_push_payload()
    required_keys = {"id", "source", "type", "exchange", "symbol", "side", "price", "amount_usd", "quantity", "status", "timestamp"}
    missing = required_keys - set(p.keys())
    record("model_push_payload", not missing, f"missing keys: {missing}", p)


def test_model_summary():
    """测试 summary 文本输出"""
    o = WhaleOrder(source=OrderSource.CEX_FUTURES, order_type=OrderType.LIQUIDATION,
                   exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY,
                   price=94000, amount_usd=800_000)
    s = o.summary()
    checks = [
        ("Binance" in s, "missing exchange"),
        ("买入" in s, "missing side"),
        ("800,000" in s, "missing amount"),
        ("94,000" in s, "missing price"),
    ]
    failed = [msg for ok, msg in checks if not ok]
    record("model_summary", not failed, "; ".join(failed), s)


def test_model_enums():
    """测试所有枚举值"""
    record("enum_OrderSource", len(OrderSource) == 4,
           f"count={len(OrderSource)}, values={[e.value for e in OrderSource]}")
    record("enum_OrderType", len(OrderType) == 4,
           f"count={len(OrderType)}, values={[e.value for e in OrderType]}")
    record("enum_OrderSide", len(OrderSide) == 3,
           f"count={len(OrderSide)}, values={[e.value for e in OrderSide]}")
    record("enum_OrderStatus", len(OrderStatus) == 4,
           f"count={len(OrderStatus)}, values={[e.value for e in OrderStatus]}")


# ═══════════════════════════════════════════════
# 2. 数据解析测试
# ═══════════════════════════════════════════════

def test_parse_side():
    """测试 order_side 字段解析"""
    record("parse_side_buy", _parse_side(2) == OrderSide.BUY)
    record("parse_side_sell", _parse_side(1) == OrderSide.SELL)
    record("parse_side_unknown", _parse_side(0) == OrderSide.UNKNOWN)


def test_parse_state():
    """测试 order_state 字段解析"""
    record("parse_state_open", _parse_state(1) == OrderStatus.OPEN)
    record("parse_state_filled", _parse_state(2) == OrderStatus.FILLED)
    record("parse_state_cancelled", _parse_state(3) == OrderStatus.CANCELLED)
    record("parse_state_unknown", _parse_state(99) == OrderStatus.UNKNOWN)


def test_parse_large_order_raw():
    """测试大额订单原始数据解析"""
    raw = {
        "id": 12345,
        "exchange_name": "Binance",
        "symbol": "BTCUSDT",
        "price": 89205.9,
        "start_time": 1745287309000,
        "start_quantity": 25.779,
        "start_usd_value": 2299638.89,
        "current_quantity": 20.0,
        "current_usd_value": 1784118.0,
        "executed_volume": 5.779,
        "executed_usd_value": 515520.89,
        "trade_count": 3,
        "order_side": 2,
        "order_state": 1,
    }
    order = _raw_to_order(raw, OrderSource.CEX_FUTURES)
    checks = [
        (order.id == "12345", f"id={order.id}"),
        (order.exchange == "Binance", f"exchange={order.exchange}"),
        (order.side == OrderSide.BUY, f"side={order.side}"),
        (order.price == 89205.9, f"price={order.price}"),
        (order.amount_usd == 1784118.0, f"amount_usd={order.amount_usd} (should use current)"),
        (order.quantity == 20.0, f"quantity={order.quantity} (should use current)"),
        (order.status == OrderStatus.OPEN, f"status={order.status}"),
        (order.source == OrderSource.CEX_FUTURES, f"source={order.source}"),
    ]
    failed = [msg for ok, msg in checks if not ok]
    record("parse_large_order", not failed, "; ".join(failed), order.model_dump())


def test_parse_liquidation_raw():
    """测试爆仓订单原始数据解析"""
    raw = {
        "exchange_name": "BINANCE",
        "symbol": "BTCUSDT",
        "base_asset": "BTC",
        "price": 87535.9,
        "usd_value": 205534.29,
        "side": 2,
        "time": 1745216319263,
    }
    order = _parse_liquidation(raw)
    checks = [
        (order.exchange == "BINANCE", f"exchange={order.exchange}"),
        (order.side == OrderSide.SELL, f"side={order.side}"),
        (order.amount_usd == 205534.29, f"amount_usd={order.amount_usd}"),
        (order.order_type == OrderType.LIQUIDATION, f"type={order.order_type}"),
        (order.status == OrderStatus.FILLED, f"status={order.status}"),
    ]
    failed = [msg for ok, msg in checks if not ok]
    record("parse_liquidation", not failed, "; ".join(failed), order.model_dump())


def test_parse_ws_liquidation():
    """测试 WebSocket 爆仓数据解析"""
    data = [
        {"baseAsset": "BTC", "exName": "Binance", "price": 56738.0, "side": 2,
         "symbol": "BTCUSDT", "time": 1725416318379, "volUsd": 385818.4},
        {"baseAsset": "ETH", "exName": "Binance", "price": 2500.0, "side": 1,
         "symbol": "ETHUSDT", "time": 1725416318380, "volUsd": 50000.0},
    ]
    orders = parse_ws_liquidation(data)
    checks = [
        (len(orders) == 1, f"count={len(orders)}, expected 1 (only BTC)"),
        (orders[0].exchange == "Binance", f"exchange={orders[0].exchange}"),
        (orders[0].amount_usd == 385818.4, f"amount_usd={orders[0].amount_usd}"),
    ]
    failed = [msg for ok, msg in checks if not ok]
    record("parse_ws_liquidation", not failed, "; ".join(failed))


# ═══════════════════════════════════════════════
# 3. 告警引擎测试
# ═══════════════════════════════════════════════

def test_alert_engine():
    """测试告警规则匹配"""
    engine = AlertEngine()

    cases = [
        (
            "6M CEX order -> mega_whale + large_cex_order",
            WhaleOrder(source=OrderSource.CEX_FUTURES, order_type=OrderType.LARGE_LIMIT,
                       exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY,
                       price=95000, amount_usd=6_000_000),
            ["mega_whale", "large_cex_order"],
        ),
        (
            "800K liquidation -> large_liquidation",
            WhaleOrder(source=OrderSource.CEX_FUTURES, order_type=OrderType.LIQUIDATION,
                       exchange="OKX", symbol="BTCUSDT", side=OrderSide.SELL,
                       price=94000, amount_usd=800_000),
            ["large_liquidation"],
        ),
        (
            "3M Hyperliquid -> hyperliquid_whale",
            WhaleOrder(source=OrderSource.DEX_HYPERLIQUID, order_type=OrderType.WHALE_POSITION,
                       exchange="Hyperliquid", symbol="BTC-PERP", side=OrderSide.BUY,
                       price=95000, amount_usd=3_000_000),
            ["hyperliquid_whale"],
        ),
        (
            "15M onchain -> mega_whale + large_onchain",
            WhaleOrder(source=OrderSource.ONCHAIN, order_type=OrderType.CHAIN_TRANSFER,
                       exchange="unknown", symbol="BTC", side=OrderSide.UNKNOWN,
                       price=0, amount_usd=15_000_000),
            ["mega_whale", "large_onchain"],
        ),
        (
            "50K order -> no alerts",
            WhaleOrder(source=OrderSource.CEX_FUTURES, order_type=OrderType.LARGE_LIMIT,
                       exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY,
                       price=95000, amount_usd=50_000),
            [],
        ),
        (
            "400K liquidation -> no alerts (below 500K threshold)",
            WhaleOrder(source=OrderSource.CEX_FUTURES, order_type=OrderType.LIQUIDATION,
                       exchange="Binance", symbol="BTCUSDT", side=OrderSide.SELL,
                       price=90000, amount_usd=400_000),
            [],
        ),
    ]

    alert_data = []
    for desc, order, expected in cases:
        matched = engine.evaluate(order)
        ok = set(matched) == set(expected)
        record(f"alert_{desc[:30]}", ok,
               f"expected={expected}, got={matched}" if not ok else "")
        alert_data.append({"case": desc, "expected": expected, "actual": matched, "pass": ok})
    collected_data["alert_engine_cases"] = alert_data


def test_alert_custom_rule():
    """测试自定义告警规则"""
    engine = AlertEngine()
    engine.add_rule(AlertRule(
        name="binance_sell_only",
        min_amount_usd=100_000,
        exchanges=["Binance"],
        sides=[OrderSide.SELL],
    ))
    o1 = WhaleOrder(source=OrderSource.CEX_FUTURES, order_type=OrderType.LARGE_LIMIT,
                    exchange="Binance", symbol="BTCUSDT", side=OrderSide.SELL,
                    price=90000, amount_usd=200_000)
    o2 = WhaleOrder(source=OrderSource.CEX_FUTURES, order_type=OrderType.LARGE_LIMIT,
                    exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY,
                    price=90000, amount_usd=200_000)
    m1 = engine.evaluate(o1)
    m2 = engine.evaluate(o2)
    record("alert_custom_rule",
           "binance_sell_only" in m1 and "binance_sell_only" not in m2,
           f"sell_match={m1}, buy_match={m2}")


# ═══════════════════════════════════════════════
# 4. 数据库测试
# ═══════════════════════════════════════════════

async def test_database():
    """测试数据库 CRUD 操作"""
    import tempfile
    test_db_path = Path(tempfile.mktemp(suffix=".db"))
    original = get_settings().db_path

    # monkey-patch for test
    db = Database()
    db._db_path = str(test_db_path)
    await db.start()

    o1 = WhaleOrder(source=OrderSource.CEX_FUTURES, order_type=OrderType.LARGE_LIMIT,
                    exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY,
                    price=95000, amount_usd=2_500_000, timestamp=1700000001000)
    o2 = WhaleOrder(source=OrderSource.DEX_HYPERLIQUID, order_type=OrderType.WHALE_POSITION,
                    exchange="Hyperliquid", symbol="BTC-PERP", side=OrderSide.SELL,
                    price=65000, amount_usd=5_000_000, timestamp=1700000002000)
    o3 = WhaleOrder(source=OrderSource.CEX_FUTURES, order_type=OrderType.LIQUIDATION,
                    exchange="OKX", symbol="BTCUSDT", side=OrderSide.SELL,
                    price=90000, amount_usd=800_000, timestamp=1700000003000)

    # insert
    is_new = await db.insert_order(o1)
    record("db_insert_new", is_new, "should be new")

    # duplicate
    is_dup = await db.insert_order(o1)
    record("db_insert_duplicate", not is_dup, "should be duplicate")

    # batch insert
    count = await db.insert_orders([o2, o3])
    record("db_batch_insert", count == 2, f"count={count}, expected 2")

    # query all
    rows = await db.get_recent_orders(limit=10)
    record("db_query_all", len(rows) == 3, f"count={len(rows)}, expected 3", rows)

    # query by source
    rows = await db.get_recent_orders(source="cex_futures")
    record("db_query_source", len(rows) == 2, f"count={len(rows)}, expected 2")

    # query by exchange
    rows = await db.get_recent_orders(exchange="Hyperliquid")
    record("db_query_exchange", len(rows) == 1, f"count={len(rows)}, expected 1")

    # query by min_amount
    rows = await db.get_recent_orders(min_amount=3_000_000)
    record("db_query_min_amount", len(rows) == 1, f"count={len(rows)}, expected 1")

    # stats
    stats = await db.get_stats()
    record("db_stats", stats["total_orders"] == 3,
           f"total={stats['total_orders']}", stats)

    await db.stop()
    test_db_path.unlink(missing_ok=True)


# ═══════════════════════════════════════════════
# 5. 聚合引擎测试
# ═══════════════════════════════════════════════

async def test_aggregator():
    """测试聚合引擎去重与告警分发"""
    import tempfile
    test_db_path = Path(tempfile.mktemp(suffix=".db"))
    db = Database()
    db._db_path = str(test_db_path)
    await db.start()

    alert_log: list[tuple[str, list[str]]] = []

    async def mock_push(order: WhaleOrder, rules: list[str]):
        alert_log.append((order.id, rules))

    engine = AlertEngine()
    agg = Aggregator(db, engine, mock_push)

    o1 = WhaleOrder(source=OrderSource.CEX_FUTURES, order_type=OrderType.LARGE_LIMIT,
                    exchange="Binance", symbol="BTCUSDT", side=OrderSide.BUY,
                    price=95000, amount_usd=6_000_000)

    # first ingest
    await agg.ingest([o1])
    record("agg_ingest_new", agg.stats["new"] == 1, f"new={agg.stats['new']}")
    record("agg_alert_fired", len(alert_log) == 1,
           f"alerts={len(alert_log)}, rules={alert_log[0][1] if alert_log else []}")

    # duplicate ingest
    await agg.ingest([o1])
    record("agg_dedup", agg.stats["new"] == 1, f"new should still be 1, got {agg.stats['new']}")

    # sub-threshold (no alert)
    o2 = WhaleOrder(source=OrderSource.CEX_FUTURES, order_type=OrderType.LARGE_LIMIT,
                    exchange="OKX", symbol="BTCUSDT", side=OrderSide.BUY,
                    price=95000, amount_usd=50_000)
    await agg.ingest([o2])
    record("agg_no_alert_sub_threshold", len(alert_log) == 1,
           f"alert count should be 1, got {len(alert_log)}")

    await db.stop()
    test_db_path.unlink(missing_ok=True)


# ═══════════════════════════════════════════════
# 6. API 客户端真实调用测试
# ═══════════════════════════════════════════════

async def test_api_real():
    """测试 CoinGlass API 真实调用（使用实际 API Key）"""
    client = CoinGlassClient()
    await client.start()

    # supported coins
    try:
        coins = await client.get_supported_coins()
        is_list = isinstance(coins, list)
        has_btc = any("BTC" in str(c).upper() for c in coins) if is_list else False
        record("api_supported_coins", is_list and len(coins) > 0,
               f"count={len(coins) if is_list else 'N/A'}, has_btc={has_btc}")
        collected_data["supported_coins_sample"] = coins[:5] if is_list else coins
    except Exception as e:
        record("api_supported_coins", False, str(e))

    # hyperliquid whale alerts
    try:
        alerts = await client.get_hyperliquid_whale_alerts()
        btc_alerts = [a for a in alerts if a.get("symbol", "").upper() == "BTC"]
        record("api_whale_alerts", isinstance(alerts, list) and len(alerts) > 0,
               f"total={len(alerts)}, btc={len(btc_alerts)}")
        collected_data["whale_alerts_sample"] = btc_alerts[:5]
    except Exception as e:
        record("api_whale_alerts", False, str(e))

    # whale index
    try:
        idx = await client.get_whale_index("Binance", "BTCUSDT", "1h", 10)
        record("api_whale_index", isinstance(idx, list) and len(idx) > 0,
               f"count={len(idx) if isinstance(idx, list) else 'N/A'}")
        collected_data["whale_index_sample"] = idx[:5] if isinstance(idx, list) else idx
    except CoinGlassAPIError as e:
        record("api_whale_index", False, f"API error: {e.message} (may need plan upgrade)")
    except Exception as e:
        record("api_whale_index", False, str(e))

    # large orders (expect upgrade plan error on Startup)
    try:
        orders = await client.get_large_orders("Binance", "BTCUSDT")
        record("api_large_orders", isinstance(orders, list),
               f"count={len(orders)}")
        collected_data["large_orders_sample"] = orders[:3]
    except CoinGlassAPIError as e:
        is_upgrade = "upgrade" in e.message.lower()
        record("api_large_orders", is_upgrade,
               f"Expected 'Upgrade plan' on Startup tier: {e.message}")
    except Exception as e:
        record("api_large_orders", False, str(e))

    # liquidation orders (expect upgrade plan error on Startup)
    try:
        liqs = await client.get_liquidation_orders("Binance", "BTC", 100000)
        record("api_liquidation_orders", isinstance(liqs, list),
               f"count={len(liqs)}")
        collected_data["liquidation_sample"] = liqs[:3]
    except CoinGlassAPIError as e:
        is_upgrade = "upgrade" in e.message.lower()
        record("api_liquidation_orders", is_upgrade,
               f"Expected 'Upgrade plan' on Startup tier: {e.message}")
    except Exception as e:
        record("api_liquidation_orders", False, str(e))

    # chain transfers
    try:
        txs = await client.get_exchange_chain_transfers()
        record("api_chain_transfers", isinstance(txs, list),
               f"count={len(txs) if isinstance(txs, list) else 'N/A'}")
        collected_data["chain_transfers_sample"] = txs[:3] if isinstance(txs, list) else txs
    except CoinGlassAPIError as e:
        record("api_chain_transfers", "upgrade" in e.message.lower(),
               f"Upgrade needed: {e.message}")
    except Exception as e:
        record("api_chain_transfers", False, str(e))

    await client.stop()


# ═══════════════════════════════════════════════
# 7. 采集器端到端测试（真实 API）
# ═══════════════════════════════════════════════

async def test_collector_hyperliquid():
    """测试 Hyperliquid 采集器端到端"""
    client = CoinGlassClient()
    await client.start()

    collected_orders: list[WhaleOrder] = []

    async def capture(orders: list[WhaleOrder]):
        collected_orders.extend(orders)

    collector = HyperliquidWhaleCollector(client, capture)
    orders = await collector.collect()

    record("collector_hl_returns_list", isinstance(orders, list),
           f"type={type(orders)}")
    record("collector_hl_has_data", len(orders) > 0,
           f"count={len(orders)}")

    if orders:
        o = orders[0]
        checks = [
            (o.source == OrderSource.DEX_HYPERLIQUID, f"source={o.source}"),
            (o.exchange == "Hyperliquid", f"exchange={o.exchange}"),
            ("BTC" in o.symbol, f"symbol={o.symbol}"),
            (o.amount_usd > 0, f"amount_usd={o.amount_usd}"),
            (o.price > 0, f"price={o.price}"),
            (o.timestamp > 0, f"timestamp={o.timestamp}"),
            (o.side in (OrderSide.BUY, OrderSide.SELL), f"side={o.side}"),
        ]
        failed = [msg for ok, msg in checks if not ok]
        record("collector_hl_data_quality", not failed, "; ".join(failed))

        collected_data["collector_hl_orders"] = [o.model_dump() for o in orders[:10]]

    await client.stop()


# ═══════════════════════════════════════════════
# 8. 推送层测试
# ═══════════════════════════════════════════════

def test_ws_push_manager():
    """测试 WebSocket 推送管理器"""
    mgr = WebSocketPushManager()
    record("ws_manager_init", mgr.client_count == 0)


# ═══════════════════════════════════════════════
# 9. 配置验证测试
# ═══════════════════════════════════════════════

def test_settings():
    """测试配置加载"""
    s = get_settings()
    checks = [
        (len(s.cg_api_key) == 32, f"api_key_len={len(s.cg_api_key)}"),
        (s.port == 8000, f"port={s.port}"),
        (len(s.exchange_list) >= 1, f"exchanges={s.exchange_list}"),
        (s.large_order_threshold > 0, f"threshold={s.large_order_threshold}"),
        (s.cg_rest_base.startswith("https://"), f"rest_base={s.cg_rest_base}"),
        ("wss://" in s.cg_ws_url, f"ws_url={s.cg_ws_url[:30]}..."),
    ]
    failed = [msg for ok, msg in checks if not ok]
    record("settings_load", not failed, "; ".join(failed), {
        "exchanges": s.exchange_list,
        "thresholds": {"large_order": s.large_order_threshold, "liquidation": s.liquidation_threshold},
        "intervals": {"large_order": s.poll_interval_large_order, "liquidation": s.poll_interval_liquidation},
    })


# ═══════════════════════════════════════════════
# 报告生成
# ═══════════════════════════════════════════════

def generate_report():
    """生成测试报告到桌面"""
    REPORT_DIR.mkdir(exist_ok=True)

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed

    # 1. 测试报告摘要 (TXT)
    report_lines = [
        "=" * 70,
        "  BTC Whale Order Monitor - 测试报告",
        f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 70,
        "",
        f"  总计: {total} 项测试",
        f"  通过: {passed} ✅",
        f"  失败: {failed} ❌",
        f"  通过率: {passed/total*100:.1f}%",
        "",
        "-" * 70,
        "  详细结果:",
        "-" * 70,
    ]
    for r in results:
        status = "✅" if r["passed"] else "❌"
        line = f"  {status} [{r['time']}] {r['test']}"
        if r["detail"]:
            line += f"\n     └─ {r['detail']}"
        report_lines.append(line)

    report_text = "\n".join(report_lines)
    (REPORT_DIR / "test_report.txt").write_text(report_text, encoding="utf-8")

    # 2. 采集到的数据样本 (JSON)
    with open(REPORT_DIR / "collected_data.json", "w", encoding="utf-8") as f:
        json.dump(collected_data, f, ensure_ascii=False, indent=2, default=str)

    # 3. 测试结果原始数据 (JSON)
    with open(REPORT_DIR / "test_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 4. 鲸鱼订单样本 CSV
    hl_orders = collected_data.get("collector_hl_orders", [])
    if hl_orders:
        csv_lines = ["id,source,type,exchange,symbol,side,price,amount_usd,quantity,status,timestamp"]
        for o in hl_orders:
            csv_lines.append(
                f"{o['id']},{o['source']},{o['order_type']},{o['exchange']},"
                f"{o['symbol']},{o['side']},{o['price']},{o['amount_usd']},"
                f"{o['quantity']},{o['status']},{o['timestamp']}"
            )
        (REPORT_DIR / "whale_orders_sample.csv").write_text("\n".join(csv_lines), encoding="utf-8")

    print(f"\n{'=' * 70}")
    print(f"  报告已生成到: {REPORT_DIR}")
    print(f"  - test_report.txt        (测试报告摘要)")
    print(f"  - test_results.json      (测试结果原始数据)")
    print(f"  - collected_data.json    (API 采集数据样本)")
    print(f"  - whale_orders_sample.csv (鲸鱼订单 CSV)")
    print(f"{'=' * 70}")


# ═══════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════

async def main():
    print("=" * 70)
    print("  BTC Whale Order Monitor - 完整测试套件")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    print("\n[1/9] 数据模型测试...")
    test_model_creation()
    test_model_id_deterministic()
    test_model_id_unique()
    test_model_push_payload()
    test_model_summary()
    test_model_enums()

    print("\n[2/9] 数据解析测试...")
    test_parse_side()
    test_parse_state()
    test_parse_large_order_raw()
    test_parse_liquidation_raw()
    test_parse_ws_liquidation()

    print("\n[3/9] 告警引擎测试...")
    test_alert_engine()
    test_alert_custom_rule()

    print("\n[4/9] 数据库测试...")
    await test_database()

    print("\n[5/9] 聚合引擎测试...")
    await test_aggregator()

    print("\n[6/9] API 客户端真实调用测试...")
    await test_api_real()

    print("\n[7/9] 采集器端到端测试...")
    await test_collector_hyperliquid()

    print("\n[8/9] 推送层测试...")
    test_ws_push_manager()

    print("\n[9/9] 配置验证测试...")
    test_settings()

    print("\n生成测试报告...")
    generate_report()


if __name__ == "__main__":
    asyncio.run(main())

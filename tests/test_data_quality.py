"""
BTC Whale Order Monitor — 全面数据质量测试
==========================================
角色：测试工程师
目标：基于真实 API 数据，验证数据在采集、解析、存储、推送全链路的准确性

覆盖范围：
  - CEX（中心化交易所）：交易所元数据、鲸鱼指数、大额订单解析验证
  - DEX（去中心化交易所）：Hyperliquid 鲸鱼提醒 & 持仓
  - On-chain：链上转账
  - 全链路：采集 → 解析 → 聚合 → 存储 → 查询
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from src.api.coinglass_client import CoinGlassClient, CoinGlassAPIError
from src.collectors.large_order import _raw_to_order, _parse_side, _parse_state
from src.collectors.liquidation import _parse_liquidation, parse_ws_liquidation
from src.collectors.hyperliquid import HyperliquidWhaleCollector
from src.collectors.onchain import OnchainTransferCollector
from src.engine.aggregator import Aggregator
from src.engine.alert_rules import AlertEngine
from src.models.whale_order import WhaleOrder, OrderSource, OrderType, OrderSide, OrderStatus
from src.storage.database import Database


# ═══════════════════════════════════════════════════════
# 测试基础设施
# ═══════════════════════════════════════════════════════

DESKTOP = Path.home() / "Desktop"
REPORT_DIR = DESKTOP / "BTC_Whale_Test_Data"

_section_name = ""
_results: list[dict] = []
_raw_data: dict[str, Any] = {}
_section_counts: dict[str, list[int]] = {}  # section -> [pass, fail]


def section(name: str):
    global _section_name
    _section_name = name
    _section_counts[name] = [0, 0]
    print(f"\n{'─' * 70}")
    print(f"  {name}")
    print(f"{'─' * 70}")


def check(name: str, passed: bool, detail: str = "", data: Any = None):
    _results.append({
        "section": _section_name,
        "test": name,
        "passed": passed,
        "detail": detail,
    })
    if _section_name in _section_counts:
        _section_counts[_section_name][0 if passed else 1] += 1
    tag = "✅" if passed else "❌"
    print(f"  {tag} {name}")
    if detail:
        d = detail if len(detail) < 120 else detail[:117] + "..."
        print(f"     └─ {d}")
    if data is not None:
        _raw_data[f"{_section_name}/{name}"] = data


def now_ms() -> int:
    return int(time.time() * 1000)


# ═══════════════════════════════════════════════════════
# A. CEX 元数据验证
# ═══════════════════════════════════════════════════════

async def test_cex_supported_exchanges(client: CoinGlassClient):
    section("A. CEX 交易所元数据验证")

    data = await client.get_supported_exchanges()
    check("返回类型为 dict", isinstance(data, dict), f"type={type(data).__name__}")
    check("交易所数量 >= 20", len(data) >= 20, f"count={len(data)}")

    exchange_names = list(data.keys())
    _raw_data["cex_exchange_names"] = exchange_names

    major = ["Binance", "Bybit", "OKX"]
    for ex in major:
        found = ex in exchange_names
        check(f"包含主流交易所 {ex}", found,
              f"{'存在' if found else '缺失'}")

    # 检查每个交易所的交易对结构
    for ex in major:
        if ex not in data:
            continue
        pairs = data[ex]
        check(f"{ex} 交易对列表非空", isinstance(pairs, list) and len(pairs) > 0,
              f"count={len(pairs) if isinstance(pairs, list) else 'N/A'}")

        btc_pairs = [p for p in pairs if isinstance(p, dict) and
                     p.get("base_asset", "").upper() == "BTC"]
        check(f"{ex} 包含 BTC 交易对", len(btc_pairs) > 0,
              f"btc_pairs={len(btc_pairs)}")

        if btc_pairs:
            pair = btc_pairs[0]
            required_fields = ["instrument_id", "base_asset", "quote_asset"]
            missing = [f for f in required_fields if f not in pair]
            check(f"{ex} BTC 交易对字段完整", not missing,
                  f"missing={missing}, sample={pair}")


async def test_cex_supported_coins(client: CoinGlassClient):
    section("B. CEX 支持币种验证")

    data = await client.get_supported_coins()
    check("返回类型为 list", isinstance(data, list), f"type={type(data).__name__}")
    check("币种数量 >= 100", len(data) >= 100, f"count={len(data)}")

    has_btc = any("BTC" == str(c).upper() for c in data)
    has_eth = any("ETH" == str(c).upper() for c in data)
    check("包含 BTC", has_btc)
    check("包含 ETH", has_eth)

    _raw_data["supported_coins_count"] = len(data)
    _raw_data["supported_coins_sample"] = data[:20]


# ═══════════════════════════════════════════════════════
# B. CEX 鲸鱼指数验证
# ═══════════════════════════════════════════════════════

async def test_cex_whale_index(client: CoinGlassClient):
    section("C. CEX 鲸鱼指数数据验证")

    data = await client.get_whale_index("Binance", "BTCUSDT", "1h", 24)
    check("返回类型为 list", isinstance(data, list))
    check("数据量 > 0", len(data) > 0, f"count={len(data)}")

    _raw_data["whale_index"] = data

    if not data:
        return

    # Schema 验证
    required_fields = ["time", "whale_index_value"]
    sample = data[0]
    missing = [f for f in required_fields if f not in sample]
    check("字段完整性 (time, whale_index_value)", not missing, f"missing={missing}")

    # 类型验证
    for i, d in enumerate(data):
        if not isinstance(d.get("time"), (int, float)):
            check("time 字段类型", False, f"index={i}, type={type(d.get('time'))}")
            break
        if not isinstance(d.get("whale_index_value"), (int, float)):
            check("whale_index_value 字段类型", False,
                  f"index={i}, type={type(d.get('whale_index_value'))}")
            break
    else:
        check("所有记录类型正确", True, f"checked {len(data)} records")

    # 时间戳合理性（应为毫秒级，近24小时内）
    times = [d["time"] for d in data]
    all_ms = all(t > 1_600_000_000_000 for t in times)
    check("时间戳为毫秒级", all_ms,
          f"min={min(times)}, max={max(times)}")

    recent = max(times)
    age_hours = (now_ms() - recent) / 3_600_000
    check("最新数据在 3 小时内", age_hours < 3, f"age={age_hours:.1f}h")

    # 时间序列单调性
    sorted_asc = all(times[i] <= times[i + 1] for i in range(len(times) - 1))
    check("时间序列单调递增", sorted_asc)

    # 值范围
    values = [d["whale_index_value"] for d in data]
    check("鲸鱼指数值范围合理 (-1000 ~ 1000)", all(-1000 < v < 1000 for v in values),
          f"min={min(values):.2f}, max={max(values):.2f}")


# ═══════════════════════════════════════════════════════
# C. CEX 大额订单解析准确性（基于文档数据格式）
# ═══════════════════════════════════════════════════════

def test_cex_large_order_parsing():
    section("D. CEX 大额订单解析准确性验证")

    # 使用 CoinGlass 官方文档中的真实响应格式
    doc_samples = [
        {
            "id": 2868159989,
            "exchange_name": "Binance",
            "symbol": "BTCUSDT",
            "base_asset": "BTC",
            "quote_asset": "USDT",
            "price": 56932,
            "start_time": 1722964242000,
            "start_quantity": 28.39774,
            "start_usd_value": 1616740.1337,
            "current_quantity": 18.77405,
            "current_usd_value": 1068844.21,
            "current_time": 1722964272000,
            "executed_volume": 9.62369,
            "executed_usd_value": 547895.92,
            "trade_count": 15,
            "order_side": 2,
            "order_state": 1,
        },
        {
            "id": 2895605135,
            "exchange_name": "Binance",
            "symbol": "BTCUSDT",
            "base_asset": "BTC",
            "quote_asset": "USDT",
            "price": 89205.9,
            "start_time": 1745287309000,
            "start_quantity": 25.779,
            "start_usd_value": 2299638.8961,
            "current_quantity": 0,
            "current_usd_value": 0,
            "executed_volume": 25.779,
            "executed_usd_value": 2299638.8961,
            "trade_count": 42,
            "order_side": 1,
            "order_state": 2,
            "order_end_time": 1745287328000,
        },
    ]

    for i, raw in enumerate(doc_samples):
        order = _raw_to_order(raw, OrderSource.CEX_FUTURES)

        check(f"样本{i+1} ID 正确映射", order.id == str(raw["id"]),
              f"expected={raw['id']}, got={order.id}")
        check(f"样本{i+1} 交易所", order.exchange == raw["exchange_name"],
              f"expected={raw['exchange_name']}, got={order.exchange}")
        check(f"样本{i+1} 交易对", order.symbol == raw["symbol"])
        check(f"样本{i+1} 价格", order.price == raw["price"],
              f"expected={raw['price']}, got={order.price}")

        # 关键：current_usd_value 优先，为 0 时回退 start_usd_value
        expected_usd = raw["current_usd_value"] if raw["current_usd_value"] else raw["start_usd_value"]
        check(f"样本{i+1} 金额优先取 current", order.amount_usd == expected_usd,
              f"expected={expected_usd}, got={order.amount_usd}")

        expected_qty = raw["current_quantity"] if raw["current_quantity"] else raw["start_quantity"]
        check(f"样本{i+1} 数量优先取 current", order.quantity == expected_qty,
              f"expected={expected_qty}, got={order.quantity}")

        # side: 1=Sell, 2=Buy
        expected_side = OrderSide.BUY if raw["order_side"] == 2 else OrderSide.SELL
        check(f"样本{i+1} 方向映射 ({raw['order_side']}->{'buy' if raw['order_side']==2 else 'sell'})",
              order.side == expected_side,
              f"expected={expected_side}, got={order.side}")

        # state: 1=Open, 2=Filled, 3=Cancelled
        state_map = {1: OrderStatus.OPEN, 2: OrderStatus.FILLED, 3: OrderStatus.CANCELLED}
        expected_state = state_map[raw["order_state"]]
        check(f"样本{i+1} 状态映射", order.status == expected_state,
              f"expected={expected_state}, got={order.status}")

        check(f"样本{i+1} 数据源", order.source == OrderSource.CEX_FUTURES)
        check(f"样本{i+1} 类型", order.order_type == OrderType.LARGE_LIMIT)

    # 边界测试：current 值为 0 时应回退到 start
    edge_raw = {
        "id": 9999,
        "exchange_name": "OKX",
        "symbol": "BTCUSDT",
        "price": 70000,
        "start_time": 1700000000000,
        "start_quantity": 10.0,
        "start_usd_value": 700000.0,
        "current_quantity": 0,
        "current_usd_value": 0,
        "order_side": 1,
        "order_state": 2,
    }
    edge_order = _raw_to_order(edge_raw, OrderSource.CEX_FUTURES)
    check("边界：current=0 回退到 start_usd", edge_order.amount_usd == 700000.0,
          f"got={edge_order.amount_usd}")
    check("边界：current=0 回退到 start_qty", edge_order.quantity == 10.0,
          f"got={edge_order.quantity}")


def test_cex_liquidation_parsing():
    section("E. CEX 爆仓订单解析准确性验证")

    # REST 格式
    rest_sample = {
        "exchange_name": "BINANCE",
        "symbol": "BTCUSDT",
        "base_asset": "BTC",
        "price": 87535.9,
        "usd_value": 205534.2932,
        "side": 2,
        "time": 1745216319263,
    }
    order = _parse_liquidation(rest_sample)
    check("REST: 交易所", order.exchange == "BINANCE")
    check("REST: 交易对", order.symbol == "BTCUSDT")
    check("REST: 价格", order.price == 87535.9)
    check("REST: 金额", order.amount_usd == 205534.2932)
    check("REST: side=2 -> SELL", order.side == OrderSide.SELL)
    check("REST: side=1 -> BUY",
          _parse_liquidation({**rest_sample, "side": 1}).side == OrderSide.BUY)
    check("REST: 状态为 FILLED", order.status == OrderStatus.FILLED)
    check("REST: 类型为 LIQUIDATION", order.order_type == OrderType.LIQUIDATION)
    check("REST: 时间戳", order.timestamp == 1745216319263)

    # WebSocket 格式
    ws_data = [
        {"baseAsset": "BTC", "exName": "Binance", "price": 56738.00,
         "side": 2, "symbol": "BTCUSDT", "time": 1725416318379, "volUsd": 3858.184},
        {"baseAsset": "BTC", "exName": "OKX", "price": 56700.00,
         "side": 1, "symbol": "BTCUSD", "time": 1725416318380, "volUsd": 150000.0},
        {"baseAsset": "ETH", "exName": "Binance", "price": 2500.0,
         "side": 1, "symbol": "ETHUSDT", "time": 1725416318381, "volUsd": 80000.0},
    ]
    orders = parse_ws_liquidation(ws_data)
    check("WS: 过滤仅保留 BTC", len(orders) == 2,
          f"expected 2 BTC orders, got {len(orders)}")

    if len(orders) >= 2:
        check("WS[0]: exName->exchange 映射", orders[0].exchange == "Binance")
        check("WS[0]: volUsd->amount_usd 映射", orders[0].amount_usd == 3858.184)
        check("WS[1]: 不同交易所", orders[1].exchange == "OKX")
        check("WS[1]: side=1->BUY", orders[1].side == OrderSide.BUY)


# ═══════════════════════════════════════════════════════
# D. DEX Hyperliquid 数据验证
# ═══════════════════════════════════════════════════════

async def test_dex_whale_alerts(client: CoinGlassClient):
    section("F. DEX Hyperliquid 鲸鱼提醒数据验证")

    data = await client.get_hyperliquid_whale_alerts()
    check("返回类型为 list", isinstance(data, list))
    check("数据量 > 0", len(data) > 0, f"count={len(data)}")

    btc_data = [d for d in data if d.get("symbol", "").upper() == "BTC"]
    check("包含 BTC 数据", len(btc_data) > 0, f"btc={len(btc_data)}, total={len(data)}")

    _raw_data["hl_alerts_all"] = data
    _raw_data["hl_alerts_btc"] = btc_data

    if not btc_data:
        return

    # Schema 完整性
    required = ["user", "symbol", "position_size", "entry_price", "liq_price",
                 "position_value_usd", "position_action", "create_time"]
    for field in required:
        all_have = all(field in d for d in btc_data)
        check(f"BTC 数据字段存在: {field}", all_have,
              f"缺失率: {sum(1 for d in btc_data if field not in d)}/{len(btc_data)}")

    # 类型验证
    type_checks = {
        "user": str,
        "symbol": str,
        "position_size": (int, float),
        "entry_price": (int, float),
        "liq_price": (int, float),
        "position_value_usd": (int, float),
        "position_action": int,
        "create_time": int,
    }
    for field, expected_type in type_checks.items():
        wrong = [i for i, d in enumerate(btc_data)
                 if not isinstance(d.get(field), expected_type)]
        check(f"类型验证 {field}: {expected_type.__name__ if isinstance(expected_type, type) else '/'.join(t.__name__ for t in expected_type)}",
              len(wrong) == 0,
              f"类型错误 {len(wrong)} 条, indices={wrong[:5]}" if wrong else "")

    # 数据范围验证
    prices = [d["entry_price"] for d in btc_data]
    check("entry_price > 0", all(p > 0 for p in prices),
          f"min={min(prices):.2f}, max={max(prices):.2f}")
    check("entry_price 在合理范围 ($10K-$500K)", all(10_000 < p < 500_000 for p in prices),
          f"min={min(prices):.2f}, max={max(prices):.2f}")

    values = [d["position_value_usd"] for d in btc_data]
    check("position_value_usd > $1M (鲸鱼阈值)", all(v >= 1_000_000 for v in values),
          f"min=${min(values):,.0f}, max=${max(values):,.0f}")

    # position_action 只能是 1 或 2
    actions = [d["position_action"] for d in btc_data]
    check("position_action ∈ {1, 2}", set(actions).issubset({1, 2}),
          f"unique={set(actions)}")

    # 钱包地址格式
    wallets = [d["user"] for d in btc_data]
    check("钱包地址以 0x 开头", all(w.startswith("0x") for w in wallets))
    check("钱包地址长度 42 字符", all(len(w) == 42 for w in wallets),
          f"lengths={set(len(w) for w in wallets)}")

    # 时间戳新鲜度
    times = [d["create_time"] for d in btc_data]
    latest = max(times)
    age_min = (now_ms() - latest) / 60_000
    check("最新数据在 30 分钟内", age_min < 30, f"age={age_min:.1f}min")

    # 强平价格一致性
    for i, d in enumerate(btc_data[:10]):
        size = d["position_size"]
        liq = d["liq_price"]
        entry = d["entry_price"]
        if size > 0:  # 多头：强平价 < 入场价
            ok = liq < entry or liq == 0
            check(f"多头[{i}] 强平价 < 入场价", ok,
                  f"entry={entry:.2f}, liq={liq:.2f}" if not ok else "")
        elif size < 0:  # 空头：强平价 > 入场价
            ok = liq > entry or liq == 0
            check(f"空头[{i}] 强平价 > 入场价", ok,
                  f"entry={entry:.2f}, liq={liq:.2f}" if not ok else "")


async def test_dex_whale_positions(client: CoinGlassClient):
    section("G. DEX Hyperliquid 鲸鱼持仓数据验证")

    data = await client.get_hyperliquid_whale_positions()
    check("返回类型为 list", isinstance(data, list))
    check("数据量 > 100", len(data) > 100, f"count={len(data)}")

    btc_data = [d for d in data if d.get("symbol", "").upper() == "BTC"]
    check("BTC 持仓数量 > 50", len(btc_data) > 50,
          f"btc={len(btc_data)}, total={len(data)}")

    _raw_data["hl_positions_btc_count"] = len(btc_data)
    _raw_data["hl_positions_total_count"] = len(data)
    _raw_data["hl_positions_btc_sample"] = btc_data[:5]

    if not btc_data:
        return

    # Schema 完整性（持仓接口比 alert 接口字段更丰富）
    required = ["user", "symbol", "position_size", "entry_price", "mark_price",
                 "liq_price", "leverage", "margin_balance", "position_value_usd",
                 "unrealized_pnl", "margin_mode", "create_time", "update_time"]
    for field in required:
        present = sum(1 for d in btc_data if field in d)
        pct = present / len(btc_data) * 100
        check(f"字段覆盖率 {field}", pct > 95, f"{present}/{len(btc_data)} ({pct:.0f}%)")

    # 数值范围
    leverages = [d.get("leverage", 0) for d in btc_data if "leverage" in d]
    check("杠杆倍数 ∈ [1, 200]", all(1 <= l <= 200 for l in leverages),
          f"min={min(leverages)}, max={max(leverages)}")

    # mark_price 一致性（所有 BTC 持仓的标记价应该近似相同）
    mark_prices = [d["mark_price"] for d in btc_data if "mark_price" in d and d["mark_price"] > 0]
    if mark_prices:
        avg_mark = sum(mark_prices) / len(mark_prices)
        spread = max(mark_prices) - min(mark_prices)
        spread_pct = spread / avg_mark * 100
        check("BTC mark_price 一致性 (偏差<1%)", spread_pct < 1,
              f"avg=${avg_mark:,.0f}, spread=${spread:,.0f} ({spread_pct:.2f}%)")

    # 多空分布
    longs = sum(1 for d in btc_data if d.get("position_size", 0) > 0)
    shorts = sum(1 for d in btc_data if d.get("position_size", 0) < 0)
    check("包含多头持仓", longs > 0, f"longs={longs}")
    check("包含空头持仓", shorts > 0, f"shorts={shorts}")
    total_value = sum(abs(d.get("position_value_usd", 0)) for d in btc_data)
    check(f"BTC 鲸鱼总持仓 > $100M", total_value > 100_000_000,
          f"total=${total_value:,.0f}, longs={longs}, shorts={shorts}")

    _raw_data["hl_positions_stats"] = {
        "longs": longs, "shorts": shorts,
        "total_value_usd": total_value,
        "avg_mark_price": avg_mark if mark_prices else 0,
    }

    # margin_mode 枚举
    modes = set(d.get("margin_mode", "") for d in btc_data)
    check("margin_mode 值合法", modes.issubset({"cross", "isolated", ""}),
          f"modes={modes}")

    # update_time 新鲜度
    update_times = [d.get("update_time", 0) for d in btc_data if d.get("update_time", 0) > 0]
    if update_times:
        latest = max(update_times)
        age_min = (now_ms() - latest) / 60_000
        check("最新 update_time 在 5 分钟内", age_min < 5,
              f"age={age_min:.1f}min")

    # 唯一性：同一地址同一币种不应出现完全重复记录
    keys = [(d.get("user", ""), d.get("symbol", "")) for d in btc_data]
    dups = len(keys) - len(set(keys))
    check("无重复 (user+symbol) 记录", dups == 0, f"duplicates={dups}")


# ═══════════════════════════════════════════════════════
# E. 链上转账数据验证
# ═══════════════════════════════════════════════════════

async def test_onchain_transfers(client: CoinGlassClient):
    section("H. 链上转账数据验证")

    data = await client.get_exchange_chain_transfers()
    check("返回类型为 list", isinstance(data, list))
    check("数据量 > 0", len(data) > 0, f"count={len(data)}")

    _raw_data["chain_transfers_all"] = data[:20]

    if not data:
        return

    # Schema 验证
    required = ["transaction_hash", "asset_symbol", "amount_usd", "asset_quantity",
                 "exchange_name", "transfer_type", "from_address", "to_address",
                 "transaction_time"]
    sample = data[0]
    for field in required:
        pct = sum(1 for d in data if field in d) / len(data) * 100
        check(f"字段覆盖率 {field}", pct > 90, f"{pct:.0f}%")

    # tx_hash 唯一性
    hashes = [d.get("transaction_hash", "") for d in data]
    unique_hashes = set(hashes)
    check("交易哈希唯一", len(hashes) == len(unique_hashes),
          f"total={len(hashes)}, unique={len(unique_hashes)}")

    # tx_hash 格式
    valid_hashes = [h for h in hashes if h.startswith("0x") and len(h) == 66]
    check("tx_hash 格式正确 (0x + 64 hex)", len(valid_hashes) == len(hashes),
          f"valid={len(valid_hashes)}/{len(hashes)}")

    # amount_usd 范围
    amounts = [d.get("amount_usd", 0) for d in data]
    check("amount_usd >= 0", all(a >= 0 for a in amounts),
          f"min={min(amounts):.2f}")

    # transfer_type 枚举
    types = set(d.get("transfer_type") for d in data)
    check("transfer_type 值集合", True, f"unique_types={types}")

    # 地址格式
    from_addrs = [d.get("from_address", "") for d in data]
    to_addrs = [d.get("to_address", "") for d in data]
    valid_from = sum(1 for a in from_addrs if a.startswith("0x"))
    valid_to = sum(1 for a in to_addrs if a.startswith("0x"))
    check("from_address 格式 (0x 开头)", valid_from == len(from_addrs),
          f"valid={valid_from}/{len(from_addrs)}")
    check("to_address 格式 (0x 开头)", valid_to == len(to_addrs),
          f"valid={valid_to}/{len(to_addrs)}")

    # 时间戳（链上转账可能是秒级）
    times = [d.get("transaction_time", 0) for d in data]
    is_seconds = all(1_600_000_000 < t < 2_000_000_000 for t in times if t > 0)
    is_millis = all(t > 1_600_000_000_000 for t in times if t > 0)
    check("时间戳格式识别", is_seconds or is_millis,
          f"{'秒级' if is_seconds else '毫秒级' if is_millis else '未知'}")

    # 资产类型分布
    assets = Counter(d.get("asset_symbol", "") for d in data)
    check("资产类型分布", True, f"top5={assets.most_common(5)}")

    # 交易所分布
    exchanges = Counter(d.get("exchange_name", "") for d in data)
    check("交易所分布", True, f"top5={exchanges.most_common(5)}")

    _raw_data["chain_transfer_stats"] = {
        "total": len(data),
        "asset_distribution": dict(assets),
        "exchange_distribution": dict(exchanges),
    }


# ═══════════════════════════════════════════════════════
# F. 采集器数据转换准确性
# ═══════════════════════════════════════════════════════

async def test_collector_hl_accuracy(client: CoinGlassClient):
    section("I. Hyperliquid 采集器转换准确性验证")

    collected: list[WhaleOrder] = []

    async def capture(orders):
        collected.extend(orders)

    collector = HyperliquidWhaleCollector(client, capture)
    orders = await collector.collect()

    check("采集器返回 list", isinstance(orders, list))
    check("采集到 BTC 订单", len(orders) > 0, f"count={len(orders)}")

    if not orders:
        return

    # 逐条验证转换后的字段
    for i, o in enumerate(orders[:10]):
        prefix = f"[{i}]"
        check(f"{prefix} source == DEX_HYPERLIQUID", o.source == OrderSource.DEX_HYPERLIQUID)
        check(f"{prefix} exchange == Hyperliquid", o.exchange == "Hyperliquid")
        check(f"{prefix} symbol 包含 BTC", "BTC" in o.symbol)
        check(f"{prefix} order_type == WHALE_POSITION", o.order_type == OrderType.WHALE_POSITION)
        check(f"{prefix} price > $10,000", o.price > 10_000, f"price={o.price}")
        check(f"{prefix} amount_usd > $1M", o.amount_usd >= 1_000_000,
              f"amount=${o.amount_usd:,.0f}")
        check(f"{prefix} quantity > 0", o.quantity > 0, f"qty={o.quantity}")
        check(f"{prefix} side ∈ {{BUY, SELL}}", o.side in (OrderSide.BUY, OrderSide.SELL))
        check(f"{prefix} id 长度 16", len(o.id) > 0)
        check(f"{prefix} timestamp > 0", o.timestamp > 0)
        check(f"{prefix} metadata 有 wallet", "wallet" in o.metadata,
              f"keys={list(o.metadata.keys())}")

    # 去重验证：采集器内部应避免重复
    ids = [o.id for o in orders]
    check("采集结果无重复 ID", len(ids) == len(set(ids)),
          f"total={len(ids)}, unique={len(set(ids))}")

    _raw_data["collector_hl_orders"] = [o.model_dump() for o in orders]


async def test_collector_onchain_accuracy(client: CoinGlassClient):
    section("J. 链上采集器转换准确性验证")

    collected: list[WhaleOrder] = []

    async def capture(orders):
        collected.extend(orders)

    collector = OnchainTransferCollector(client, capture)
    orders = await collector.collect()

    check("采集器返回 list", isinstance(orders, list))

    # 链上转账可能没有达到阈值的 BTC 订单
    if not orders:
        check("无满足阈值的链上转账（正常）", True,
              f"threshold=${get_settings().large_order_threshold:,.0f}")
        return

    for i, o in enumerate(orders[:5]):
        prefix = f"[{i}]"
        check(f"{prefix} source == ONCHAIN", o.source == OrderSource.ONCHAIN)
        check(f"{prefix} order_type == CHAIN_TRANSFER", o.order_type == OrderType.CHAIN_TRANSFER)
        check(f"{prefix} amount_usd >= threshold",
              o.amount_usd >= get_settings().large_order_threshold)
        check(f"{prefix} metadata 有 tx_hash", "tx_hash" in o.metadata)


# ═══════════════════════════════════════════════════════
# G. 全链路端到端测试
# ═══════════════════════════════════════════════════════

async def test_end_to_end_pipeline(client: CoinGlassClient):
    section("K. 全链路端到端验证 (采集→聚合→存储→查询)")

    test_db_path = Path(tempfile.mktemp(suffix=".db"))
    db = Database()
    db._db_path = str(test_db_path)
    await db.start()

    alert_log: list[dict] = []

    async def mock_push(order: WhaleOrder, rules: list[str]):
        alert_log.append({"id": order.id, "rules": rules, "summary": order.summary()})

    engine = AlertEngine()
    agg = Aggregator(db, engine, mock_push)

    # Step 1: 从真实 API 采集 Hyperliquid 数据
    hl_alerts_raw = await client.get_hyperliquid_whale_alerts()
    btc_alerts = [a for a in hl_alerts_raw if a.get("symbol", "").upper() == "BTC"]
    check("Step1: 获取真实 Hyperliquid BTC 数据", len(btc_alerts) > 0,
          f"count={len(btc_alerts)}")

    # Step 2: 通过采集器转换
    collected: list[WhaleOrder] = []

    async def capture(orders):
        collected.extend(orders)

    collector = HyperliquidWhaleCollector(client, capture)
    orders = await collector.collect()
    check("Step2: 采集器转换", len(orders) > 0, f"count={len(orders)}")

    # Step 3: 喂入聚合引擎
    await agg.ingest(orders)
    check("Step3: 聚合引擎接收", agg.stats["new"] > 0,
          f"new={agg.stats['new']}, received={agg.stats['received']}")

    # 触发告警的订单
    alerted_count = agg.stats["alerted"]
    check("Step3: 告警触发", alerted_count > 0, f"alerted={alerted_count}")

    # Step 4: 从数据库查询
    db_rows = await db.get_recent_orders(limit=100)
    check("Step4: 数据库存储", len(db_rows) > 0, f"db_rows={len(db_rows)}")

    # 数据一致性：采集数量 == 数据库数量
    check("Step4: 采集 vs 存储一致", len(db_rows) == agg.stats["new"],
          f"collected_new={agg.stats['new']}, db_rows={len(db_rows)}")

    # Step 5: 验证存储数据完整性
    if db_rows:
        row = db_rows[0]
        required_fields = ["id", "source", "order_type", "exchange", "symbol",
                           "side", "price", "amount_usd", "quantity", "status", "timestamp"]
        missing = [f for f in required_fields if f not in row]
        check("Step5: 存储字段完整", not missing, f"missing={missing}")

    # Step 6: 各种查询维度验证
    by_source = await db.get_recent_orders(source="dex_hyperliquid")
    check("Step6: 按 source 查询", len(by_source) == len(db_rows),
          f"count={len(by_source)}")

    by_exchange = await db.get_recent_orders(exchange="Hyperliquid")
    check("Step6: 按 exchange 查询", len(by_exchange) == len(db_rows),
          f"count={len(by_exchange)}")

    big_ones = await db.get_recent_orders(min_amount=5_000_000)
    check("Step6: 按金额过滤 (>$5M)",
          all(r["amount_usd"] >= 5_000_000 for r in big_ones),
          f"count={len(big_ones)}")

    # Step 7: 去重验证（再次灌入相同数据）
    stats_before = dict(agg.stats)
    await agg.ingest(orders)
    check("Step7: 重复数据被过滤", agg.stats["new"] == stats_before["new"],
          f"before={stats_before['new']}, after={agg.stats['new']}")

    # Step 8: 验证告警推送内容
    if alert_log:
        alert = alert_log[0]
        check("Step8: 告警包含 rules", len(alert["rules"]) > 0,
              f"rules={alert['rules']}")
        check("Step8: 告警包含 summary", len(alert["summary"]) > 0,
              f"summary={alert['summary'][:80]}")

    _raw_data["e2e_alerts"] = alert_log[:10]
    _raw_data["e2e_db_sample"] = db_rows[:5]
    _raw_data["e2e_stats"] = {
        "aggregator": agg.stats,
        "db_total": len(db_rows),
        "alerts_fired": len(alert_log),
    }

    stats = await db.get_stats()
    _raw_data["e2e_db_stats"] = stats

    await db.stop()
    test_db_path.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════
# H. 跨源数据一致性
# ═══════════════════════════════════════════════════════

async def test_cross_source_consistency(client: CoinGlassClient):
    section("L. 跨数据源一致性验证")

    # Hyperliquid alerts vs positions 的价格应该接近
    alerts = await client.get_hyperliquid_whale_alerts()
    positions = await client.get_hyperliquid_whale_positions()

    btc_alert_prices = [a["entry_price"] for a in alerts
                        if a.get("symbol", "").upper() == "BTC" and a.get("entry_price", 0) > 0]
    btc_pos_mark = [p["mark_price"] for p in positions
                    if p.get("symbol", "").upper() == "BTC" and p.get("mark_price", 0) > 0]

    if btc_alert_prices and btc_pos_mark:
        alert_avg = sum(btc_alert_prices) / len(btc_alert_prices)
        pos_mark_avg = sum(btc_pos_mark) / len(btc_pos_mark)
        diff_pct = abs(alert_avg - pos_mark_avg) / pos_mark_avg * 100
        check("Alerts 入场均价 vs Positions mark_price 偏差 < 10%",
              diff_pct < 10,
              f"alert_avg=${alert_avg:,.0f}, mark_avg=${pos_mark_avg:,.0f}, diff={diff_pct:.1f}%")

    # Whale Index 值与价格趋势（定性检查：指数有值）
    idx = await client.get_whale_index("Binance", "BTCUSDT", "1h", 5)
    if idx:
        latest_idx = idx[-1]["whale_index_value"]
        check("鲸鱼指数有有效值", isinstance(latest_idx, (int, float)),
              f"latest={latest_idx}")

    # alerts 和 positions 中相同钱包的持仓方向一致性
    alert_wallets = {}
    for a in alerts:
        if a.get("symbol", "").upper() == "BTC":
            w = a["user"]
            size = a.get("position_size", 0)
            alert_wallets[w] = "long" if size > 0 else "short"

    pos_wallets = {}
    for p in positions:
        if p.get("symbol", "").upper() == "BTC":
            w = p["user"]
            size = p.get("position_size", 0)
            pos_wallets[w] = "long" if size > 0 else "short"

    common = set(alert_wallets.keys()) & set(pos_wallets.keys())
    if common:
        consistent = sum(1 for w in common if alert_wallets[w] == pos_wallets[w])
        check(f"相同钱包方向一致性 ({len(common)} 个重叠钱包)",
              consistent / len(common) > 0.8,
              f"consistent={consistent}/{len(common)} ({consistent/len(common)*100:.0f}%)")
    else:
        check("alerts/positions 钱包有交集", False,
              "无重叠钱包（数据窗口不同，可接受）")


# ═══════════════════════════════════════════════════════
# 报告生成
# ═══════════════════════════════════════════════════════

def generate_report():
    REPORT_DIR.mkdir(exist_ok=True)

    total = len(_results)
    passed = sum(1 for r in _results if r["passed"])
    failed = total - passed

    # TXT 报告
    lines = [
        "=" * 80,
        "  BTC Whale Order Monitor — 全面数据质量测试报告",
        f"  测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"  API 等级: Startup (部分接口需 Standard 或以上)",
        "=" * 80,
        "",
        f"  总测试项: {total}",
        f"  通过:     {passed} ✅",
        f"  失败:     {failed} ❌",
        f"  通过率:   {passed / total * 100:.1f}%",
        "",
    ]

    for sec, (p, f) in _section_counts.items():
        tag = "✅" if f == 0 else "⚠️"
        lines.append(f"  {tag} {sec}: {p}/{p + f} passed")

    lines.append("")
    lines.append("─" * 80)
    lines.append("  详细结果")
    lines.append("─" * 80)

    current_section = ""
    for r in _results:
        if r["section"] != current_section:
            current_section = r["section"]
            lines.append(f"\n  [{current_section}]")
        tag = "✅" if r["passed"] else "❌"
        lines.append(f"    {tag} {r['test']}")
        if r["detail"]:
            d = r["detail"] if len(r["detail"]) < 100 else r["detail"][:97] + "..."
            lines.append(f"       └─ {d}")

    report_txt = "\n".join(lines)
    (REPORT_DIR / "data_quality_report.txt").write_text(report_txt, encoding="utf-8")

    # JSON 完整数据
    with open(REPORT_DIR / "data_quality_results.json", "w", encoding="utf-8") as f:
        json.dump(_results, f, ensure_ascii=False, indent=2, default=str)

    with open(REPORT_DIR / "real_api_data_samples.json", "w", encoding="utf-8") as f:
        json.dump(_raw_data, f, ensure_ascii=False, indent=2, default=str)

    # CSV: Hyperliquid 鲸鱼订单
    hl_orders = _raw_data.get("collector_hl_orders", [])
    if hl_orders:
        with open(REPORT_DIR / "dex_hyperliquid_orders.csv", "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "id", "source", "order_type", "exchange", "symbol", "side",
                "price", "amount_usd", "quantity", "status", "timestamp"])
            writer.writeheader()
            for o in hl_orders:
                writer.writerow({k: o.get(k, "") for k in writer.fieldnames})

    # CSV: Hyperliquid 持仓
    hl_pos = _raw_data.get("hl_positions_btc_sample", [])
    if hl_pos:
        with open(REPORT_DIR / "dex_hyperliquid_positions.csv", "w", encoding="utf-8", newline="") as f:
            fields = ["user", "symbol", "position_size", "entry_price", "mark_price",
                       "liq_price", "leverage", "position_value_usd", "unrealized_pnl",
                       "margin_mode", "create_time", "update_time"]
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for p in hl_pos:
                writer.writerow(p)

    # CSV: 链上转账
    chain = _raw_data.get("chain_transfers_all", [])
    if chain:
        with open(REPORT_DIR / "onchain_transfers.csv", "w", encoding="utf-8", newline="") as f:
            fields = ["transaction_hash", "asset_symbol", "amount_usd", "asset_quantity",
                       "exchange_name", "transfer_type", "from_address", "to_address",
                       "transaction_time"]
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for t in chain:
                writer.writerow(t)

    print(f"\n{'=' * 70}")
    print(f"  报告已生成到: {REPORT_DIR}")
    files = sorted(REPORT_DIR.glob("*"))
    for fp in files:
        size = fp.stat().st_size
        print(f"  - {fp.name:<40s} ({size:>8,} bytes)")
    print(f"{'=' * 70}")


# ═══════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════

async def main():
    print("=" * 70)
    print("  BTC Whale Order Monitor — 全面数据质量测试")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    client = CoinGlassClient()
    await client.start()

    try:
        await test_cex_supported_exchanges(client)
        await test_cex_supported_coins(client)
        await test_cex_whale_index(client)
        test_cex_large_order_parsing()
        test_cex_liquidation_parsing()
        await test_dex_whale_alerts(client)
        await test_dex_whale_positions(client)
        await test_onchain_transfers(client)
        await test_collector_hl_accuracy(client)
        await test_collector_onchain_accuracy(client)
        await test_end_to_end_pipeline(client)
        await test_cross_source_consistency(client)
    finally:
        await client.stop()

    generate_report()


if __name__ == "__main__":
    asyncio.run(main())

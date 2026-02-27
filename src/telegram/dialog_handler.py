"""Dialog handler for Telegram Bot natural language queries."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.storage.user_database import UserDatabase
    from src.storage.database import Database
    from src.ai.analyzer import AIAnalyzer

from config.settings import get_settings
from src.models.user import User

logger = logging.getLogger(__name__)


class DialogHandler:
    """Handles natural language conversations with users."""

    def __init__(
        self,
        user_db: "UserDatabase",
        db: "Database",
        ai_analyzer: "AIAnalyzer",
    ) -> None:
        self.user_db = user_db
        self.db = db
        self.ai_analyzer = ai_analyzer
        self.settings = get_settings()

    async def handle_message(
        self, user: User, message: str
    ) -> str:
        """Handle a user's natural language message."""
        if not self.settings.deepseek_api_key:
            return "AI 分析功能尚未配置。请联系管理员。"

        # Save message to history
        await self.user_db.add_chat_message(
            user.telegram_id, "user", message
        )

        try:
            # Parse user intent
            intent, params = await self._parse_intent(message)

            # Fetch data based on intent
            if intent == "stats":
                response = await self._handle_stats_query(user, params)
            elif intent == "trend":
                response = await self._handle_trend_query(params)
            elif intent == "recent":
                response = await self._handle_recent_query(user, params)
            elif intent == "analyze":
                response = await self._handle_analyze_query(params)
            else:
                # Use AI to answer general questions
                response = await self._handle_general_query(
                    user, message, params
                )

            # Save assistant response to history
            await self.user_db.add_chat_message(
                user.telegram_id, "assistant", response
            )

            return response

        except Exception as e:
            logger.error("Dialog handler error: %s", e, exc_info=True)
            return "抱歉，处理您的请求时出现错误。请稍后重试。"

    async def _parse_intent(
        self, message: str
    ) -> tuple[str, dict]:
        """Parse user intent from natural language message."""
        message_lower = message.lower()

        # Pattern matching for common intents
        if any(
            word in message_lower
            for word in ["统计", "stats", "数据", "多少单"]
        ):
            return "stats", await self._extract_params(message, ["hours", "exchange"])

        elif any(
            word in message_lower
            for word in ["趋势", "trend", "行情", "市场"]
        ):
            return "trend", await self._extract_params(
                message, ["hours", "exchange", "symbol"]
            )

        elif any(
            word in message_lower for word in ["最近", "recent", "最新", "大单"]
        ):
            return "recent", await self._extract_params(
                message, ["hours", "exchange", "count"]
            )

        elif any(
            word in message_lower
            for word in ["分析", "analyze", "影响", "怎么看"]
        ):
            return "analyze", await self._extract_params(
                message, ["hours", "exchange"]
            )

        else:
            # General query - use AI
            return "general", {
                "raw_message": message,
                "hours": 24,  # Default 24 hours
            }

    async def _extract_params(
        self, message: str, keys: list[str]
    ) -> dict:
        """Extract parameters from message."""
        params = {}

        # Extract time range (hours)
        time_patterns = [
            r"(\d+)\s*(小时|hour|hr)",
            r"(\d+)\s*(分钟|min)",
            r"(\d+)\s*(天|day)",
        ]
        for pattern in time_patterns:
            match = re.search(pattern, message)
            if match:
                value = int(match.group(1))
                if "小时" in match.group(2) or "hour" in match.group(2):
                    params["hours"] = value
                elif "分钟" in match.group(2) or "min" in match.group(2):
                    params["hours"] = value / 60
                elif "天" in match.group(2) or "day" in match.group(2):
                    params["hours"] = value * 24
                break

        # Extract exchange
        exchanges = ["binance", "okx", "bybit", "bitget", "coinbase"]
        for exchange in exchanges:
            if exchange.lower() in message.lower():
                params["exchange"] = exchange.capitalize()
                break

        # Extract count (for recent queries)
        count_match = re.search(r"(\d+)\s*(笔|条|个)", message)
        if count_match:
            params["count"] = min(int(count_match.group(1)), 50)

        return params

    async def _handle_stats_query(
        self, user: User, params: dict
    ) -> str:
        """Handle statistics query."""
        hours = params.get("hours", 1)
        exchange = params.get("exchange")

        summary = await self.ai_analyzer.get_market_summary(hours=hours)

        response = f"*📊 市场统计（过去 {hours} 小时）*\n\n"
        response += f"📈 **总订单数:** {summary['total_orders']}\n"
        response += f"💰 **平均金额:** ${summary['avg_amount_usd']:,.0f}\n"
        response += f"🟢 **买入比例:** {summary['buy_ratio']}%\n"
        response += f"🔴 **卖出比例:** {summary['sell_ratio']}%\n\n"

        if summary.get("top_exchanges"):
            response += "*🏆 活跃交易所 TOP5:*\n"
            for exc in summary["top_exchanges"]:
                response += f"   • {exc['name']}: {exc['count']} 单 (${exc['total']:,.0f})\n"

        # Use AI to generate insights
        market_data = {
            "summary": summary,
            "period_hours": hours,
        }
        ai_insight = await self.ai_analyzer.deepseek.answer_query(
            "总结一下这个市场的趋势", market_data
        )

        response += f"\n*🤖 AI 洞察:*\n{ai_insight}"

        return response

    async def _handle_trend_query(self, params: dict) -> str:
        """Handle trend analysis query."""
        hours = params.get("hours", 1)
        exchange = params.get("exchange")

        summary = await self.ai_analyzer.get_market_summary(hours=hours)

        if exchange:
            response = f"*📈 {exchange} 趋势分析（过去 {hours} 小时）*\n\n"
        else:
            response = f"*📈 整体市场趋势（过去 {hours} 小时）*\n\n"

        # Trend analysis based on buy/sell ratio
        buy_ratio = summary["buy_ratio"]

        if buy_ratio > 55:
            trend = "📈 看涨 - 买盘强势"
        elif buy_ratio < 45:
            trend = "📉 看跌 - 卖盘强势"
        else:
            trend = "➡️ 震荡 - 多空平衡"

        response += f"**趋势判断:** {trend}\n\n"
        response += f"📊 买入: {summary['buy_ratio']}%\n"
        response += f"📊 卖出: {summary['sell_ratio']}%\n"
        response += f"📊 总订单: {summary['total_orders']}\n"

        return response

    async def _handle_recent_query(
        self, user: User, params: dict
    ) -> str:
        """Handle recent orders query."""
        hours = params.get("hours", 1)
        exchange = params.get("exchange")
        count = params.get("count", 5)

        orders = await self.ai_analyzer.fetch_orders_for_query(
            source=None, exchange=exchange, hours=hours
        )

        recent_orders = orders[:count]

        if not recent_orders:
            return f"过去 {hours} 小时内未找到符合条件的订单。"

        response = f"*📋 最近 {len(recent_orders)} 笔大单（过去 {hours} 小时）*\n\n"

        for order in recent_orders:
            emoji = "🟢" if order.side.value == "buy" else "🔴"
            direction = "买入" if order.side.value == "buy" else "卖出"
            response += f"{emoji} **{order.exchange}** {direction} ${order.amount_usd:,.0f}\n"
            response += f"   {order.symbol} @ ${order.price:,.2f}\n"
            response += f"   {order.order_type.value}\n\n"

        return response

    async def _handle_analyze_query(self, params: dict) -> str:
        """Handle market analysis query."""
        hours = params.get("hours", 1)
        exchange = params.get("exchange")

        orders = await self.ai_analyzer.fetch_orders_for_query(
            source=None, exchange=exchange, hours=hours
        )

        if not orders:
            return f"过去 {hours} 小时内未找到足够的订单数据进行分析。"

        # Build market data for AI
        summary = await self.ai_analyzer.get_market_summary(hours=hours)

        if exchange:
            market_data = {
                "exchange": exchange,
                "period_hours": hours,
                "total_orders": summary["total_orders"],
                "buy_ratio": summary["buy_ratio"],
                "sell_ratio": summary["sell_ratio"],
                "avg_amount": summary["avg_amount_usd"],
            }
            question = f"分析一下 {exchange} 交易所的市场情况"
        else:
            market_data = {
                "period_hours": hours,
                "total_orders": summary["total_orders"],
                "buy_ratio": summary["buy_ratio"],
                "sell_ratio": summary["sell_ratio"],
                "avg_amount": summary["avg_amount_usd"],
            }
            question = "分析一下整体市场情况"

        # Use AI for deep analysis
        response = await self.ai_analyzer.deepseek.answer_query(
            question, market_data
        )

        return f"*🤖 市场分析（过去 {hours} 小时）*\n\n{response}"

    async def _handle_general_query(
        self, user: User, message: str, params: dict
    ) -> str:
        """Handle general queries using AI."""
        hours = params.get("hours", 24)

        # Fetch market data
        summary = await self.ai_analyzer.get_market_summary(hours=hours)

        market_data = {
            "user_query": message,
            "period_hours": hours,
            "market_summary": summary,
        }

        # Use AI to answer
        response = await self.ai_analyzer.deepseek.answer_query(
            message, market_data
        )

        return response

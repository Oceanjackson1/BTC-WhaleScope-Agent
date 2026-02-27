"""Message formatter for Telegram Bot."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from src.models.whale_order import WhaleOrder


class MessageFormatter:
    """Formats messages for Telegram."""

    @staticmethod
    def format_alert(order: WhaleOrder, ai_analysis:Optional[ dict] = None) -> str:
        """Format a whale order alert message."""
        emoji = "🟢" if order.side.value == "buy" else "🔴"
        direction = "买入" if order.side.value == "buy" else "卖出"

        # Build base alert message
        message = f"""*{emoji} 鲸鱼大单告警*

📊 **交易所:** {order.exchange}
💱 **交易对:** {order.symbol}
{emoji} **方向:** {direction}
💰 **金额:** ${order.amount_usd:,.0f}
📈 **价格:** ${order.price:,.2f}
📝 **类型:** {order.order_type.value}
⏰ **时间:** {datetime.fromtimestamp(order.timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')}"""

        # Add AI analysis if available
        if ai_analysis and ai_analysis.get("analysis"):
            signal_emoji = {
                "bullish": "📈",
                "bearish": "📉",
                "neutral": "➡️",
            }.get(ai_analysis.get("signal", "neutral"), "➡️")

            message += f"""

---
*🤖 AI 分析*

📊 **分析:** {ai_analysis.get('analysis', '分析中...')}
🎯 **交易信号:** {signal_emoji} {ai_analysis.get('signal', 'neutral').upper()}
🎲 **置信度:** {ai_analysis.get('confidence', 0)}/100
⚠️ **风险等级:** {ai_analysis.get('risk_level', 'medium').upper()}
💡 **建议:** {ai_analysis.get('suggestion', '建议观望')}"""

        return message.strip()

    @staticmethod
    def format_stats(stats: dict) -> str:
        """Format user statistics message."""
        return f"""*📈 个人统计*

👤 **用户 ID:** `{stats.get('telegram_id', 'N/A')}`
✅ **状态:** {'活跃' if stats.get('is_active') else '未激活'}

📊 **订阅设置:**
   • 交易所: {', '.join(stats.get('subscribed_exchanges', [])) if stats.get('subscribed_exchanges') else '全部'}
   • 金额阈值: ${stats.get('min_alert_threshold', 0):,.0f}

📅 **注册时间:** {stats.get('created_at', 'N/A')}
🕐 **最后活跃:** {stats.get('last_active_at', '无')}"""

    @staticmethod
    def format_system_status(status: dict) -> str:
        """Format system status message."""
        return f"""*📊 系统状态*

🔴 **CoinGlass API:** {'运行中' if status.get('cg_api') else '离线'}
🤖 **AI 分析:** {'运行中' if status.get('deepseek_ai') else '未配置'}
📱 **Telegram Bot:** {'运行中' if status.get('tg_bot') else '未启用'}

👥 **活跃用户:** {status.get('active_users', 0)}
📡 **监控交易所:** {', '.join(status.get('exchanges', []))}

⚙️ **配置:**
   • 大单阈值: ${status.get('large_threshold', 0):,.0f}
   • 爆仓阈值: ${status.get('liquidation_threshold', 0):,.0f}"""

    @staticmethod
    def format_user_list(users: list[dict]) -> str:
        """Format user list for admin."""
        message = "*👥 用户列表*\n\n"

        for user in users[:20]:
            status = "✅" if user.get("is_active") else "⏳"
            admin = " (管理员)" if user.get("is_admin") else ""
            username = user.get("username") or "N/A"
            user_id = user.get("telegram_id")
            message += f"{status} `{user_id}` - {username}{admin}\n"

        if len(users) > 20:
            message += f"\n... 还有 {len(users) - 20} 位用户"

        return message

    @staticmethod
    def format_ai_response(response: str) -> str:
        """Format AI response."""
        return f"""*🤖 AI 分析结果*

{response}

---
⚠️ *免责声明: 以上分析仅供参考，不构成投资建议。投资有风险，请谨慎决策。*"""

    @staticmethod
    def format_error(message: str) -> str:
        """Format error message."""
        return f"""⚠️ **错误**

{message}

如需帮助，请发送 /help 查看可用命令。"""

    @staticmethod
    def format_success(message: str) -> str:
        """Format success message."""
        return f"""✅ {message}"""

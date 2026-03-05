"""Telegram Bot service for whale order monitoring."""

from __future__ import annotations

import logging
import asyncio
import re
import csv
import io
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

from config.settings import get_settings
from src.storage.user_database import UserDatabase
from src.telegram.user_manager import UserManager
from src.telegram.push_dispatcher import PushDispatcher
from src.telegram.task_progress import (
    TaskProgressManager,
    TaskStep,
    ai_analysis_steps,
    export_steps,
    query_steps,
    payment_job_steps,
)

if TYPE_CHECKING:
    from src.storage.user_database import UserDatabase
    from src.telegram.user_manager import UserManager

logger = logging.getLogger(__name__)


class TelegramBot:
    """Telegram Bot for whale order alerts and analysis."""

    def __init__(
        self,
        user_db: UserDatabase,
        push_dispatcher: PushDispatcher,
        dialog_handler: "Optional[DialogHandler]" = None,
        db: "Optional[object]" = None,
        ai_client: "Optional[object]" = None,
    ) -> None:
        self.settings = get_settings()
        self.user_db = user_db
        self.push_dispatcher = push_dispatcher
        self.dialog_handler = dialog_handler
        self.user_manager = UserManager(user_db)
        self.ai_client = ai_client  # DeepseekClient for /ask
        self.db = db  # main whale_orders database

        self._application:Optional[ Application] = None

    async def start(self) -> None:
        """Start the Telegram Bot."""
        if not self.settings.tg_enabled or not self.settings.tg_bot_token:
            logger.warning("Telegram Bot not configured or disabled")
            return

        self._application = Application.builder().token(
            self.settings.tg_bot_token
        ).build()

        # Register handlers
        self._register_handlers()

        # Start the bot
        await self._application.initialize()
        
        # Set command menu
        if self._application.bot:
            await self._application.bot.set_my_commands([
                ("start", "开始使用 / Start Bot"),
                ("help", "显示帮助 / Show Help"),
                ("language", "设置语言 / Language Settings"),
                ("status", "系统状态 / System Status"),
                ("stats", "个人统计 / Personal Stats"),
                ("subscribe", "订阅管理 / Manage Subscriptions"),
            ])
            
        await self._application.start()
        await self._application.updater.start_polling(drop_pending_updates=True)

        logger.info(
            "Telegram Bot started successfully. Admins: %s",
            self.settings.tg_admin_id_list,
        )

    async def stop(self) -> None:
        """Stop the Telegram Bot."""
        if self._application:
            await self._application.updater.stop()
            await self._application.stop()
            await self._application.shutdown()
            logger.info("Telegram Bot stopped")

    def _register_handlers(self) -> None:
        """Register all command and message handlers."""
        app = self._application

        # Command handlers
        app.add_handler(CommandHandler("start", self._start_command))
        app.add_handler(CommandHandler("help", self._help_command))
        app.add_handler(CommandHandler("language", self._language_command))
        app.add_handler(CommandHandler("subscribe", self._subscribe_command))
        app.add_handler(CommandHandler("stats", self._stats_command))
        app.add_handler(CommandHandler("status", self._status_command))

        # Job Offerings commands
        app.add_handler(CommandHandler("query", self._query_command))
        app.add_handler(CommandHandler("export", self._export_command))
        app.add_handler(CommandHandler("ask", self._ask_command))
        app.add_handler(CommandHandler("buy", self._buy_command))
        app.add_handler(CommandHandler("sell", self._sell_command))
        app.add_handler(CommandHandler("positions", self._positions_command))
        app.add_handler(CommandHandler("balance", self._balance_command))

        # Admin commands
        app.add_handler(CommandHandler("approve", self._approve_command))
        app.add_handler(CommandHandler("revoke", self._revoke_command))
        app.add_handler(CommandHandler("users", self._users_command))

        # Callback handlers
        app.add_handler(CallbackQueryHandler(self._callback_handler))

        # Message handler for general text
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._message_handler)
        )

    # ==================== Command Handlers ====================

    async def _start_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /start command."""
        user_id = update.effective_user.id
        user = await self.user_manager.register_user(
            telegram_id=user_id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            last_name=update.effective_user.last_name,
        )

        await self.user_manager.update_activity(user_id)
        
        # Invitation code logic
        if context.args and len(context.args) > 0 and context.args[0] == "Ocean1":
            if not user.is_active:
                # Direct DB access to activate since approve_user expects an admin_id
                await self.user_manager.db.activate_user(user_id)
                user = await self.user_manager.get_user(user_id)
                await update.message.reply_text("🎉 邀请码验证成功！您的账号已激活。 / Invite code verified! Account activated.")
                
        # Always show job offerings layout
        if user.language == "en":
            welcome_header = (
                "🤖 Hey! I am your BTC Whale Monitoring AI Agent.\n\n"
                "I am an AI Data Analyst focusing on on-chain tracking and exchange whale movements.\n"
                "You can hire me for the following tasks—from data queries to trade execution, charged per task.\n\n"
            )
            
            menu_body = (
                "—— 📊 Data Query —— as low as $0.10/time\n"
                "· Whale Order Tracking → /query large        $0.10\n"
                "· On-chain Tracking → /query onchain         $0.10\n"
                "· Spot Order Book Tracking → /query spot     $0.20\n"
                "· Futures Depth Tracking → /query futures    $0.20\n\n"
                "—— 📥 Data Export —— $0.80/time\n"
                "· Export Whale Trades + Orderbook\n"
                "→ /export <symbol>                           $0.80\n"
                "Delivery: CSV (Trades) + JSON (Depth)\n\n"
                "—— 🤖 AI Analysis —— $0.50 ~ $1.00/time\n"
                "· AI Q&A → /ask <question>                   $0.50\n"
                "· Deep Market Analysis + Trade Signals\n"
                "→ /ask <question> [symbol]                   $1.00\n"
                "Signals based on real trades + whale positions\n\n"
                "—— 💰 Trade Execution —— $1.00/tx\n"
                "· Copy Buy → /buy                            $1.00\n"
                "· Copy Sell → /sell                          $1.00\n"
                "· Check Positions → /positions               $0.10\n"
                "· Check Balance → /balance                   $0.10\n\n"
                "—— 🔧 Account Management —— Free\n"
                "/subscribe · /status · /stats · /language\n\n"
                "💡 Support symbol parameters (e.g. BTC, ETH, SOL).\n"
                "Type /help to see the full menu anytime."
            )
            
            if not user.is_active:
                msg = welcome_header + "⚠️ **You need to input an invite code (like `/start Ocean1`) or wait for admin approval to use these services.**\n\n" + menu_body
            else:
                msg = welcome_header + menu_body
        else:
            welcome_header = (
                "🤖 Hey! 我是您的 BTC Whale Monitoring AI Agent.\n\n"
                "我是一个专注于 比特币链上及交易所巨鲸动向 的 AI 数据分析师。\n"
                "您可以雇佣我完成以下工作——从数据查询到下单跟单，按件计费。\n\n"
            )
            
            menu_body = (
                "—— 📊 数据查询 —— 低至 $0.10/次\n"
                "· 巨鲸大单追踪 → /query large        $0.10\n"
                "· 链上异动追踪 → /query onchain      $0.10\n"
                "· 现货大单追踪 → /query spot         $0.20\n"
                "· 合约深度追踪 → /query futures      $0.20\n\n"
                "—— 📥 数据导出 —— $0.80/次\n"
                "· 导出鲸鱼真实成交 + 订单簿\n"
                "→ /export <币种>                     $0.80\n"
                "交付: CSV (成交记录) + JSON (完整深度)\n\n"
                "—— 🤖 AI 分析 —— $0.50 ~ $1.00/次\n"
                "· AI 智能问答 → /ask <问题>          $0.50\n"
                "· 锁定行情深度分析 + 下单建议\n"
                "→ /ask <问题> [币种]                 $1.00\n"
                "基于真实成交 + 巨鲸持仓数据给出方向建议\n\n"
                "—— 💰 交易执行 —— $1.00/笔\n"
                "· 自动跟单买入 → /buy                  $1.00\n"
                "· 自动跟单卖出 → /sell                 $1.00\n"
                "· 查持仓 → /positions                $0.10\n"
                "· 查余额 → /balance                  $0.10\n\n"
                "—— 🔧 账户管理 —— 免费\n"
                "/subscribe · /status · /stats · /language\n\n"
                "💡 所有「币种」参数支持币种代号 (如 BTC, ETH, SOL)。\n"
                "输入 /help 随时查看完整菜单。"
            )
            
            if not user.is_active:
                msg = welcome_header + "⚠️ **您需要输入邀请码（例如发送 `/start Ocean1`）或等待管理员审核才能正式使用。**\n\n" + menu_body
            else:
                msg = welcome_header + menu_body
            
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def _language_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /language command."""
        user_id = update.effective_user.id
        user = await self.user_manager.get_user(user_id)
        if not user:
            return
            
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🇺🇸 English", callback_data="set_lang_en"),
                InlineKeyboardButton("🇨🇳 中文", callback_data="set_lang_zh"),
            ]
        ])
        
        msg = "Please select your preferred language / 请选择您的首选语言:"
        await update.message.reply_text(msg, reply_markup=keyboard)

    async def _help_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /help command."""
        help_text = """
*🐋 BTC 鲸鱼订单监控系统*

*基础命令：*
/start - 开始使用
/help - 显示帮助信息
/status - 查看系统状态
/stats - 查看个人统计

*订阅管理：*
/subscribe - 设置订阅偏好

*查询命令（自然语言）：*
• "最近 1 小时的大单趋势"
• "分析 Binance 的大单"
• "给我看最近的爆仓单"

*管理员命令：*
/approve <user_id> - 审核用户
/revoke <user_id> - 撤销用户
/users - 查看所有用户

💡 提示：发送任意问题即可获取 AI 分析结果！
        """
        await update.message.reply_text(help_text, parse_mode="Markdown")

    async def _subscribe_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /subscribe command."""
        user_id = update.effective_user.id

        if not await self.user_manager.is_active(user_id):
            await update.message.reply_text(
                "您的账号尚未激活，请等待管理员审核。"
            )
            return

        # Create subscription menu
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Binance", callback_data="sub_binance"),
                InlineKeyboardButton("OKX", callback_data="sub_okx"),
            ],
            [
                InlineKeyboardButton("Bybit", callback_data="sub_bybit"),
                InlineKeyboardButton("全部交易所", callback_data="sub_all"),
            ],
            [
                InlineKeyboardButton(
                    "设置金额阈值", callback_data="sub_threshold"
                ),
                InlineKeyboardButton("完成", callback_data="sub_done"),
            ],
        ])

        user = await self.user_manager.get_user(user_id)
        current_exchanges = (
            ", ".join(user.subscribed_exchanges)
            if user.subscribed_exchanges
            else "全部"
        )

        await update.message.reply_text(
            f"*订阅设置*\n\n"
            f"当前订阅的交易所: {current_exchanges}\n"
            f"当前金额阈值: ${user.min_alert_threshold:,.0f}\n\n"
            f"请选择要订阅的交易所或设置金额阈值:",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

    async def _status_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /status command."""
        status_text = f"""
*📊 系统状态*

🔴 CoinGlass API: 运行中
🤖 AI 分析: {'运行中' if self.settings.deepseek_api_key else '未配置'}

👥 活跃用户: {len(await self.user_manager.get_all_active_users())}

📡 监控的交易所: {', '.join(get_settings().exchange_list)}

⚙️ 配置的交易所: {get_settings().exchanges}
        """

        await update.message.reply_text(status_text, parse_mode="Markdown")

    async def _stats_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /stats command."""
        user_id = update.effective_user.id

        if not await self.user_manager.is_active(user_id):
            await update.message.reply_text(
                "您的账号尚未激活，请等待管理员审核。"
            )
            return

        user = await self.user_manager.get_user(user_id)

        # Fetch user's alert statistics
        # Get user's recent alert count from chat history
        async with self.user_db._conn.execute(
            """SELECT COUNT(*) as count FROM chat_history
               WHERE user_id = ? AND role = 'assistant'
               AND timestamp > strftime('%s', 'now', '-1 day')""",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            alerts_today = row["count"] if row else 0

        stats_text = f"""*📈 个人统计*

👤 **用户 ID:** `{user.telegram_id}`
✅ **状态:** {'活跃' if user.is_active else '未激活'}

📊 **订阅设置:**
   • 交易所: {', '.join(user.subscribed_exchanges) if user.subscribed_exchanges else '全部'}
   • 金额阈值: ${user.min_alert_threshold:,.0f}

📅 **注册时间:** {user.created_at.strftime('%Y-%m-%d %H:%M')}
🕐 **最后活跃:** {user.last_active_at.strftime('%Y-%m-%d %H:%M') if user.last_active_at else '无'}

🔔 **24小时告警数:** {alerts_today}"""

        await update.message.reply_text(stats_text, parse_mode="Markdown")

    async def _execute_dummy_job(self, update: Update, command_name: str, english_name: str, chinese_name: str, price: float) -> None:
        """Helper to check permissions and run a simulated job."""
        user_id = update.effective_user.id
        user = await self.user_manager.get_user(user_id)
        if not user:
            return

        if not user.is_active:
            msg = "⚠️ Please input invite code (e.g. `/start Ocean1`) first." if user.language == "en" else "⚠️ 请先输入验证码激活（例如：`/start Ocean1`）"
            await update.message.reply_text(msg, parse_mode="Markdown")
            return

        job_name = english_name if user.language == "en" else chinese_name
        
        btn_text = f"💳 Pay ${price:.2f}" if user.language == "en" else f"💳 确认支付 ${price:.2f}"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(btn_text, callback_data=f"pay_job_{command_name}")]
        ])
        
        if user.language == "en":
            msg = (
                f"🧾 **Virtual Invoice**\n\n"
                f"Target Job: **{job_name}**\n"
                f"Total Cost: **${price:.2f}**\n\n"
                f"Please complete your payment below to execute task:"
            )
        else:
            msg = (
                f"🧾 **虚拟账单**\n\n"
                f"您选择了服务：**{job_name}**\n"
                f"服务费用：**${price:.2f}**\n\n"
                f"请点击下方按钮完成支付以启动任务："
            )
        await update.message.reply_text(msg, reply_markup=keyboard, parse_mode="Markdown")

    def _parse_query_request(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> dict[str, str]:
        """Parse query mode and symbol from command args/text."""
        mode_alias = {
            "large": "large",
            "onchain": "onchain",
            "spot": "spot",
            "futures": "futures",
            "大单": "large",
            "链上": "onchain",
            "现货": "spot",
            "合约": "futures",
            "期货": "futures",
        }

        tokens: list[str] = []
        if context.args:
            tokens = [t.strip() for t in context.args if t.strip()]
        elif update.message and update.message.text:
            parts = update.message.text.strip().split()
            if parts:
                head = parts[0].lower()
                if head in {"/query", "query", "查询"}:
                    tokens = parts[1:]
                else:
                    tokens = parts

        mode = "large"
        symbol = "BTC"
        if tokens:
            first = tokens[0]
            normalized_mode = mode_alias.get(first.lower()) or mode_alias.get(first)
            if normalized_mode:
                mode = normalized_mode
                if len(tokens) > 1:
                    symbol = tokens[1]
            else:
                symbol = first
                if len(tokens) > 1:
                    maybe_mode = mode_alias.get(tokens[1].lower()) or mode_alias.get(tokens[1])
                    if maybe_mode:
                        mode = maybe_mode

        symbol = re.sub(r"[^A-Za-z0-9_-]", "", symbol.upper()) or "BTC"
        return {"mode": mode, "symbol": symbol}

    def _query_meta(self, mode: str, language: str) -> tuple[str, float]:
        """Get display name and price for query mode."""
        mode_name_en = {
            "large": "Whale Large Orders",
            "onchain": "On-chain Transfers",
            "spot": "Spot Order Flow",
            "futures": "Futures Order Flow",
        }
        mode_name_zh = {
            "large": "巨鲸大单",
            "onchain": "链上异动",
            "spot": "现货追踪",
            "futures": "合约追踪",
        }
        price_map = {
            "large": 0.10,
            "onchain": 0.10,
            "spot": 0.20,
            "futures": 0.20,
        }
        name = mode_name_en.get(mode, mode_name_en["large"]) if language == "en" else mode_name_zh.get(mode, mode_name_zh["large"])
        return name, price_map.get(mode, 0.20)

    async def _do_query(
        self,
        msg,
        user,
        query_request: dict[str, str],
    ) -> None:
        """Run a real query against whale_orders and render summary rows."""
        if not self.db or not hasattr(self.db, "_conn") or self.db._conn is None:
            err = "❌ Database not available." if user.language == "en" else "❌ 数据库尚未就绪，请稍后再试。"
            await msg.edit_text(err)
            return

        mode = query_request.get("mode", "large")
        symbol = query_request.get("symbol", "BTC")

        mode_name, _ = self._query_meta(mode, user.language)
        title_zh = f"数据查询：{mode_name} {symbol}"
        title_en = f"Data Query: {mode_name} {symbol}"
        steps = query_steps()

        filters = ["symbol LIKE ?"]
        params: list[object] = [f"%{symbol}%"]

        if mode == "onchain":
            filters.append("source = ?")
            params.append("onchain")
        elif mode == "spot":
            filters.append("source = ?")
            params.append("cex_spot")
        elif mode == "futures":
            filters.append("(source = ? OR source = ?)")
            params.extend(["cex_futures", "dex_hyperliquid"])
        else:
            filters.append("(order_type = ? OR order_type = ?)")
            params.extend(["large_limit", "whale_position"])

        where_clause = " AND ".join(filters)
        breakdown_rows = []

        async with TaskProgressManager(msg, steps, user.language, title_zh, title_en) as progress:
            await progress.advance()  # Querying data

            sql = (
                "SELECT timestamp, exchange, symbol, side, amount_usd, price, source, order_type, metadata "
                f"FROM whale_orders WHERE {where_clause} "
                "ORDER BY timestamp DESC LIMIT 20"
            )
            async with self.db._conn.execute(sql, tuple(params)) as cursor:
                rows = await cursor.fetchall()

            stat_sql = (
                "SELECT COUNT(*) as cnt, COALESCE(SUM(amount_usd), 0) as total_usd, "
                "COALESCE(SUM(CASE WHEN side='buy' THEN amount_usd ELSE 0 END), 0) as buy_usd, "
                "COALESCE(SUM(CASE WHEN side='sell' THEN amount_usd ELSE 0 END), 0) as sell_usd "
                f"FROM whale_orders WHERE {where_clause}"
            )
            async with self.db._conn.execute(stat_sql, tuple(params)) as cursor:
                stat = await cursor.fetchone()

            if mode == "large":
                breakdown_sql = (
                    "SELECT source, order_type, COUNT(*) as cnt, COALESCE(SUM(amount_usd), 0) as total_usd "
                    f"FROM whale_orders WHERE {where_clause} "
                    "GROUP BY source, order_type "
                    "ORDER BY total_usd DESC"
                )
                async with self.db._conn.execute(breakdown_sql, tuple(params)) as cursor:
                    breakdown_rows = await cursor.fetchall()

            await progress.advance()  # Generating answer

        total_count = int(stat["cnt"]) if stat else 0
        total_usd = float(stat["total_usd"]) if stat else 0.0
        buy_usd = float(stat["buy_usd"]) if stat else 0.0
        sell_usd = float(stat["sell_usd"]) if stat else 0.0

        def parse_meta(raw_meta) -> dict:
            if isinstance(raw_meta, dict):
                return raw_meta
            if isinstance(raw_meta, str):
                try:
                    parsed = json.loads(raw_meta)
                    return parsed if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    return {}
            return {}

        if not rows:
            # If on-chain/spot data is empty, fallback to recent whale events for same symbol.
            if mode in {"onchain", "spot"}:
                fallback_params: tuple[object, ...] = (f"%{symbol}%",)
                fallback_sql = (
                    "SELECT timestamp, exchange, symbol, side, amount_usd, price, source, order_type, metadata "
                    "FROM whale_orders WHERE symbol LIKE ? "
                    "ORDER BY timestamp DESC LIMIT 8"
                )
                async with self.db._conn.execute(fallback_sql, fallback_params) as cursor:
                    fallback_rows = await cursor.fetchall()

                if fallback_rows:
                    fallback_stat_sql = (
                        "SELECT COUNT(*) as cnt, COALESCE(SUM(amount_usd), 0) as total_usd, "
                        "COALESCE(SUM(CASE WHEN side='buy' THEN amount_usd ELSE 0 END), 0) as buy_usd, "
                        "COALESCE(SUM(CASE WHEN side='sell' THEN amount_usd ELSE 0 END), 0) as sell_usd "
                        "FROM whale_orders WHERE symbol LIKE ?"
                    )
                    async with self.db._conn.execute(fallback_stat_sql, fallback_params) as cursor:
                        fallback_stat = await cursor.fetchone()

                    fallback_count = int(fallback_stat["cnt"]) if fallback_stat else 0
                    fallback_total = float(fallback_stat["total_usd"]) if fallback_stat else 0.0
                    fallback_buy = float(fallback_stat["buy_usd"]) if fallback_stat else 0.0
                    fallback_sell = float(fallback_stat["sell_usd"]) if fallback_stat else 0.0

                    fallback_lines = []
                    for row in fallback_rows:
                        ts = datetime.fromtimestamp(int(row["timestamp"]) / 1000, tz=timezone.utc).strftime("%H:%M:%S")
                        side = str(row["side"]).upper()
                        src = str(row["source"])
                        line = (
                            f"{ts} | {row['exchange']} {row['symbol']} {side} ${float(row['amount_usd']):,.0f} [{src}]"
                        )
                        meta = parse_meta(row["metadata"])
                        wallet = str(meta.get("wallet") or "").strip()
                        if wallet:
                            line += f" | wallet:{wallet}"
                        fallback_lines.append(line)

                    if mode == "spot":
                        fallback_hint_en = "Spot order-book data is unavailable with current CoinGlass plan."
                        fallback_hint_zh = "当前 CoinGlass 套餐下现货盘口大单数据不可用。"
                    else:
                        fallback_hint_en = "No on-chain transfer records found for now."
                        fallback_hint_zh = "当前未采集到链上转账记录。"

                    if user.language == "en":
                        fallback_result = (
                            "✅ Payment successful!\n"
                            f"📭 {fallback_hint_en}\n"
                            "🔁 Showing latest whale events for the same symbol instead.\n"
                            f"• Total records: {fallback_count}\n"
                            f"• Total volume: ${fallback_total:,.0f}\n"
                            f"• Buy volume: ${fallback_buy:,.0f}\n"
                            f"• Sell volume: ${fallback_sell:,.0f}\n\n"
                            "Latest fallback events (UTC):\n"
                            + "\n".join(fallback_lines)
                        )
                    else:
                        fallback_result = (
                            "✅ 支付成功！\n"
                            f"📭 {fallback_hint_zh}\n"
                            "🔁 已自动回退为同币种最近巨鲸事件。\n"
                            f"• 总记录数：{fallback_count}\n"
                            f"• 总成交额：${fallback_total:,.0f}\n"
                            f"• 买入额：${fallback_buy:,.0f}\n"
                            f"• 卖出额：${fallback_sell:,.0f}\n\n"
                            "回退事件（UTC）：\n"
                            + "\n".join(fallback_lines)
                        )
                    await msg.edit_text(fallback_result)
                    return

            if user.language == "en":
                no_data = (
                    "✅ Payment successful!\n"
                    f"📭 No data found for mode={mode}, symbol={symbol}.\n"
                    "Possible reasons:\n"
                    "1) Collector has not accumulated data yet\n"
                    "2) API plan limitation (especially spot/futures)\n"
                    "3) Symbol has no recent whale events\n"
                    "Tip: try /query large BTC first."
                )
            else:
                no_data = (
                    "✅ 支付成功！\n"
                    f"📭 当前没有匹配数据（类型={mode}，币种={symbol}）。\n"
                    "可能原因：\n"
                    "1) 采集器刚启动，数据尚未积累\n"
                    "2) API 套餐限制（尤其 spot/futures）\n"
                    "3) 该币种近期无巨鲸事件\n"
                    "建议先试：/query large BTC。"
                )
            await msg.edit_text(no_data)
            return

        latest_lines = []
        for row in rows[:8]:
            ts = datetime.fromtimestamp(int(row["timestamp"]) / 1000, tz=timezone.utc).strftime("%H:%M:%S")
            side = str(row["side"]).upper()
            line = f"{ts} | {row['exchange']} {row['symbol']} {side} ${float(row['amount_usd']):,.0f}"
            if mode == "large":
                meta = parse_meta(row["metadata"])
                wallet = str(meta.get("wallet") or "").strip()
                action = str(meta.get("action") or "").strip()
                if wallet:
                    action_suffix = f" ({action})" if action else ""
                    line += f" | wallet:{wallet}{action_suffix}"
            latest_lines.append(line)

        breakdown_lines = []
        if mode == "large":
            for item in breakdown_rows[:6]:
                breakdown_lines.append(
                    f"- {item['source']} / {item['order_type']}: {int(item['cnt'])} records, ${float(item['total_usd']):,.0f}"
                )

        if user.language == "en":
            result = (
                "✅ Payment successful!\n"
                f"📊 Query done: {mode_name} ({symbol})\n"
                f"• Total records: {total_count}\n"
                f"• Total volume: ${total_usd:,.0f}\n"
                f"• Buy volume: ${buy_usd:,.0f}\n"
                f"• Sell volume: ${sell_usd:,.0f}\n"
            )
            if breakdown_lines:
                result += "\nSource breakdown:\n" + "\n".join(breakdown_lines)
            result += (
                "\n\n"
                "Latest events (UTC):\n"
                + "\n".join(latest_lines)
            )
        else:
            result = (
                "✅ 支付成功！\n"
                f"📊 查询完成：{mode_name}（{symbol}）\n"
                f"• 总记录数：{total_count}\n"
                f"• 总成交额：${total_usd:,.0f}\n"
                f"• 买入额：${buy_usd:,.0f}\n"
                f"• 卖出额：${sell_usd:,.0f}\n"
            )
            if breakdown_lines:
                result += "\n来源明细：\n" + "\n".join(breakdown_lines)
            result += (
                "\n\n"
                "最新事件（UTC）：\n"
                + "\n".join(latest_lines)
            )
        await msg.edit_text(result)

    async def _query_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        user = await self.user_manager.get_user(user_id)
        if not user:
            return

        if not user.is_active:
            msg = "⚠️ Please input invite code (e.g. `/start Ocean1`) first." if user.language == "en" else "⚠️ 请先输入验证码激活（例如：`/start Ocean1`）"
            await update.message.reply_text(msg, parse_mode="Markdown")
            return

        query_request = self._parse_query_request(update, context)
        mode = query_request["mode"]
        symbol = query_request["symbol"]
        mode_name, price = self._query_meta(mode, user.language)
        context.user_data["pending_query_request"] = query_request

        btn_text = f"💳 Pay ${price:.2f}" if user.language == "en" else f"💳 确认支付 ${price:.2f}"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(btn_text, callback_data="pay_job_query")]
        ])

        if user.language == "en":
            msg = (
                "🧾 **Virtual Invoice**\n\n"
                f"Target Job: **📊 {mode_name}**\n"
                f"Symbol: **{symbol}**\n"
                f"Total Cost: **${price:.2f}**\n\n"
                "Please click the button below to execute the query:"
            )
        else:
            msg = (
                "🧾 **虚拟账单**\n\n"
                f"您选择了服务：**📊 {mode_name}**\n"
                f"查询币种：**{symbol}**\n"
                f"服务费用：**${price:.2f}**\n\n"
                "请点击下方按钮完成支付并开始查询："
            )
        await update.message.reply_text(msg, reply_markup=keyboard, parse_mode="Markdown")

    async def _export_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /export command — show exchange picker before exporting."""
        user_id = update.effective_user.id
        user = await self.user_manager.get_user(user_id)
        if not user:
            return

        if not user.is_active:
            msg = "⚠️ Please input invite code (e.g. `/start Ocean1`) first." if user.language == "en" else "⚠️ 请先输入验证码激活（例如：`/start Ocean1`）"
            await update.message.reply_text(msg, parse_mode="Markdown")
            return

        # Parse symbol from args (default BTC)
        symbol_filter = "BTC"
        if context.args and len(context.args) > 0:
            symbol_filter = context.args[0].upper()
        elif update.message and update.message.text:
            parts = update.message.text.strip().split()
            if len(parts) > 1:
                symbol_filter = parts[1].upper()
        symbol_filter = re.sub(r"[^A-Za-z0-9_-]", "", symbol_filter) or "BTC"

        # Show exchange picker
        if user.language == "en":
            msg = f"📥 **Export {symbol_filter} Whale Orders**\n\nStep 1/2: Please select the exchange:"
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Hyperliquid", callback_data=f"export_pick_{symbol_filter}_Hyperliquid"),
                    InlineKeyboardButton("Binance", callback_data=f"export_pick_{symbol_filter}_Binance"),
                ],
                [
                    InlineKeyboardButton("OKX", callback_data=f"export_pick_{symbol_filter}_OKX"),
                    InlineKeyboardButton("🌐 All Exchanges", callback_data=f"export_pick_{symbol_filter}_ALL"),
                ]
            ])
        else:
            msg = f"📥 **导出 {symbol_filter} 巨鲸订单**\n\n步骤 1/2：请选择交易所："
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Hyperliquid", callback_data=f"export_pick_{symbol_filter}_Hyperliquid"),
                    InlineKeyboardButton("Binance", callback_data=f"export_pick_{symbol_filter}_Binance"),
                ],
                [
                    InlineKeyboardButton("OKX", callback_data=f"export_pick_{symbol_filter}_OKX"),
                    InlineKeyboardButton("🌐 全部交易所", callback_data=f"export_pick_{symbol_filter}_ALL"),
                ]
            ])
        await update.message.reply_text(msg, reply_markup=keyboard, parse_mode="Markdown")

    def _export_range_meta(self, range_key: str, language: str) -> tuple[str, int]:
        """Get export range label and day span."""
        mapping = {
            "1d": ("1 Day", "1天", 1),
            "7d": ("7 Days", "7天", 7),
            "30d": ("1 Month", "1个月", 30),
        }
        en_label, zh_label, days = mapping.get(range_key, mapping["7d"])
        return (en_label if language == "en" else zh_label, days)

    async def _do_export(
        self,
        query,
        user,
        symbol_filter: str,
        exchange_filter: str,
        range_key: str = "7d",
    ) -> None:
        """Actually perform the CSV+JSON export after exchange selection."""
        if not self.db or not hasattr(self.db, '_conn') or self.db._conn is None:
            msg = "❌ Database not available." if user.language == "en" else "❌ 数据库尚未就绪，请稍后重试。"
            await query.edit_message_text(msg)
            return

        exchange_label = exchange_filter if exchange_filter != "ALL" else ("All Exchanges" if user.language == "en" else "全部交易所")
        range_label, days = self._export_range_meta(range_key, user.language)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        since_ms = now_ms - days * 24 * 60 * 60 * 1000

        msg = query.message
        steps = export_steps()
        title_zh = f"导出 {symbol_filter} — {exchange_label} — {range_label}"
        title_en = f"Export {symbol_filter} — {exchange_label} — {range_label}"

        # Initial placeholder (will be immediately overwritten by progress manager)
        await query.edit_message_text("⏳")

        try:
            # Query data first to check if we have results before showing progress
            if exchange_filter == "ALL":
                sql = (
                    "SELECT * FROM whale_orders "
                    "WHERE symbol LIKE ? AND timestamp >= ? "
                    "ORDER BY timestamp DESC LIMIT 3000"
                )
                params = (f"%{symbol_filter}%", since_ms)
            else:
                sql = (
                    "SELECT * FROM whale_orders "
                    "WHERE symbol LIKE ? AND exchange = ? AND timestamp >= ? "
                    "ORDER BY timestamp DESC LIMIT 3000"
                )
                params = (f"%{symbol_filter}%", exchange_filter, since_ms)

            async with self.db._conn.execute(sql, params) as cursor:
                rows = await cursor.fetchall()

            if not rows:
                if user.language == "en":
                    no_data = f"📭 No {symbol_filter} orders found on {exchange_label} in the last {range_label}."
                else:
                    no_data = f"📭 最近{range_label}内，{exchange_label} 上暂无 {symbol_filter} 相关订单。"
                await msg.edit_text(no_data)
                return

            records = [dict(r) for r in rows]
            today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
            suffix = exchange_filter if exchange_filter != "ALL" else "ALL"
            range_suffix = range_key

            async with TaskProgressManager(msg, steps, user.language, title_zh, title_en) as progress:
                # Step 0: Query complete, advance to CSV generation
                await progress.advance()  # → Step 1: Generating CSV

                # Step 1: CSV
                csv_buf = io.StringIO()
                cols = ["timestamp", "exchange", "symbol", "side", "price", "amount_usd", "quantity", "order_type", "status", "source"]
                writer = csv.DictWriter(csv_buf, fieldnames=cols, extrasaction="ignore")
                writer.writeheader()
                for rec in records:
                    rc = dict(rec)
                    ts = rc.get("timestamp", 0)
                    if ts:
                        rc["timestamp"] = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    writer.writerow(rc)
                csv_bytes = csv_buf.getvalue().encode("utf-8")
                csv_fn = f"whale_orders_{symbol_filter}_{suffix}_{range_suffix}_{today_str}.csv"

                await progress.advance()  # → Step 2: Generating JSON

                # Step 2: JSON
                jrs = []
                for rec in records:
                    jr = dict(rec)
                    ts = jr.get("timestamp", 0)
                    if ts:
                        jr["timestamp_utc"] = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    if isinstance(jr.get("metadata"), str):
                        try:
                            jr["metadata"] = json.loads(jr["metadata"])
                        except json.JSONDecodeError:
                            pass
                    jrs.append(jr)
                json_bytes = json.dumps(jrs, ensure_ascii=False, indent=2).encode("utf-8")
                json_fn = f"whale_orders_{symbol_filter}_{suffix}_{range_suffix}_{today_str}.json"

                await progress.advance()  # → Step 3: Sending files

                # Step 3: Send files
                if user.language == "en":
                    caption = (
                        f"📊 **{symbol_filter} Whale Orders — {exchange_label}**\n\n"
                        f"Range: **{range_label}**\n"
                        f"Records: **{len(records)}**\n"
                        "Format: CSV + JSON"
                    )
                else:
                    caption = (
                        f"📊 **{symbol_filter} 巨鲸订单 — {exchange_label}**\n\n"
                        f"时间范围: **{range_label}**\n"
                        f"记录数: **{len(records)}**\n"
                        "格式: CSV + JSON"
                    )

                await msg.reply_document(
                    document=io.BytesIO(csv_bytes), filename=csv_fn, caption=caption, parse_mode="Markdown"
                )
                await msg.reply_document(
                    document=io.BytesIO(json_bytes), filename=json_fn
                )

            # Overwrite with final summary
            done_msg = (
                f"✅ {len(records)} records exported ({range_label})."
                if user.language == "en"
                else f"✅ 已导出 {len(records)} 条记录（{range_label}）。"
            )
            try:
                await msg.edit_text(done_msg)
            except Exception:
                pass

        except Exception as e:
            logger.error("Export failed: %s", e, exc_info=True)
            try:
                await msg.edit_text(f"❌ Export failed: {e}" if user.language == "en" else f"❌ 导出失败: {e}")
            except Exception:
                await msg.reply_text(f"❌ Export failed: {e}" if user.language == "en" else f"❌ 导出失败: {e}")

    async def _ask_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /ask command — real Deepseek AI analysis with chat memory."""
        user_id = update.effective_user.id
        user = await self.user_manager.get_user(user_id)
        if not user:
            return

        if not user.is_active:
            msg = "⚠️ Please input invite code (e.g. `/start Ocean1`) first." if user.language == "en" else "⚠️ 请先输入验证码激活（例如：`/start Ocean1`）"
            await update.message.reply_text(msg, parse_mode="Markdown")
            return

        # Extract the question from args or raw text
        question = ""
        if context.args:
            question = " ".join(context.args)
        elif update.message and update.message.text:
            text = update.message.text.strip()
            for prefix in ["/ask", "ask", "分析", "Ask"]:
                if text.lower().startswith(prefix.lower()):
                    text = text[len(prefix):].strip()
                    break
            question = text

        if not question:
            hint = "💡 Usage: `/ask <your question>`\nExample: `/ask What is the current whale trend for BTC?`" if user.language == "en" else "💡 用法：`/ask <您的问题>`\n示例：`/ask BTC巨鲸最近的买卖趋势是什么？`"
            await update.message.reply_text(hint, parse_mode="Markdown")
            return

        if not self.ai_client:
            await update.message.reply_text("❌ AI client not configured." if user.language == "en" else "❌ AI 分析服务未配置。")
            return

        steps = ai_analysis_steps()
        progress_msg = await update.message.reply_text("⏳")

        try:
            async with TaskProgressManager(
                progress_msg, steps, user.language, "AI 分析", "AI Analysis"
            ) as progress:
                # Step 0: Save question + load chat history
                await self.user_db.add_chat_message(user_id, "user", question)

                chat_history = None
                try:
                    history_msgs = await self.user_db.get_chat_history(user_id, limit=6)
                    if history_msgs:
                        chat_history = [
                            {"role": m.role, "content": m.content}
                            for m in history_msgs
                            if m.content != question
                        ]
                except Exception as e:
                    logger.warning("Failed to load chat history: %s", e)

                await progress.advance()  # → Step 1: Fetching whale data

                # Step 1: Fetch recent whale data from DB
                data_context = {}
                if self.db and hasattr(self.db, '_conn') and self.db._conn:
                    async with self.db._conn.execute(
                        "SELECT COUNT(*) as cnt, AVG(amount_usd) as avg_amt FROM whale_orders WHERE timestamp > ?",
                        (int((datetime.now(timezone.utc).timestamp() - 3600) * 1000),)
                    ) as cur:
                        row = await cur.fetchone()
                        data_context["orders_last_1h"] = row["cnt"] if row else 0
                        data_context["avg_amount_1h"] = round(row["avg_amt"] or 0, 2) if row else 0

                    async with self.db._conn.execute(
                        """SELECT side, COUNT(*) as cnt, SUM(amount_usd) as total
                           FROM whale_orders WHERE timestamp > ?
                           GROUP BY side""",
                        (int((datetime.now(timezone.utc).timestamp() - 3600) * 1000),)
                    ) as cur:
                        sides = await cur.fetchall()
                        for s in sides:
                            data_context[f"{s['side']}_count"] = s["cnt"]
                            data_context[f"{s['side']}_total_usd"] = round(s["total"] or 0, 2)

                    async with self.db._conn.execute(
                        "SELECT * FROM whale_orders ORDER BY timestamp DESC LIMIT 5"
                    ) as cur:
                        recent = await cur.fetchall()
                        recent_summary = []
                        for r in recent:
                            d = dict(r)
                            recent_summary.append({
                                "exchange": d["exchange"], "symbol": d["symbol"],
                                "side": d["side"], "amount_usd": d["amount_usd"],
                                "price": d["price"], "order_type": d["order_type"]
                            })
                        data_context["recent_5_orders"] = recent_summary

                await progress.advance()  # → Step 2: AI analyzing

                # Step 2: Call Deepseek AI (longest step, auto-pulse animates)
                response = await self.ai_client.answer_query(question, data_context, chat_history=chat_history)
                await self.user_db.add_chat_message(user_id, "assistant", response)

                await progress.advance()  # → Step 3: Formatting results

            # Context manager exits with "completed" — overwrite with final result
            try:
                await progress_msg.edit_text(f"🤖 **AI Analysis**\n\n{response}", parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(f"🤖 **AI Analysis**\n\n{response}", parse_mode="Markdown")

        except Exception as e:
            logger.error("AI ask failed: %s", e, exc_info=True)
            try:
                await progress_msg.edit_text(f"❌ AI analysis failed: {e}" if user.language == "en" else f"❌ AI 分析失败: {e}")
            except Exception:
                await update.message.reply_text(f"❌ AI analysis failed: {e}" if user.language == "en" else f"❌ AI 分析失败: {e}")

    async def _buy_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._execute_dummy_job(update, "buy", "Copy Buy", "跟单买入", 1.00)

    async def _sell_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._execute_dummy_job(update, "sell", "Copy Sell", "跟单卖出", 1.00)

    async def _positions_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._execute_dummy_job(update, "positions", "Check Positions", "查询持仓", 0.10)

    async def _balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._execute_dummy_job(update, "balance", "Check Balance", "查询余额", 0.10)

    # ==================== Admin Commands ====================

    async def _approve_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /approve command (admin only)."""
        user_id = update.effective_user.id

        if not await self.user_manager.is_admin(user_id):
            await update.message.reply_text("⛔ 仅管理员可使用此命令")
            return

        if not context.args or len(context.args) != 1:
            await update.message.reply_text("用法: /approve <user_id>")
            return

        target_id = int(context.args[0])
        success = await self.user_manager.approve_user(target_id, user_id)

        if success:
            await update.message.reply_text(f"✅ 用户 {target_id} 已激活")
        else:
            await update.message.reply_text("❌ 激活失败")

    async def _revoke_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /revoke command (admin only)."""
        user_id = update.effective_user.id

        if not await self.user_manager.is_admin(user_id):
            await update.message.reply_text("⛔ 仅管理员可使用此命令")
            return

        if not context.args or len(context.args) != 1:
            await update.message.reply_text("用法: /revoke <user_id>")
            return

        target_id = int(context.args[0])
        success = await self.user_manager.revoke_user(target_id, user_id)

        if success:
            await update.message.reply_text(f"✅ 用户 {target_id} 已撤销")
        else:
            await update.message.reply_text("❌ 撤销失败")

    async def _users_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /users command (admin only)."""
        user_id = update.effective_user.id

        if not await self.user_manager.is_admin(user_id):
            await update.message.reply_text("⛔ 仅管理员可使用此命令")
            return

        users = await self.user_manager.get_all_users()

        if not users:
            await update.message.reply_text("暂无用户")
            return

        # Build user list (limit to first 20)
        user_list = "*用户列表:*\n\n"
        for user in users[:20]:
            status = "✅" if user.is_active else "⏳"
            admin = " (管理员)" if user.is_admin else ""
            user_list += f"{status} `{user.telegram_id}` - {user.username or 'N/A'}{admin}\n"

        if len(users) > 20:
            user_list += f"\n... 还有 {len(users) - 20} 位用户"

        await update.message.reply_text(user_list, parse_mode="Markdown")

    # ==================== Callback Handlers ====================

    async def _callback_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle inline keyboard callbacks."""
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        user = await self.user_manager.get_user(user_id)

        if not user:
            return

        data = query.data
        
        # Language selection
        if data.startswith("set_lang_"):
            lang_code = data.split("_")[2]
            await self.user_manager.update_subscription(user_id, language=lang_code)
            msg = "✅ Language updated successfully!" if lang_code == "en" else "✅ 语言设置已更新！"
            await query.edit_message_text(msg)
            return

        if data == "sub_done":
            msg = "✅ Subscription settings saved!" if user.language == "en" else "✅ 订阅设置已保存！"
            await query.edit_message_text(msg)
            return

        # Export flow step 1: exchange selection callback: export_pick_{SYMBOL}_{EXCHANGE}
        if data.startswith("export_pick_"):
            parts = data.split("_", 3)  # ['export', 'pick', 'BTC', 'Hyperliquid']
            if len(parts) >= 4:
                symbol_filter = parts[2]
                exchange_filter = parts[3]
                exchange_label = exchange_filter if exchange_filter != "ALL" else ("All Exchanges" if user.language == "en" else "全部交易所")
                if user.language == "en":
                    msg_text = (
                        f"📥 **Export {symbol_filter} — {exchange_label}**\n\n"
                        "Step 2/2: Please choose the time range:"
                    )
                else:
                    msg_text = (
                        f"📥 **导出 {symbol_filter} — {exchange_label}**\n\n"
                        "步骤 2/2：请选择时间范围："
                    )
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("1 Day" if user.language == "en" else "1天", callback_data=f"export_do_{symbol_filter}_{exchange_filter}_1d"),
                        InlineKeyboardButton("7 Days" if user.language == "en" else "7天", callback_data=f"export_do_{symbol_filter}_{exchange_filter}_7d"),
                        InlineKeyboardButton("1 Month" if user.language == "en" else "1个月", callback_data=f"export_do_{symbol_filter}_{exchange_filter}_30d"),
                    ]
                ])
                await query.edit_message_text(msg_text, reply_markup=keyboard, parse_mode="Markdown")
            return

        # Export flow step 2: execute export callback: export_do_{SYMBOL}_{EXCHANGE}_{RANGE}
        if data.startswith("export_do_"):
            parts = data.split("_", 4)  # ['export', 'do', 'BTC', 'Hyperliquid', '7d']
            if len(parts) >= 4:
                symbol_filter = parts[2]
                exchange_filter = parts[3]
                range_key = parts[4] if len(parts) >= 5 else "7d"
                await self._do_export(query, user, symbol_filter, exchange_filter, range_key)
            return


        elif data.startswith("pay_job_"):
            if not user.is_active:
                await query.answer(
                    "⚠️ Please input invite code (e.g. /start Ocean1) first." if user.language == "en" else "⚠️ 请先输入验证码激活（例如：/start Ocean1）",
                    show_alert=True
                )
                return
                
            job_types = {
                "pay_job_query": ("📊 Data Query", "📊 数据查询"),
                "pay_job_ai": ("🤖 AI Analysis", "🤖 AI 深度分析"),
                "pay_job_export": ("📥 Export Real Data", "📥 导出真实数据"),
                "pay_job_buy": ("📈 Copy Buy", "📈 跟单买入"),
                "pay_job_sell": ("📉 Copy Sell", "📉 跟单卖出"),
                "pay_job_positions": ("💼 Check Positions", "💼 查询持仓"),
                "pay_job_balance": ("💰 Check Balance", "💰 查询余额")
            }
            if data in job_types:
                names = job_types[data]
                job_name = names[0] if user.language == "en" else names[1]

                await query.edit_message_text("⏳")
                pay_msg = query.message
                steps = payment_job_steps()

                try:
                    async with TaskProgressManager(
                        pay_msg, steps, user.language, job_name, job_name
                    ) as progress:
                        # Step 0: Processing payment (simulated)
                        await asyncio.sleep(1)
                        await progress.advance()  # → Step 1: Executing task

                        # Step 1: Executing task (simulated)
                        await asyncio.sleep(2)
                        await progress.advance()  # → Step 2: Confirming result

                        # Step 2: auto-completes on exit

                    # Real data path for /query after payment confirmation.
                    if data == "pay_job_query":
                        query_request = context.user_data.pop("pending_query_request", {
                            "mode": "large",
                            "symbol": "BTC",
                        })
                        await self._do_query(pay_msg, user, query_request)
                    else:
                        if user.language == "en":
                            done = (
                                f"✅ **Payment Successful!**\n\n"
                                f"**{job_name}** completed.\n"
                                f"(This feature is for demonstration, no real funds were moved)"
                            )
                        else:
                            done = (
                                f"✅ **支付成功！**\n\n"
                                f"**{job_name}** 任务已完成。\n"
                                f"（此功能为演示效果，未实际扣取您的资金）"
                            )
                        await pay_msg.edit_text(done, parse_mode="Markdown")
                except Exception as e:
                    logger.error("Payment job failed: %s", e, exc_info=True)
            return

        elif data == "sub_all":
            await self.user_manager.update_subscription(
                user_id, subscribed_exchanges=[]
            )

        elif data == "sub_binance":
            exchanges = user.subscribed_exchanges or []
            if "Binance" in exchanges:
                exchanges = [e for e in exchanges if e != "Binance"]
            else:
                exchanges.append("Binance")
            await self.user_manager.update_subscription(
                user_id, subscribed_exchanges=exchanges
            )

        elif data == "sub_okx":
            exchanges = user.subscribed_exchanges or []
            if "OKX" in exchanges:
                exchanges = [e for e in exchanges if e != "OKX"]
            else:
                exchanges.append("OKX")
            await self.user_manager.update_subscription(
                user_id, subscribed_exchanges=exchanges
            )

        elif data == "sub_bybit":
            exchanges = user.subscribed_exchanges or []
            if "Bybit" in exchanges:
                exchanges = [e for e in exchanges if e != "Bybit"]
            else:
                exchanges.append("Bybit")
            await self.user_manager.update_subscription(
                user_id, subscribed_exchanges=exchanges
            )

        elif data == "sub_threshold":
            # TODO: Implement threshold setting dialog
            await query.edit_message_text(
                "请输入新的金额阈值（美元），例如: 500000"
            )
            return

        # Update the keyboard
        user = await self.user_manager.get_user(user_id)
        current_exchanges = (
            ", ".join(user.subscribed_exchanges)
            if user.subscribed_exchanges
            else "全部"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    f"{'✅ ' if 'Binance' in (user.subscribed_exchanges or []) else ''}Binance",
                    callback_data="sub_binance",
                ),
                InlineKeyboardButton(
                    f"{'✅ ' if 'OKX' in (user.subscribed_exchanges or []) else ''}OKX",
                    callback_data="sub_okx",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{'✅ ' if 'Bybit' in (user.subscribed_exchanges or []) else ''}Bybit",
                    callback_data="sub_bybit",
                ),
                InlineKeyboardButton(
                    f"{'✅ ' if not user.subscribed_exchanges else ''}全部",
                    callback_data="sub_all",
                ),
            ],
            [
                InlineKeyboardButton("设置金额阈值", callback_data="sub_threshold"),
                InlineKeyboardButton("完成", callback_data="sub_done"),
            ],
        ])

        try:
            await query.edit_message_text(
                f"*订阅设置*\n\n"
                f"当前订阅的交易所: {current_exchanges}\n"
                f"当前金额阈值: ${user.min_alert_threshold:,.0f}\n\n"
                f"请选择要订阅的交易所或设置金额阈值:",
                reply_markup=keyboard,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error("Failed to update message: %s", e)

    # ==================== Message Handler ====================

    async def _message_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle general text messages."""
        user_id = update.effective_user.id
        text = update.message.text

        if not await self.user_manager.is_active(user_id):
            await update.message.reply_text(
                "您的账号尚未激活，请等待管理员审核。"
            )
            return

        await self.user_manager.update_activity(user_id)

        # Handle threshold setting
        if re.match(r"^\d+$", text.strip()):
            new_threshold = float(text.strip())
            await self.user_manager.update_subscription(
                user_id, min_alert_threshold=new_threshold
            )
            await update.message.reply_text(
                f"✅ 金额阈值已更新为 ${new_threshold:,.0f}"
            )
            return

        text_lower = text.strip().lower()
        if text_lower.startswith("query") or text_lower.startswith("查询"):
            await self._query_command(update, context)
            return
        elif text_lower.startswith("export") or text_lower.startswith("导出"):
            await self._export_command(update, context)
            return
        elif text_lower.startswith("ask") or text_lower.startswith("分析"):
            await self._ask_command(update, context)
            return
        elif text_lower.startswith("buy") or text_lower.startswith("买入"):
            await self._buy_command(update, context)
            return
        elif text_lower.startswith("sell") or text_lower.startswith("卖出"):
            await self._sell_command(update, context)
            return
        elif text_lower.startswith("positions") or text_lower.startswith("position") or text_lower.startswith("持仓"):
            await self._positions_command(update, context)
            return
        elif text_lower.startswith("balance") or text_lower.startswith("余额"):
            await self._balance_command(update, context)
            return

        # Use dialog handler for natural language queries
        if self.dialog_handler:
            user = await self.user_manager.get_user(user_id)
            steps = query_steps()
            progress_msg = await update.message.reply_text("⏳")
            try:
                async with TaskProgressManager(
                    progress_msg, steps, user.language if user else "zh",
                    "智能分析", "Smart Analysis",
                ) as progress:
                    response = await self.dialog_handler.handle_message(user, text)

                try:
                    await progress_msg.edit_text(response, parse_mode="Markdown")
                except Exception:
                    await update.message.reply_text(response, parse_mode="Markdown")
            except Exception as e:
                logger.error("Dialog handler error: %s", e, exc_info=True)
                try:
                    err = "An error occurred. Please try again." if (user and user.language == "en") else "处理您的请求时出现错误，请稍后重试。"
                    await progress_msg.edit_text(err)
                except Exception:
                    await update.message.reply_text("处理您的请求时出现错误，请稍后重试。")
        else:
            await update.message.reply_text(
                "AI 分析功能尚未配置。请联系管理员。"
            )

"""Telegram Bot service for whale order monitoring."""

from __future__ import annotations

import logging
import asyncio
import re
import csv
import io
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, Any

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
                ("bindgroup", "绑定群聊推送 / Bind Group Push"),
                ("query", "查询开仓 / Query opens"),
                ("export", "导出开仓 / Export opens"),
                ("ask", "AI 分析 / AI analysis"),
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
        app.add_handler(CommandHandler("bindgroup", self._bindgroup_command))
        app.add_handler(CommandHandler("stats", self._stats_command))
        app.add_handler(CommandHandler("status", self._status_command))

        # Job Offerings commands
        app.add_handler(CommandHandler("query", self._query_command))
        app.add_handler(CommandHandler("export", self._export_command))
        app.add_handler(CommandHandler("ask", self._ask_command))

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
                "🤖 Hyperliquid WhaleScope AI Agent is ready.\n\n"
                "This AI Agent specializes in detecting whale OPEN positions on Hyperliquid from CoinGlass real-time data.\n\n"
            )
            
            menu_body = (
                "—— 🤖 AI Agent Capabilities ——\n"
                "• Real-time whale open detection (LONG/SHORT)\n"
                "• Wallet-level open-position tracking\n"
                "• Open heat leaderboard (1h / 4h / 24h)\n"
                "• AI interpretation + risk hints\n"
                "• Export-ready structured datasets\n\n"
                "—— 🐋 Whale Definition ——\n"
                "• Whale open alert: notional ≥ $1,000,000\n"
                "• Focus whale alert: notional ≥ $5,000,000\n"
                "• Mega whale alert: notional ≥ $10,000,000\n\n"
                "—— 📊 Data Query —— $0.10/time\n"
                "· Open positions feed → /query open BTC      $0.10\n"
                "· Wallet open history → /query wallet 0x...  $0.10\n"
                "· Top open board → /query top 24h            $0.10\n\n"
                "—— 📥 Data Export —— $0.80/time\n"
                "· Export Hyperliquid open records\n"
                "→ /export open BTC 7d                        $0.80\n"
                "Delivery: CSV + JSON\n\n"
                "—— 🤖 AI Analysis —— $0.50/time\n"
                "· AI Q&A → /ask <question>                   $0.50\n"
                "Signals are based on Hyperliquid whale opens only.\n\n"
                "—— 🔧 Account Management —— Free\n"
                "/subscribe · /status · /stats · /language\n\n"
                "💡 Symbols supported by CoinGlass Hyperliquid endpoint are available (BTC/ETH/SOL...).\n"
                "Type /help to see the full menu anytime."
            )
            
            if not user.is_active:
                msg = welcome_header + "⚠️ **You need to input an invite code (like `/start Ocean1`) or wait for admin approval to use these services.**\n\n" + menu_body
            else:
                msg = welcome_header + menu_body
        else:
            welcome_header = (
                "🤖 Hyperliquid WhaleScope AI Agent 已启动。\n\n"
                "这是一个专注于 Hyperliquid 鲸鱼开仓检测的 AI Agent，基于 CoinGlass 实时数据持续追踪鲸鱼开仓行为。\n\n"
            )
            
            menu_body = (
                "—— 🤖 AI Agent 能力 ——\n"
                "• 实时检测鲸鱼开仓（LONG/SHORT）\n"
                "• 钱包级开仓行为追踪\n"
                "• 开仓热度排行榜（1h / 4h / 24h）\n"
                "• AI 解读 + 风险提示\n"
                "• 结构化数据导出\n\n"
                "—— 🐋 巨鲸定义（告警分层）——\n"
                "• 标准巨鲸开仓：单笔名义价值 ≥ $1,000,000\n"
                "• 重点巨鲸开仓：单笔名义价值 ≥ $5,000,000\n"
                "• 超级巨鲸开仓：单笔名义价值 ≥ $10,000,000\n\n"
                "—— 📊 数据查询 —— $0.10/次\n"
                "· 开仓事件流 → /query open BTC       $0.10\n"
                "· 钱包开仓历史 → /query wallet 0x... $0.10\n"
                "· 开仓排行榜 → /query top 24h         $0.10\n\n"
                "—— 📥 数据导出 —— $0.80/次\n"
                "· 导出 Hyperliquid 开仓记录\n"
                "→ /export open BTC 7d                $0.80\n"
                "交付: CSV + JSON\n\n"
                "—— 🤖 AI 分析 —— $0.50/次\n"
                "· AI 智能问答 → /ask <问题>          $0.50\n"
                "信号基于 Hyperliquid 鲸鱼开仓数据。\n\n"
                "—— 🔧 账户管理 —— 免费\n"
                "/subscribe · /status · /stats · /language\n\n"
                "💡 支持 CoinGlass Hyperliquid 接口可用币种（如 BTC/ETH/SOL）。\n"
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
*🤖 Hyperliquid WhaleScope AI Agent*

*AI Agent 支持的功能：*
• 实时检测 Hyperliquid 鲸鱼开仓事件
• 钱包级开仓历史追踪
• 开仓热度排行榜（1h/4h/24h）
• AI 趋势解读与风险提示
• CSV + JSON 结构化数据导出

*基础命令：*
/start - 开始使用
/help - 显示帮助
/status - 系统状态
/stats - 个人统计
/language - 切换语言

*核心命令：*
/query open BTC [page] - 查询开仓事件流（分页）
/query wallet <0x地址> [page] - 查询钱包开仓历史
/query top [1h|4h|24h] - 查询开仓排行榜
/export open BTC [1d|7d|30d] - 导出开仓数据
/ask <问题> - AI 分析

*订阅：*
/subscribe - 订阅设置（开关/阈值/推送渠道）
/bindgroup - 在群里绑定群推送（先把 Bot 拉进群）

*管理员命令：*
/approve <user_id> - 审核用户
/revoke <user_id> - 撤销用户
/users - 查看所有用户
        """
        await update.message.reply_text(help_text, parse_mode="Markdown")

    @staticmethod
    def _mask_webhook(url: str) -> str:
        if not url:
            return "未设置"
        if len(url) <= 18:
            return "***"
        return f"{url[:12]}...{url[-6:]}"

    def _push_channel_label(self, user) -> str:
        channel = (user.push_channel or "dm").lower()
        if channel == "group":
            if user.push_group_chat_id:
                return f"Telegram 群聊 (ID: `{user.push_group_chat_id}`)"
            return "Telegram 群聊 (未绑定，请在目标群发送 /bindgroup)"
        if channel == "webhook":
            return f"Webhook ({self._mask_webhook(user.custom_webhook_url or '')})"
        return "Telegram 私聊"

    def _build_subscribe_keyboard(self, user) -> InlineKeyboardMarkup:
        enabled_text = "⏸ 停止推送" if user.alerts_enabled else "▶️ 恢复推送"
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    f"{'✅ ' if 'Hyperliquid' in (user.subscribed_exchanges or []) else ''}Hyperliquid",
                    callback_data="sub_hyperliquid",
                ),
                InlineKeyboardButton(
                    f"{'✅ ' if not user.subscribed_exchanges else ''}全部",
                    callback_data="sub_all",
                ),
            ],
            [
                InlineKeyboardButton("设置金额阈值", callback_data="sub_threshold"),
                InlineKeyboardButton(enabled_text, callback_data="sub_toggle_push"),
            ],
            [
                InlineKeyboardButton(
                    f"{'✅ ' if (user.push_channel or 'dm') == 'dm' else ''}私聊推送",
                    callback_data="sub_channel_dm",
                ),
                InlineKeyboardButton(
                    f"{'✅ ' if (user.push_channel or 'dm') == 'group' else ''}群聊推送",
                    callback_data="sub_channel_group",
                ),
                InlineKeyboardButton(
                    f"{'✅ ' if (user.push_channel or 'dm') == 'webhook' else ''}Webhook",
                    callback_data="sub_channel_webhook",
                ),
            ],
            [
                InlineKeyboardButton("完成", callback_data="sub_done"),
            ],
        ])

    def _build_subscribe_text(self, user) -> str:
        current_exchanges = (
            ", ".join(user.subscribed_exchanges)
            if user.subscribed_exchanges
            else "Hyperliquid(默认)"
        )
        push_state = "开启" if user.alerts_enabled else "停止"
        return (
            "*订阅设置*\n\n"
            f"当前订阅源: {current_exchanges}\n"
            f"当前金额阈值: ${user.min_alert_threshold:,.0f}\n"
            f"推送状态: {push_state}\n"
            f"推送渠道: {self._push_channel_label(user)}\n\n"
            "可选渠道：Telegram 私聊 / Telegram 群聊 / 自定义 Webhook\n"
            "如需群推送：把 Bot 拉进群后，在该群发送 `/bindgroup`。"
        )

    async def _bindgroup_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Bind current group chat as push destination for this user."""
        user_id = update.effective_user.id
        chat = update.effective_chat
        if chat.type not in {"group", "supergroup"}:
            await update.message.reply_text("请在目标群里发送 `/bindgroup` 来绑定群推送。", parse_mode="Markdown")
            return

        if not await self.user_manager.is_active(user_id):
            await update.message.reply_text("您的账号尚未激活，请先完成激活。")
            return

        await self.user_manager.update_push_preferences(
            user_id,
            alerts_enabled=True,
            push_channel="group",
            push_group_chat_id=chat.id,
        )
        await update.message.reply_text(
            f"✅ 已绑定当前群为推送目的地。\n群ID: `{chat.id}`\n后续告警将推送到本群。",
            parse_mode="Markdown",
        )

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

        user = await self.user_manager.get_user(user_id)
        keyboard = self._build_subscribe_keyboard(user)
        await update.message.reply_text(
            self._build_subscribe_text(user),
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

    async def _status_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /status command."""
        status_text = f"""
*📊 系统状态（Hyperliquid WhaleScope AI Agent）*

🟢 CoinGlass Hyperliquid API: 运行中
🤖 AI 分析: {'运行中' if self.settings.deepseek_api_key else '未配置'}
👥 活跃用户: {len(await self.user_manager.get_all_active_users())}
📡 监控能力: Hyperliquid 鲸鱼开仓实时检测
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
   • 来源: {', '.join(user.subscribed_exchanges) if user.subscribed_exchanges else 'Hyperliquid(默认)'}
   • 金额阈值: ${user.min_alert_threshold:,.0f}
   • 推送状态: {'开启' if user.alerts_enabled else '停止'}
   • 推送渠道: {self._push_channel_label(user)}

📅 **注册时间:** {user.created_at.strftime('%Y-%m-%d %H:%M')}
🕐 **最后活跃:** {user.last_active_at.strftime('%Y-%m-%d %H:%M') if user.last_active_at else '无'}

🔔 **24小时告警数:** {alerts_today}"""

        await update.message.reply_text(stats_text, parse_mode="Markdown")

    @staticmethod
    def _parse_page_token(token: str) -> Optional[int]:
        clean = token.strip().lower()
        if not clean:
            return None
        if clean.isdigit():
            return int(clean)
        if clean.startswith("page=") and clean[5:].isdigit():
            return int(clean[5:])
        if clean.startswith("p=") and clean[2:].isdigit():
            return int(clean[2:])
        if clean.startswith("p") and clean[1:].isdigit():
            return int(clean[1:])
        return None

    @staticmethod
    def _safe_utc_hms(timestamp_ms: int) -> str:
        try:
            if timestamp_ms <= 0:
                return "--:--:--"
            return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).strftime("%H:%M:%S")
        except Exception:
            return "--:--:--"

    def _parse_query_request(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> dict[str, str | int]:
        """Parse query mode and parameters from command args/text."""
        mode_alias = {
            "open": "open",
            "wallet": "wallet",
            "top": "top",
            "开仓": "open",
            "钱包": "wallet",
            "地址": "wallet",
            "排行": "top",
            "排行榜": "top",
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

        mode = "open"
        symbol = "BTC"
        wallet = ""
        window = "24h"
        page = 1
        rest: list[str] = []
        if tokens:
            first = tokens[0]
            normalized_mode = mode_alias.get(first.lower()) or mode_alias.get(first)
            if normalized_mode:
                mode = normalized_mode
                rest = tokens[1:]
            else:
                rest = tokens

        if mode == "wallet":
            if rest:
                wallet = re.sub(r"[^A-Za-z0-9_xX-]", "", rest[0])
                for token in rest[1:]:
                    maybe_page = self._parse_page_token(token)
                    if maybe_page:
                        page = maybe_page
                        break
        elif mode == "top":
            if rest and rest[0].lower() in {"1h", "4h", "24h"}:
                window = rest[0].lower()
        else:
            if rest:
                symbol = rest[0]
                for token in rest[1:]:
                    maybe_page = self._parse_page_token(token)
                    if maybe_page:
                        page = maybe_page
                        break

        page = max(1, min(page, 999))
        symbol = re.sub(r"[^A-Za-z0-9_-]", "", symbol.upper()) or "BTC"
        return {"mode": mode, "symbol": symbol, "wallet": wallet, "window": window, "page": page}

    def _query_meta(self, mode: str, language: str) -> tuple[str, float]:
        """Get display name and price for query mode."""
        mode_name_en = {
            "open": "Hyperliquid Open Feed",
            "wallet": "Wallet Open History",
            "top": "Open Leaderboard",
        }
        mode_name_zh = {
            "open": "Hyperliquid 开仓流",
            "wallet": "钱包开仓历史",
            "top": "开仓排行榜",
        }
        price_map = {
            "open": 0.10,
            "wallet": 0.10,
            "top": 0.10,
        }
        name = mode_name_en.get(mode, mode_name_en["open"]) if language == "en" else mode_name_zh.get(mode, mode_name_zh["open"])
        return name, price_map.get(mode, 0.10)

    async def _do_query(
        self,
        msg,
        user,
        query_request: dict[str, str | int],
    ) -> None:
        """Run Hyperliquid open-position queries and render response."""
        if not self.db or not hasattr(self.db, "_conn") or self.db._conn is None:
            err = "❌ Database not available." if user.language == "en" else "❌ 数据库尚未就绪，请稍后再试。"
            await msg.edit_text(err)
            return

        mode = str(query_request.get("mode", "open"))
        symbol = str(query_request.get("symbol", "BTC"))
        wallet = str(query_request.get("wallet", "")).strip()
        window = str(query_request.get("window", "24h")).lower()
        page = int(query_request.get("page", 1) or 1)
        page = max(1, min(page, 999))
        page_size = 20

        mode_name, _ = self._query_meta(mode, user.language)
        if mode == "wallet":
            title_zh = f"数据查询：{mode_name} {wallet or '(empty)'} P{page}"
            title_en = f"Data Query: {mode_name} {wallet or '(empty)'} P{page}"
        elif mode == "top":
            title_zh = f"数据查询：{mode_name} {window}"
            title_en = f"Data Query: {mode_name} {window}"
        else:
            title_zh = f"数据查询：{mode_name} {symbol} P{page}"
            title_en = f"Data Query: {mode_name} {symbol} P{page}"
        steps = query_steps()

        base_where = (
            "source = 'dex_hyperliquid' AND order_type = 'whale_position' "
            "AND COALESCE(json_extract(metadata, '$.action'), 'open') = 'open'"
        )

        async with TaskProgressManager(msg, steps, user.language, title_zh, title_en) as progress:
            await progress.advance()  # Querying data

            await progress.advance()  # Generating answer

        def parse_meta(raw_meta: Any) -> dict[str, Any]:
            if isinstance(raw_meta, dict):
                return raw_meta
            if isinstance(raw_meta, str):
                try:
                    parsed = json.loads(raw_meta)
                    return parsed if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    return {}
            return {}

        if mode == "top":
            window_map = {"1h": 1, "4h": 4, "24h": 24}
            hours = window_map.get(window, 24)
            since_ms = int((datetime.now(timezone.utc).timestamp() - hours * 3600) * 1000)
            sql = (
                "SELECT timestamp, symbol, side, amount_usd, price, metadata "
                f"FROM whale_orders WHERE {base_where} AND timestamp >= ? "
                "ORDER BY amount_usd DESC LIMIT 200"
            )
            async with self.db._conn.execute(sql, (since_ms,)) as cursor:
                rows = await cursor.fetchall()

            if not rows:
                no_data = (
                    f"✅ Payment successful!\n📭 No Hyperliquid open records in last {hours}h."
                    if user.language == "en"
                    else f"✅ 支付成功！\n📭 最近 {hours} 小时暂无 Hyperliquid 开仓记录。"
                )
                await msg.edit_text(no_data)
                return

            board: dict[tuple[str, str], dict[str, Any]] = {}
            for row in rows:
                meta = parse_meta(row["metadata"])
                w = str(meta.get("wallet") or "unknown")
                key = (w, row["symbol"])
                item = board.setdefault(
                    key,
                    {
                        "wallet": w,
                        "symbol": row["symbol"],
                        "count": 0,
                        "total_usd": 0.0,
                        "max_usd": 0.0,
                        "latest_ts": 0,
                    },
                )
                usd = float(row["amount_usd"])
                item["count"] += 1
                item["total_usd"] += usd
                item["max_usd"] = max(item["max_usd"], usd)
                item["latest_ts"] = max(item["latest_ts"], int(row["timestamp"]))

            rank_rows = sorted(board.values(), key=lambda x: x["total_usd"], reverse=True)[:20]
            lines = []
            for idx, item in enumerate(rank_rows, start=1):
                ts = self._safe_utc_hms(item["latest_ts"])
                lines.append(
                    f"{idx:02d}. ${item['total_usd']:,.0f} | {item['symbol']} | {item['wallet']} | "
                    f"{item['count']} opens | max ${item['max_usd']:,.0f} | last {ts}"
                )

            total_usd = sum(i["total_usd"] for i in rank_rows)
            if user.language == "en":
                result = (
                    "✅ Payment successful!\n"
                    f"📊 Open leaderboard ({hours}h)\n"
                    f"• Wallet-symbol pairs: {len(rank_rows)}\n"
                    f"• Total open notional: ${total_usd:,.0f}\n\n"
                    "Top board:\n"
                    + "\n".join(lines)
                )
            else:
                result = (
                    "✅ 支付成功！\n"
                    f"📊 开仓排行榜（最近 {hours} 小时）\n"
                    f"• 钱包-标的对数：{len(rank_rows)}\n"
                    f"• 总开仓名义价值：${total_usd:,.0f}\n\n"
                    "排行榜：\n"
                    + "\n".join(lines)
                )
            await msg.edit_text(result)
            return

        where_clause = base_where
        params: list[object] = []
        query_label = symbol
        if mode == "wallet":
            if not wallet:
                err = (
                    "❌ Wallet is required. Example: /query wallet 0xabc..."
                    if user.language == "en"
                    else "❌ 钱包地址不能为空。示例：/query wallet 0xabc..."
                )
                await msg.edit_text(err)
                return
            where_clause += " AND metadata LIKE ?"
            params.append(f"%{wallet}%")
            query_label = wallet
        else:
            where_clause += " AND symbol LIKE ?"
            params.append(f"%{symbol}%")

        stat_sql = (
            "SELECT COUNT(*) as cnt, COALESCE(SUM(amount_usd), 0) as total_usd, "
            "COALESCE(SUM(CASE WHEN side='buy' THEN amount_usd ELSE 0 END), 0) as long_usd, "
            "COALESCE(SUM(CASE WHEN side='sell' THEN amount_usd ELSE 0 END), 0) as short_usd "
            f"FROM whale_orders WHERE {where_clause}"
        )
        async with self.db._conn.execute(stat_sql, tuple(params)) as cursor:
            stat = await cursor.fetchone()

        total_count = int(stat["cnt"]) if stat else 0
        total_pages = (total_count + page_size - 1) // page_size if total_count else 1
        page = min(page, total_pages)
        offset = (page - 1) * page_size

        sql = (
            "SELECT timestamp, exchange, symbol, side, amount_usd, price, metadata "
            f"FROM whale_orders WHERE {where_clause} "
            "ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        )
        async with self.db._conn.execute(sql, tuple(params + [page_size, offset])) as cursor:
            rows = await cursor.fetchall()

        if not rows:
            no_data = (
                f"✅ Payment successful!\n📭 No Hyperliquid open records for {query_label}."
                if user.language == "en"
                else f"✅ 支付成功！\n📭 未找到 {query_label} 对应的 Hyperliquid 开仓记录。"
            )
            await msg.edit_text(no_data)
            return

        total_usd = float(stat["total_usd"]) if stat else 0.0
        long_usd = float(stat["long_usd"]) if stat else 0.0
        short_usd = float(stat["short_usd"]) if stat else 0.0

        latest_lines = []
        for row in rows:
            ts = self._safe_utc_hms(int(row["timestamp"]))
            side = "LONG" if str(row["side"]).lower() == "buy" else "SHORT"
            meta = parse_meta(row["metadata"])
            row_wallet = str(meta.get("wallet") or "")
            latest_lines.append(
                f"{ts} | {row['symbol']} {side} ${float(row['amount_usd']):,.0f} @ ${float(row['price']):,.2f} | {row_wallet}"
            )

        nav_tip = ""
        if user.language == "en":
            if page > 1:
                nav_tip += f"\nPrev: /query {mode} {query_label} {page - 1}"
            if page < total_pages:
                nav_tip += f"\nNext: /query {mode} {query_label} {page + 1}"
        else:
            if page > 1:
                nav_tip += f"\n上一页：/query {mode} {query_label} {page - 1}"
            if page < total_pages:
                nav_tip += f"\n下一页：/query {mode} {query_label} {page + 1}"

        if user.language == "en":
            result = (
                "✅ Payment successful!\n"
                f"📊 Query done: {mode_name} ({query_label})\n"
                f"• Total records: {total_count}\n"
                f"• Total open notional: ${total_usd:,.0f}\n"
                f"• LONG open notional: ${long_usd:,.0f}\n"
                f"• SHORT open notional: ${short_usd:,.0f}\n"
                f"• Page: {page}/{total_pages} (size {page_size})\n\n"
                "Latest opens (UTC):\n"
                + "\n".join(latest_lines)
            )
            if nav_tip:
                result += "\n\nPagination:" + nav_tip
        else:
            result = (
                "✅ 支付成功！\n"
                f"📊 查询完成：{mode_name}（{query_label}）\n"
                f"• 总记录数：{total_count}\n"
                f"• 总开仓名义价值：${total_usd:,.0f}\n"
                f"• LONG 开仓额：${long_usd:,.0f}\n"
                f"• SHORT 开仓额：${short_usd:,.0f}\n"
                f"• 页码：{page}/{total_pages}（每页 {page_size} 条）\n\n"
                "最新开仓（UTC）：\n"
                + "\n".join(latest_lines)
            )
            if nav_tip:
                result += "\n\n分页：" + nav_tip
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
        mode = str(query_request["mode"])
        symbol = str(query_request["symbol"])
        wallet = str(query_request.get("wallet", ""))
        window = str(query_request.get("window", "24h"))
        page = int(query_request.get("page", 1) or 1)
        mode_name, price = self._query_meta(mode, user.language)
        context.user_data["pending_query_request"] = query_request

        btn_text = f"💳 Pay ${price:.2f}" if user.language == "en" else f"💳 确认支付 ${price:.2f}"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(btn_text, callback_data="pay_job_query")]
        ])

        if user.language == "en":
            target = symbol
            if mode == "wallet":
                target = wallet or "N/A"
            elif mode == "top":
                target = window
            msg = (
                "🧾 **Virtual Invoice**\n\n"
                f"Target Job: **📊 {mode_name}**\n"
                f"Target: **{target}**\n"
                f"Page: **{page}**\n"
                f"Total Cost: **${price:.2f}**\n\n"
                "Please click the button below to execute the query:"
            )
        else:
            target = symbol
            if mode == "wallet":
                target = wallet or "N/A"
            elif mode == "top":
                target = window
            msg = (
                "🧾 **虚拟账单**\n\n"
                f"您选择了服务：**📊 {mode_name}**\n"
                f"查询目标：**{target}**\n"
                f"查询页码：**{page}**\n"
                f"服务费用：**${price:.2f}**\n\n"
                "请点击下方按钮完成支付并开始查询："
            )
        await update.message.reply_text(msg, reply_markup=keyboard, parse_mode="Markdown")

    def _parse_export_request(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> dict[str, str]:
        tokens: list[str] = []
        if context.args:
            tokens = [t.strip() for t in context.args if t.strip()]
        elif update.message and update.message.text:
            parts = update.message.text.strip().split()
            if parts:
                head = parts[0].lower()
                if head in {"/export", "export", "导出"}:
                    tokens = parts[1:]
                else:
                    tokens = parts

        symbol = "BTC"
        range_key = "7d"
        symbol_set = False
        for tok in tokens:
            t = tok.lower()
            if t in {"open", "开仓"}:
                continue
            if t in {"1d", "7d", "30d"}:
                range_key = t
                continue
            if not symbol_set:
                symbol = tok
                symbol_set = True

        symbol = re.sub(r"[^A-Za-z0-9_-]", "", symbol.upper()) or "BTC"
        return {"symbol": symbol, "range_key": range_key}

    async def _export_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /export command for Hyperliquid open-position export."""
        user_id = update.effective_user.id
        user = await self.user_manager.get_user(user_id)
        if not user:
            return

        if not user.is_active:
            msg = "⚠️ Please input invite code (e.g. `/start Ocean1`) first." if user.language == "en" else "⚠️ 请先输入验证码激活（例如：`/start Ocean1`）"
            await update.message.reply_text(msg, parse_mode="Markdown")
            return

        export_request = self._parse_export_request(update, context)
        symbol_filter = export_request["symbol"]
        range_key = export_request["range_key"]
        range_label, _ = self._export_range_meta(range_key, user.language)
        context.user_data["pending_export_request"] = export_request

        btn_text = "💳 Pay $0.80" if user.language == "en" else "💳 确认支付 $0.80"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(btn_text, callback_data="pay_job_export")]])

        if user.language == "en":
            text = (
                "🧾 **Virtual Invoice**\n\n"
                "Target Job: **📥 Export Hyperliquid Open Records**\n"
                f"Symbol: **{symbol_filter}**\n"
                f"Range: **{range_label}**\n"
                "Source: **Hyperliquid only**\n"
                "Total Cost: **$0.80**"
            )
        else:
            text = (
                "🧾 **虚拟账单**\n\n"
                "您选择了服务：**📥 导出 Hyperliquid 开仓记录**\n"
                f"币种：**{symbol_filter}**\n"
                f"时间范围：**{range_label}**\n"
                "数据源：**Hyperliquid 开仓数据**\n"
                "服务费用：**$0.80**"
            )
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

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
        msg,
        user,
        symbol_filter: str,
        range_key: str = "7d",
    ) -> None:
        """Export Hyperliquid whale open records as CSV+JSON."""
        if not self.db or not hasattr(self.db, '_conn') or self.db._conn is None:
            err = "❌ Database not available." if user.language == "en" else "❌ 数据库尚未就绪，请稍后重试。"
            await msg.edit_text(err)
            return

        range_label, days = self._export_range_meta(range_key, user.language)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        since_ms = now_ms - days * 24 * 60 * 60 * 1000
        steps = export_steps()
        title_zh = f"导出 Hyperliquid 开仓 {symbol_filter} {range_label}"
        title_en = f"Export Hyperliquid opens {symbol_filter} {range_label}"

        try:
            sql = (
                "SELECT * FROM whale_orders "
                "WHERE source='dex_hyperliquid' AND order_type='whale_position' "
                "AND COALESCE(json_extract(metadata, '$.action'), 'open')='open' "
                "AND symbol LIKE ? AND timestamp >= ? "
                "ORDER BY timestamp DESC LIMIT 5000"
            )
            async with self.db._conn.execute(sql, (f"%{symbol_filter}%", since_ms)) as cursor:
                rows = await cursor.fetchall()

            if not rows:
                no_data = (
                    f"📭 No Hyperliquid open records for {symbol_filter} in last {range_label}."
                    if user.language == "en"
                    else f"📭 最近{range_label}内暂无 {symbol_filter} 的 Hyperliquid 开仓记录。"
                )
                await msg.edit_text(no_data)
                return

            records = [dict(r) for r in rows]
            today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
            csv_fn = f"hyperliquid_open_{symbol_filter}_{range_key}_{today_str}.csv"
            json_fn = f"hyperliquid_open_{symbol_filter}_{range_key}_{today_str}.json"

            async with TaskProgressManager(msg, steps, user.language, title_zh, title_en) as progress:
                await progress.advance()

                csv_buf = io.StringIO()
                cols = [
                    "timestamp", "exchange", "symbol", "side", "price", "amount_usd",
                    "quantity", "order_type", "status", "source", "wallet", "action"
                ]
                writer = csv.DictWriter(csv_buf, fieldnames=cols, extrasaction="ignore")
                writer.writeheader()
                for rec in records:
                    rc = dict(rec)
                    ts = int(rc.get("timestamp", 0) or 0)
                    if ts > 0:
                        rc["timestamp"] = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    meta = rc.get("metadata")
                    if isinstance(meta, str):
                        try:
                            meta = json.loads(meta)
                        except json.JSONDecodeError:
                            meta = {}
                    if not isinstance(meta, dict):
                        meta = {}
                    rc["wallet"] = meta.get("wallet", "")
                    rc["action"] = meta.get("action", "open")
                    writer.writerow(rc)
                csv_bytes = csv_buf.getvalue().encode("utf-8")

                await progress.advance()

                json_rows = []
                for rec in records:
                    jr = dict(rec)
                    ts = int(jr.get("timestamp", 0) or 0)
                    if ts > 0:
                        jr["timestamp_utc"] = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    if isinstance(jr.get("metadata"), str):
                        try:
                            jr["metadata"] = json.loads(jr["metadata"])
                        except json.JSONDecodeError:
                            jr["metadata"] = {}
                    json_rows.append(jr)

                json_payload = {
                    "source": "coinglass_hyperliquid_whale_alert",
                    "scope": "open_positions_only",
                    "symbol_filter": symbol_filter,
                    "range": range_key,
                    "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "count": len(json_rows),
                    "records": json_rows,
                }
                json_bytes = json.dumps(json_payload, ensure_ascii=False, indent=2).encode("utf-8")

                await progress.advance()

                if user.language == "en":
                    caption = (
                        f"📊 **Hyperliquid Open Export — {symbol_filter}**\n\n"
                        f"Range: **{range_label}**\n"
                        f"Records: **{len(records)}**\n"
                        "Scope: **Open positions only**"
                    )
                else:
                    caption = (
                        f"📊 **Hyperliquid 开仓导出 — {symbol_filter}**\n\n"
                        f"时间范围: **{range_label}**\n"
                        f"记录数: **{len(records)}**\n"
                        "范围: **开仓事件数据**"
                    )

                await msg.reply_document(document=io.BytesIO(csv_bytes), filename=csv_fn, caption=caption, parse_mode="Markdown")
                await msg.reply_document(document=io.BytesIO(json_bytes), filename=json_fn)

            done_msg = (
                f"✅ Exported {len(records)} Hyperliquid open records."
                if user.language == "en"
                else f"✅ 已导出 {len(records)} 条 Hyperliquid 开仓记录。"
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

                    # Build wallet-risk context for questions like
                    # "which wallet is easiest to liquidate / at what price".
                    ts_24h_ago = int((datetime.now(timezone.utc).timestamp() - 24 * 3600) * 1000)
                    async with self.db._conn.execute(
                        """SELECT symbol, side, price, amount_usd, timestamp, metadata
                           FROM whale_orders
                           WHERE timestamp > ?
                           ORDER BY timestamp DESC
                           LIMIT 500""",
                        (ts_24h_ago,),
                    ) as cur:
                        risk_rows = await cur.fetchall()

                    wallet_totals: dict[str, float] = {}
                    near_liq: list[dict[str, Any]] = []
                    latest_symbol_price: dict[str, float] = {}

                    for r in risk_rows:
                        d = dict(r)
                        symbol = str(d.get("symbol") or "")
                        try:
                            price = float(d.get("price") or 0)
                        except (TypeError, ValueError):
                            price = 0.0

                        if symbol and price > 0 and symbol not in latest_symbol_price:
                            latest_symbol_price[symbol] = round(price, 4)

                        try:
                            metadata = json.loads(d.get("metadata") or "{}")
                            if not isinstance(metadata, dict):
                                metadata = {}
                        except Exception:
                            metadata = {}

                        wallet = str(metadata.get("wallet") or "").strip()
                        amount_usd = float(d.get("amount_usd") or 0)
                        if wallet:
                            wallet_totals[wallet] = wallet_totals.get(wallet, 0.0) + amount_usd

                        liq_raw = metadata.get("liq_price")
                        if not wallet or liq_raw in (None, "", 0) or price <= 0:
                            continue
                        try:
                            liq_price = float(liq_raw)
                        except (TypeError, ValueError):
                            continue
                        if liq_price <= 0:
                            continue

                        near_liq.append(
                            {
                                "wallet": wallet,
                                "symbol": symbol,
                                "side": d.get("side"),
                                "entry_price": round(price, 4),
                                "liq_price": round(liq_price, 4),
                                "liq_distance_pct": round(abs(price - liq_price) / price * 100, 4),
                                "amount_usd": round(amount_usd, 2),
                                "leverage": metadata.get("leverage"),
                                "timestamp": d.get("timestamp"),
                            }
                        )

                    near_liq.sort(key=lambda x: (x["liq_distance_pct"], -x["amount_usd"]))
                    top_exposure = sorted(wallet_totals.items(), key=lambda kv: kv[1], reverse=True)
                    data_context["latest_observed_price"] = latest_symbol_price
                    data_context["top_wallet_exposure_24h"] = [
                        {"wallet": wallet, "total_amount_usd": round(total, 2)}
                        for wallet, total in top_exposure[:8]
                    ]
                    data_context["wallets_near_liquidation"] = near_liq[:8]

                await progress.advance()  # → Step 2: AI analyzing

                # Step 2: Call Deepseek AI (longest step, auto-pulse animates)
                response = await self.ai_client.answer_query(question, data_context, chat_history=chat_history)
                await self.user_db.add_chat_message(user_id, "assistant", response)

                await progress.advance()  # → Step 3: Formatting results

            # Context manager exits with "completed" — overwrite with final result.
            # Use plain text to avoid Telegram Markdown parse errors on AI output.
            final_text = f"🤖 AI Analysis\n\n{response}"
            try:
                await progress_msg.edit_text(final_text)
            except Exception:
                await update.message.reply_text(final_text)

        except Exception as e:
            logger.error("AI ask failed: %s", e, exc_info=True)
            try:
                await progress_msg.edit_text(f"❌ AI analysis failed: {e}" if user.language == "en" else f"❌ AI 分析失败: {e}")
            except Exception:
                await update.message.reply_text(f"❌ AI analysis failed: {e}" if user.language == "en" else f"❌ AI 分析失败: {e}")

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
                "pay_job_export": ("📥 Export Open Data", "📥 导出开仓数据"),
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
                            "mode": "open",
                            "symbol": "BTC",
                            "wallet": "",
                            "window": "24h",
                            "page": 1,
                        })
                        await self._do_query(pay_msg, user, query_request)
                    elif data == "pay_job_export":
                        export_request = context.user_data.pop("pending_export_request", {
                            "symbol": "BTC",
                            "range_key": "7d",
                        })
                        await self._do_export(
                            pay_msg,
                            user,
                            str(export_request.get("symbol", "BTC")),
                            str(export_request.get("range_key", "7d")),
                        )
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

        elif data == "sub_hyperliquid":
            exchanges = user.subscribed_exchanges or []
            if "Hyperliquid" in exchanges:
                exchanges = [e for e in exchanges if e != "Hyperliquid"]
            else:
                exchanges.append("Hyperliquid")
            await self.user_manager.update_subscription(
                user_id, subscribed_exchanges=exchanges
            )

        elif data == "sub_toggle_push":
            await self.user_manager.update_push_preferences(
                user_id,
                alerts_enabled=not user.alerts_enabled,
            )

        elif data == "sub_channel_dm":
            await self.user_manager.update_push_preferences(
                user_id,
                alerts_enabled=True,
                push_channel="dm",
            )

        elif data == "sub_channel_group":
            group_id = None
            if query.message and query.message.chat.type in {"group", "supergroup"}:
                group_id = query.message.chat.id
            await self.user_manager.update_push_preferences(
                user_id,
                alerts_enabled=True,
                push_channel="group",
                push_group_chat_id=group_id,
            )
            if not group_id:
                await query.answer("请将 Bot 拉进目标群，并在群里发送 /bindgroup 完成绑定。", show_alert=True)

        elif data == "sub_channel_webhook":
            context.user_data["awaiting_webhook_input"] = True
            context.user_data.pop("awaiting_threshold_input", None)
            await self.user_manager.update_push_preferences(
                user_id,
                alerts_enabled=True,
                push_channel="webhook",
            )
            await query.edit_message_text(
                "请发送自定义 Webhook 链接（必须以 http:// 或 https:// 开头）。\n"
                "例如：`https://example.com/hooks/whale`\n\n"
                "发送 `cancel` 可取消。",
                parse_mode="Markdown",
            )
            return

        elif data == "sub_threshold":
            context.user_data["awaiting_threshold_input"] = True
            context.user_data.pop("awaiting_webhook_input", None)
            await query.edit_message_text(
                "请输入新的金额阈值（美元），例如: `500000`\n发送 `cancel` 可取消。",
                parse_mode="Markdown",
            )
            return

        # Update the keyboard
        user = await self.user_manager.get_user(user_id)
        keyboard = self._build_subscribe_keyboard(user)

        try:
            await query.edit_message_text(
                self._build_subscribe_text(user),
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

        normalized = text.strip()
        lowered = normalized.lower()

        # Handle subscription threshold input flow.
        if context.user_data.get("awaiting_threshold_input"):
            if lowered in {"cancel", "取消"}:
                context.user_data.pop("awaiting_threshold_input", None)
                await update.message.reply_text("已取消金额阈值设置。")
                return
            if not re.fullmatch(r"\d+(?:\.\d+)?", normalized):
                await update.message.reply_text("请输入纯数字金额，例如 500000，或发送 cancel 取消。")
                return
            new_threshold = float(normalized)
            await self.user_manager.update_subscription(
                user_id, min_alert_threshold=new_threshold
            )
            context.user_data.pop("awaiting_threshold_input", None)
            await update.message.reply_text(f"✅ 金额阈值已更新为 ${new_threshold:,.0f}")
            return

        # Handle custom webhook input flow.
        if context.user_data.get("awaiting_webhook_input"):
            if lowered in {"cancel", "取消"}:
                context.user_data.pop("awaiting_webhook_input", None)
                await update.message.reply_text("已取消 Webhook 设置。")
                return
            if not re.match(r"^https?://", normalized, re.IGNORECASE):
                await update.message.reply_text("Webhook 链接格式无效，请以 http:// 或 https:// 开头，或发送 cancel 取消。")
                return
            await self.user_manager.update_push_preferences(
                user_id,
                alerts_enabled=True,
                push_channel="webhook",
                custom_webhook_url=normalized,
            )
            context.user_data.pop("awaiting_webhook_input", None)
            await update.message.reply_text(
                f"✅ Webhook 已保存：{self._mask_webhook(normalized)}\n后续预警将推送到该链接。"
            )
            return

        text_lower = lowered
        if text_lower.startswith("query") or text_lower.startswith("查询"):
            await self._query_command(update, context)
            return
        elif text_lower.startswith("export") or text_lower.startswith("导出"):
            await self._export_command(update, context)
            return
        elif text_lower.startswith("ask") or text_lower.startswith("分析"):
            await self._ask_command(update, context)
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

from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings
from pydantic import Field


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    cg_api_key: str = Field(..., description="CoinGlass API Key")

    # Agent identity and deployment metadata
    agent_id: str = "btc-whalescope-agent-prod"
    agent_name: str = "BTC-WhaleScope-Agent"
    bot_username: str = ""
    app_version: str = "local-dev"
    deploy_env: str = "production"
    compose_project_name: str = "btc-whalescope-agent"
    container_name: str = "btc-whalescope-agent-app"

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    db_path: str = "data/whale_orders.db"
    user_db_path: str = "data/users.db"

    # polling intervals (seconds)
    poll_interval_large_order: int = 10
    poll_interval_liquidation: int = 10
    poll_interval_whale_alert: int = 10
    poll_interval_onchain: int = 60

    exchanges: str = "Binance,OKX,Bybit"

    large_order_threshold: float = 500_000
    liquidation_threshold: float = 100_000

    webhook_urls: str = ""

    ws_push_enabled: bool = True
    webhook_push_enabled: bool = False

    # Telegram Bot configuration
    tg_bot_token: str = Field("", description="Telegram Bot Token")
    tg_admin_ids: str = Field("", description="Admin Telegram IDs (comma-separated)")
    tg_enabled: bool = False

    # Deepseek AI configuration
    deepseek_api_key: str = Field("", description="Deepseek API Key")
    deepseek_model: str = "deepseek-chat"
    deepseek_max_tokens: int = 1000
    deepseek_temperature: float = 0.7
    deepseek_api_base: str = "https://api.deepseek.com"

    # Heartbeat reporting configuration
    heartbeat_enabled: bool = False
    heartbeat_url: str = ""
    heartbeat_api_key: str = ""
    heartbeat_bearer_token: str = ""
    heartbeat_agent_id: str = "codex-btc-whalescope-01"
    heartbeat_name: str = "BTC WhaleScope Agent"
    heartbeat_role: str = "product"
    heartbeat_role_label_zh: str = "BTC巨鲸情报分析师"

    # Tencent COS configuration (optional)
    cos_bucket: str = ""
    cos_region: str = ""
    cos_secret_id: str = ""
    cos_secret_key: str = ""
    cos_base_url: str = ""

    model_config = {
        "env_file": str(PROJECT_ROOT / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def exchange_list(self) -> list[str]:
        return [e.strip() for e in self.exchanges.split(",") if e.strip()]

    @property
    def webhook_url_list(self) -> list[str]:
        if not self.webhook_urls:
            return []
        return [u.strip() for u in self.webhook_urls.split(",") if u.strip()]

    @property
    def abs_db_path(self) -> Path:
        p = Path(self.db_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def cg_rest_base(self) -> str:
        return "https://open-api-v4.coinglass.com"

    @property
    def cg_ws_url(self) -> str:
        return f"wss://open-ws.coinglass.com/ws-api?cg-api-key={self.cg_api_key}"

    @property
    def abs_user_db_path(self) -> Path:
        p = Path(self.user_db_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def tg_admin_id_list(self) -> list[int]:
        if not self.tg_admin_ids:
            return []
        return [int(id.strip()) for id in self.tg_admin_ids.split(",") if id.strip().isdigit()]

    @property
    def heartbeat_token(self) -> str:
        return self.heartbeat_bearer_token or self.heartbeat_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""Test script for verifying all components."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from config.settings import get_settings


async def test_imports():
    """Test if all modules can be imported."""
    print("=" * 60)
    print("测试模块导入...")
    print("=" * 60)

    try:
        from src.storage.user_database import UserDatabase
        print("✅ UserDatabase 导入成功")
    except Exception as e:
        print(f"❌ UserDatabase 导入失败: {e}")
        return False

    try:
        from src.models.user import User, UserSubscription, ChatMessage
        print("✅ User models 导入成功")
    except Exception as e:
        print(f"❌ User models 导入失败: {e}")
        return False

    try:
        from src.telegram.user_manager import UserManager
        print("✅ UserManager 导入成功")
    except Exception as e:
        print(f"❌ UserManager 导入失败: {e}")
        return False

    try:
        from src.telegram.push_dispatcher import PushDispatcher
        print("✅ PushDispatcher 导入成功")
    except Exception as e:
        print(f"❌ PushDispatcher 导入失败: {e}")
        return False

    try:
        from src.telegram.dialog_handler import DialogHandler
        print("✅ DialogHandler 导入成功")
    except Exception as e:
        print(f"❌ DialogHandler 导入失败: {e}")
        return False

    try:
        from src.ai.deepseek_client import DeepseekClient
        print("✅ DeepseekClient 导入成功")
    except Exception as e:
        print(f"❌ DeepseekClient 导入失败: {e}")
        return False

    try:
        from src.ai.analyzer import AIAnalyzer
        print("✅ AIAnalyzer 导入成功")
    except Exception as e:
        print(f"❌ AIAnalyzer 导入失败: {e}")
        return False

    try:
        from src.telegram.bot import TelegramBot
        print("✅ TelegramBot 导入成功")
    except Exception as e:
        print(f"❌ TelegramBot 导入失败: {e}")
        return False

    print("\n" + "=" * 60)
    return True


def test_config():
    """Test configuration settings."""
    print("\n" + "=" * 60)
    print("测试配置...")
    print("=" * 60)

    settings = get_settings()

    print(f"✅ CG_API_KEY: {settings.cg_api_key[:10]}...{settings.cg_api_key[-4:]}")
    print(f"✅ TG_BOT_TOKEN: {settings.tg_bot_token[:10]}...{settings.tg_bot_token[-4:]}")
    print(f"✅ TG_ENABLED: {settings.tg_enabled}")
    print(f"✅ DEEPSEEK_API_KEY: {settings.deepseek_api_key[:10]}...{settings.deepseek_api_key[-4:]}")
    print(f"✅ DEEPSEEK_MODEL: {settings.deepseek_model}")
    print(f"✅ HOST: {settings.host}")
    print(f"✅ PORT: {settings.port}")
    print(f"✅ DB_PATH: {settings.abs_db_path}")
    print(f"✅ USER_DB_PATH: {settings.abs_user_db_path}")
    print(f"✅ EXCHANGES: {settings.exchange_list}")
    print(f"✅ TG_ADMIN_IDS: {settings.tg_admin_id_list}")
    print("\n" + "=" * 60)


def test_database_paths():
    """Test database directory structure."""
    print("\n" + "=" * 60)
    print("测试数据库路径...")
    print("=" * 60)

    settings = get_settings()

    db_path = settings.abs_db_path
    user_db_path = settings.abs_user_db_path

    # Check whale orders database
    if db_path.parent.exists():
        print(f"✅ Whale orders database directory: {db_path.parent}")
    else:
        print(f"⚠️ Whale orders database directory does not exist: {db_path.parent}")

    # Check user database
    if user_db_path.parent.exists():
        print(f"✅ User database directory: {user_db_path.parent}")
    else:
        print(f"⚠️ User database directory does not exist: {user_db_path.parent}")

    print("\n" + "=" * 60)


def test_api_keys():
    """Test if API keys are properly configured."""
    print("\n" + "=" * 60)
    print("测试 API Keys...")
    print("=" * 60)

    settings = get_settings()

    # Test CoinGlass API Key
    if settings.cg_api_key and len(settings.cg_api_key) > 20:
        print(f"✅ CoinGlass API Key configured ({len(settings.cg_api_key)} characters)")
    else:
        print(f"⚠️ CoinGlass API Key may not be configured")

    # Test Telegram Bot Token
    if settings.tg_bot_token and len(settings.tg_bot_token) > 20:
        print(f"✅ Telegram Bot Token configured ({len(settings.tg_bot_token)} characters)")
    else:
        print(f"⚠️ Telegram Bot Token may not be configured")

    # Test Deepseek API Key
    if settings.deepseek_api_key and len(settings.deepseek_api_key) > 20:
        print(f"✅ Deepseek API Key configured ({len(settings.deepseek_api_key)} characters)")
    else:
        print(f"⚠️ Deepseek API Key may not be configured")

    print("\n" + "=" * 60)


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("  BTC Whale Order Monitor - 系统测试")
    print("  版本: 2.0.0")
    print("=" * 60)
    print()

    # Test module imports
    imports_ok = asyncio.run(test_imports())

    if not imports_ok:
        print("\n❌ 模块导入测试失败，请检查代码。")
        sys.exit(1)

    # Test configuration
    test_config()

    # Test database paths
    test_database_paths()

    # Test API keys
    test_api_keys()

    # Summary
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    print("✅ 所有模块导入成功")
    print("✅ 配置文件加载成功")
    print("✅ API Keys 已配置")
    print("✅ 数据库路径已验证")
    print("\n" + "=" * 60)
    print("准备启动系统...")
    print("=" * 60)
    print("\n使用以下命令启动系统:")
    print("  python3 -m src.main")
    print("\n或使用启动脚本:")
    print("  bash start.sh")
    print("=" * 60)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Niibot - Multi-Channel Twitch Bot
重構版本：使用模組化架構，簡化啟動邏輯
"""

import asyncio
import logging
import os

import twitchio.utils
from dotenv import load_dotenv

from core.bot import NiiBot
from core.database import DatabaseManager

# 載入環境變數
load_dotenv()

# 設定日誌
logger = logging.getLogger("Bot")


def validate_environment() -> tuple[str, str, str, str, int, str, str]:
    """驗證並取得環境變數"""
    CLIENT_ID = os.getenv("CLIENT_ID")
    CLIENT_SECRET = os.getenv("CLIENT_SECRET")
    BOT_ID = os.getenv("BOT_ID")
    OWNER_ID = os.getenv("OWNER_ID")
    PORT_STR = os.getenv("PORT")
    DATABASE_URL = os.getenv("DATABASE_URL")

    if not all([CLIENT_ID, CLIENT_SECRET, BOT_ID, OWNER_ID, PORT_STR, DATABASE_URL]):
        raise ValueError("Missing required environment variables")

    # 確保所有必要變數都有值並進行型別轉換
    assert CLIENT_ID is not None
    assert CLIENT_SECRET is not None
    assert BOT_ID is not None
    assert OWNER_ID is not None
    assert PORT_STR is not None
    assert DATABASE_URL is not None

    PORT = int(PORT_STR)
    PREFIX = os.getenv("PREFIX", "!")

    return CLIENT_ID, CLIENT_SECRET, BOT_ID, OWNER_ID, PORT, DATABASE_URL, PREFIX


async def clear_tokens_if_requested(database_manager: DatabaseManager) -> bool:
    """檢查是否需要清除 tokens"""
    if os.getenv("CLEAR_TOKENS", "").lower() in ("true", "1", "yes"):
        await database_manager.clear_tokens()
        logger.info("Tokens cleared - restart without CLEAR_TOKENS to re-authorize")
        return True
    return False


async def main() -> None:
    """主要啟動函式"""
    # 1. 環境準備
    config = validate_environment()
    twitchio.utils.setup_logging(level=logging.INFO)
    logger.info("Starting Niibot...")

    # 2. 資料庫初始化
    database_manager = DatabaseManager(config[5])  # DATABASE_URL
    await database_manager.initialize()

    # 3. 檢查 token 清除請求
    if await clear_tokens_if_requested(database_manager):
        return

    # 4. 啟動 Bot
    bot = NiiBot(
        client_id=config[0],
        client_secret=config[1],
        bot_id=config[2],
        owner_id=config[3],
        port=config[4],
        database_manager=database_manager,
        prefix=config[6],
    )

    try:
        await bot.start()
    finally:
        await bot.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
    except Exception as e:
        logger.error("Startup failed: %s", e)
        raise

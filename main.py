"""
BTC Trading Bot - Entry point
"""
import asyncio
import logging
import sys
import os

# load_dotenv MUST happen before anything else so LOG_LEVEL and other env vars are available
from dotenv import load_dotenv
load_dotenv()

_log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=_log_level,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)

logger = logging.getLogger(__name__)


async def main():
    from bot import TradingBot
    logger.info("=" * 50)
    logger.info("BTC Trading Bot Starting...")
    logger.info("=" * 50)
    bot = TradingBot()
    await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")

import logging
import sys
from pathlib import Path

import yaml

from bot.telegram_handler import TelegramBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    config_path = Path(__file__).resolve().parent / "config.yaml"
    if not config_path.exists():
        logger.error("config.yaml not found at %s", config_path)
        sys.exit(1)

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    token = config.get("telegram", {}).get("bot_token", "")
    if not token or token == "YOUR_BOT_TOKEN_HERE":
        logger.error("Please set a valid Telegram bot_token in config.yaml")
        sys.exit(1)

    if not config.get("whitelist"):
        logger.error("Whitelist is empty in config.yaml — no users would be authorized")
        sys.exit(1)

    return config


def main():
    config = load_config()
    bot = TelegramBot(config)
    bot.run()


if __name__ == "__main__":
    main()

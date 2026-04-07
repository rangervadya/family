import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass
class BotSettings:
    telegram_token: str
    deepseek_api_url: str | None = None
    deepseek_api_key: str | None = None
    openweather_api_key: str | None = None
    default_timezone: str = "Europe/Moscow"
    # Если с Mac не достучаться до api.telegram.org — укажите HTTP(S) или SOCKS5 прокси (VPN).
    telegram_proxy: str | None = None
    telegram_connect_timeout: float = 30.0
    telegram_read_timeout: float = 30.0


def get_settings() -> BotSettings:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in environment")

    proxy = os.getenv("TELEGRAM_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("ALL_PROXY")

    def _timeout(name: str, default: float) -> float:
        raw = os.getenv(name)
        if raw is None or raw == "":
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    return BotSettings(
        telegram_token=token,
        deepseek_api_url=os.getenv("DEEPSEEK_API_URL"),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
        openweather_api_key=os.getenv("OPENWEATHER_API_KEY"),
        default_timezone=os.getenv("DEFAULT_TIMEZONE", "Europe/Moscow"),
        telegram_proxy=proxy,
        telegram_connect_timeout=_timeout("TELEGRAM_CONNECT_TIMEOUT", 30.0),
        telegram_read_timeout=_timeout("TELEGRAM_READ_TIMEOUT", 30.0),
    )


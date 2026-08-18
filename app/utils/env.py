"""
Загрузка переменных окружения из .env
"""
import os
from urllib.parse import urlsplit


def load_dotenv_file() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


def get_telegram_token() -> str:
    return (
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        or os.getenv("BOT_TOKEN", "").strip()
    )


def get_telegram_proxy_url(fallback: str = "") -> str:
    """Возвращает проверенный HTTP(S)-прокси для Telegram Bot API."""
    proxy_url = os.getenv("TELEGRAM_PROXY_URL", "").strip() or fallback.strip()
    if not proxy_url:
        return ""

    try:
        parsed = urlsplit(proxy_url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(
            "TELEGRAM_PROXY_URL должен быть корректным HTTP(S)-URL прокси"
        ) from exc

    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or port is None
        or any(char.isspace() for char in proxy_url)
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "TELEGRAM_PROXY_URL должен иметь формат http://[login:password@]host:port"
        )

    return proxy_url

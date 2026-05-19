"""
Пути к статическим изображениям для Telegram-бота.
"""
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"

MAIN_MENU_IMAGE = ASSETS_DIR / "funpaywizard-main.png"
PREVIEW_IMAGE = ASSETS_DIR / "funpaywizard-preview.png"
SUPPORT_IMAGE = ASSETS_DIR / "funpaywizard-support.png"

"""
Создание конфигов и минимальная подготовка к первому запуску.
Первичная настройка FunPay и пароля администратора — в Telegram-боте.
"""

import os
from configparser import ConfigParser

DEFAULT_CONFIG = {
    "FunPay": {
        "golden_key": "",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
        "autoRaise": "0",
        "autoResponse": "0",
        "autoDelivery": "0",
        "multiDelivery": "0",
        "autoRestore": "0",
        "autoDisable": "0"
    },
    "Telegram": {
        "enabled": "1",
        "token": "",
        "secretKey": "",
        "proxy": "",
        "groupTopicsEnabled": "0",
        "groupChatId": ""
    },
    "BlockList": {
        "blockDelivery": "0",
        "blockResponse": "0",
        "blockNewMessageNotification": "0",
        "blockNewOrderNotification": "0",
        "blockCommandNotification": "0"
    },
    "NewMessageView": {
        "includeMyMessages": "1",
        "includeFPMessages": "1",
        "includeBotMessages": "0",
        "notifyOnlyMyMessages": "0",
        "notifyOnlyFPMessages": "0",
        "notifyOnlyBotMessages": "0"
    },
    "Greetings": {
        "cacheInitChats": "0",
        "ignoreSystemMessages": "0",
        "sendGreetings": "0",
        "greetingsText": "Привет, $username!"
    },
    "OrderConfirm": {
        "sendReply": "1",
        "replyText": "$username, спасибо за подтверждение заказа $order_id!\nЕсли не сложно, оставь, пожалуйста, отзыв!"
    },
    "ReviewReply": {
        "star1Reply": "0",
        "star2Reply": "0",
        "star3Reply": "0",
        "star4Reply": "0",
        "star5Reply": "0",
        "star1ReplyText": "",
        "star2ReplyText": "",
        "star3ReplyText": "",
        "star4ReplyText": "",
        "star5ReplyText": "",
    },
    "Proxy": {
        "enable": "0",
        "ip": "",
        "port": "",
        "login": "",
        "password": "",
        "check": "0"
    },
    "Other": {
        "watermark": "",
        "requestsDelay": "4"
    }
}

MAIN_CONFIG_PATH = "configs/_main.cfg"


def create_config_obj(settings: dict) -> ConfigParser:
    config = ConfigParser(delimiters=(":", ), interpolation=None)
    config.optionxform = str
    config.read_dict(settings)
    return config


def is_setup_required(cfg: ConfigParser) -> bool:
    """Настройка не завершена, пока не заданы golden_key и пароль администратора."""
    if len(cfg["FunPay"]["golden_key"].strip()) != 32:
        return True
    if len(cfg["Telegram"]["secretKey"].strip()) < 4:
        return True
    return False


def ensure_config_files() -> None:
    os.makedirs("configs", exist_ok=True)
    for path in ("configs/auto_response.cfg", "configs/auto_delivery.cfg"):
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8"):
                pass


def create_initial_config(telegram_token: str = "") -> None:
    """Создаёт _main.cfg с пустым golden_key — настройка продолжится в боте."""
    ensure_config_files()
    config = create_config_obj(DEFAULT_CONFIG)
    config.set("Telegram", "enabled", "1")
    if telegram_token:
        config.set("Telegram", "token", telegram_token)
    with open(MAIN_CONFIG_PATH, "w", encoding="utf-8") as f:
        config.write(f)

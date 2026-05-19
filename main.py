import sys

if sys.version_info < (3, 9):
    print("FunPayWizard требует Python 3.9 или новее. "
          f"Сейчас: {sys.version.split()[0]}. "
          "Установите Python 3.10+ и запускайте им же (например: python3.11 main.py).")
    sys.exit(1)

import app.utils.config_loader as cfg_loader
from app.setup import create_initial_config, ensure_config_files
from app.utils.env import load_dotenv_file, get_telegram_token
from colorama import Fore, Style
import app.utils.logger
from app.utils.logger import LOGGER_CONFIG
import logging.config
import colorama
import sys
import os
from app.assistant import Assistant
import app.utils.exceptions as excs
from app.constants import translate as _
from app.logo import colorize_banner, funpay_banner, wizard_banner
from app.constants.texts import community_chat_url

# Фиолетовая палитра (256-color), чтобы FUNPAY и WIZARD отличались визуально
_C_FUNPAY = "\033[38;5;218m"    # светлый лавандовый
_C_WIZARD = "\033[38;5;99m"     # насыщенный фиолетовый
_C_VERSION = "\033[38;5;183m"
_C_META = "\033[38;5;147m"
_C_LINK = "\033[38;5;177m"

logo = (
    f"\n{colorize_banner(funpay_banner(), _C_FUNPAY, bright=Style.BRIGHT)}\n\n"
    f"{colorize_banner(wizard_banner(), _C_WIZARD, bright=Style.BRIGHT)}\n"
)

VERSION = "0.1.7"

if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))
else:
    os.chdir(os.path.dirname(__file__))

folders = ["configs", "logs", "storage", "storage/cache", "storage/products", "assets", "assets/static"]
for i in folders:
    if not os.path.exists(i):
        os.makedirs(i)

files = ["configs/auto_delivery.cfg", "configs/auto_response.cfg"]
for i in files:
    if not os.path.exists(i):
        with open(i, "w", encoding="utf-8") as f:
            ...

# UPDATE 0.0.9
if os.path.exists("storage/cache/block_list.json"):
    os.rename("storage/cache/block_list.json", "storage/cache/blacklist.json")
# UPDATE 0.0.9


colorama.init()


logging.config.dictConfig(LOGGER_CONFIG)
logging.raiseExceptions = False
logger = logging.getLogger("main")
logger.debug("------------------------------------------------------------------")


print(logo)
print(f"{_C_VERSION}{Style.BRIGHT}v{VERSION}{Style.RESET_ALL}\n")
print(f"{_C_META}{Style.BRIGHT}By {_C_LINK}{Style.BRIGHT}neluckoff{Style.RESET_ALL}")
print(f"{_C_META}{Style.BRIGHT} * GitHub: {_C_LINK}{Style.BRIGHT}https://github.com/neluckoff/FunPayWizard{Style.RESET_ALL}")
print(f"{_C_META}{Style.BRIGHT} * Telegram: {_C_LINK}{Style.BRIGHT}{community_chat_url}")
print(f"{_C_META}{Style.BRIGHT} * Developer Site: {_C_LINK}{Style.BRIGHT}https://neluckoff.me\n")


load_dotenv_file()
ensure_config_files()

if not os.path.exists("configs/_main.cfg"):
    tg_token = get_telegram_token()
    if not tg_token:
        print(f"{Fore.RED}{Style.BRIGHT}Не найден configs/_main.cfg и не задан TELEGRAM_BOT_TOKEN в .env{Style.RESET_ALL}")
        print(f"{Fore.CYAN}Скопируйте .env.example в .env и укажите токен бота от @BotFather.{Style.RESET_ALL}")
        sys.exit(1)
    create_initial_config(tg_token)
    print(f"{Fore.GREEN}{Style.BRIGHT}Создан configs/_main.cfg. Запустите бота и откройте его в Telegram для настройки.{Style.RESET_ALL}")


try:
    logger.info("$MAGENTAЗагружаю конфиг _main.cfg...")
    MAIN_CFG = cfg_loader.load_main_config("configs/_main.cfg")
    logger.info("$MAGENTAЗагружаю конфиг auto_response.cfg...")
    AR_CFG = cfg_loader.load_auto_response_config("configs/auto_response.cfg")
    RAW_AR_CFG = cfg_loader.load_raw_auto_response_config("configs/auto_response.cfg")

    logger.info("$MAGENTAЗагружаю конфиг auto_delivery.cfg...")
    AD_CFG = cfg_loader.load_auto_delivery_config("configs/auto_delivery.cfg")
except excs.ConfigParseError as e:
    logger.error(e)
    logger.error("Завершаю программу...")
    sys.exit()
except UnicodeDecodeError:
    logger.error("Произошла ошибка при расшифровке UTF-8. Убедитесь, что кодировка файла = UTF-8, "
                 "а формат конца строк = LF.")
    logger.error("Завершаю программу...")
    sys.exit()
except:
    logger.critical("Произошла непредвиденная ошибка.")
    logger.debug("TRACEBACK", exc_info=True)
    logger.error("Завершаю программу...")
    sys.exit()


try:
    Assistant(MAIN_CFG, AD_CFG, AR_CFG, RAW_AR_CFG, VERSION).init().run()
except KeyboardInterrupt:
    logger.info("Завершаю программу...")
    sys.exit()
except:
    logger.critical("При работе ассистента произошла необработанная ошибка.")
    logger.debug("TRACEBACK", exc_info=True)
    logger.critical("Завершаю программу...")
    sys.exit()

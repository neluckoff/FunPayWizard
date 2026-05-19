"""
В данном модуле написаны инструменты, которыми пользуется Telegram бот.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.assistant import Assistant
from app.constants import translate as _
from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B
import configparser
import datetime
import os.path
import json
import logging
import time
from os.path import exists
from api.common.utils import RegularExpressions
from bs4 import BeautifulSoup as bs
from bs4 import BeautifulSoup
from api.account import Account
from api.types import OrderStatuses
from api.updater.events import *
import app.utils.assistant_tools
from app.bot import callbacks as cb
import re

logger = logging.getLogger("TGBot")


class NotificationTypes:
    """
    Класс с типами Telegram уведомлений.
    """
    bot_start = "1"
    """Уведомление о старте бота."""
    new_message = "2"
    """Уведомление о новом сообщении."""
    command = "3"
    """Уведомление о введенной команде."""
    new_order = "4"
    """Уведомление о новом заказе."""
    order_confirmed = "5"
    """Уведомление о подтверждении заказа."""
    review = "5r"
    """Уведомление об отзыве."""
    lots_restore = "6"
    """Уведомление о восстановлении лота."""
    lots_deactivate = "7"
    """Уведомление о деактивации лота."""
    delivery = "8"
    """Уведомление о выдаче товара."""
    lots_raise = "9"
    """Уведомление о поднятии лотов."""
    other = "10"
    """Прочие уведомления (плагины)."""
    announcement = "11"
    """Новости / объявления."""
    ad = "12"
    """Реклама."""
    critical = "13"
    """Не отключаемые критически важные уведомления."""
    daily_stats = "14"
    """Вечерняя сводка за день (заказы, незакрытые, заработок)."""


def load_json_cache(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.loads(f.read())
    except (OSError, json.JSONDecodeError):
        logger.warning(f"Не удалось загрузить JSON-кэш {path}. Использую значение по умолчанию.")
        logger.debug("TRACEBACK", exc_info=True)
        return default


def load_authorized_users() -> list[int]:
    """
    Загружает авторизированных пользователей из кэша.

    :return: список из id авторизированных пользователей.
    """
    return load_json_cache("storage/cache/tg_authorized_users.json", [])


def load_notification_settings() -> dict:
    """
    Загружает настройки Telegram уведомлений из кэша.

    :return: настройки Telegram уведомлений.
    """
    return load_json_cache("storage/cache/notifications.json", {})


def load_answer_templates() -> list[str]:
    """
    Загружает шаблоны ответов из кэша.

    :return: шаблоны ответов из кэша.
    """
    return load_json_cache("storage/cache/answer_templates.json", [])


def save_authorized_users(users: list[int]) -> None:
    """
    Сохраняет ID авторизированных пользователей.

    :param users: список id авторизированных пользователей.
    """
    if not os.path.exists("storage/cache/"):
        os.makedirs("storage/cache/")
    with open("storage/cache/tg_authorized_users.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(users))


def save_json_cache(path: str, data) -> None:
    if not os.path.exists("storage/cache/"):
        os.makedirs("storage/cache/")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False))


def save_notification_settings(settings: dict) -> None:
    """
    Сохраняет настройки Telegram-уведомлений.

    :param settings: настройки Telegram-уведомлений.
    """
    if not os.path.exists("storage/cache/"):
        os.makedirs("storage/cache/")
    with open("storage/cache/notifications.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(settings))


def save_answer_templates(templates: list[str]) -> None:
    """
    Сохраняет шаблоны ответов.

    :param templates: список шаблонов.
    """
    if not os.path.exists("storage/cache/"):
        os.makedirs("storage/cache")
    with open("storage/cache/answer_templates.json", "w", encoding="utf-8") as f:
        f.write(json.dumps(templates))


def format_order_price(price: float, currency: str) -> str:
    sym = {"RUB": "₽", "USD": "$", "EUR": "€"}
    amount = f"{price:g}"
    sign = sym.get(currency, currency)
    if currency == "USD":
        return f"{sign}{amount}"
    return f"{amount} {sign}"


def escape(text: str) -> str:
    """
    Форматирует текст под HTML разметку.

    :param text: текст.
    :return: форматированный текст.
    """
    escape_characters = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
    }
    for char in escape_characters:
        text = text.replace(char, escape_characters[char])
    return text


def bool_to_text(value: bool | int | str | None, on: str = "🟢", off: str = "🔴"):
    if value is not None and int(value):
        return on
    return off


def get_offset(element_index: int, max_elements_on_page: int) -> int:
    """
    Возвращает смещение списка элементов таким образом, чтобы элемент с индексом element_index оказался в конце списка.

    :param element_index: индекс элемента, который должен оказаться в конце.
    :param max_elements_on_page: максимальное кол-во элементов на 1 странице.
    """
    elements_amount = element_index + 1
    elements_on_page = elements_amount % max_elements_on_page
    elements_on_page = elements_on_page if elements_on_page else max_elements_on_page
    if not elements_amount - elements_on_page:  # если это первая группа команд:
        return 0
    else:
        return element_index - elements_on_page + 1


def add_navigation_buttons(keyboard_obj: K, curr_offset: int,
                           max_elements_on_page: int,
                           elements_on_page: int, elements_amount: int,
                           callback_text: str,
                           extra: list | None = None) -> K:
    """
    Добавляет к переданной клавиатуре кнопки след. / пред. страница.

    :param keyboard_obj: экземпляр клавиатуры.
    :param curr_offset: текущее смещение списка.
    :param max_elements_on_page: максимальное кол-во кнопок на 1 странице.
    :param elements_on_page: текущее кол-во элементов на странице.
    :param elements_amount: общее кол-во элементов.
    :param callback_text: текст callback'а.
    :param extra: доп. данные (будут перечислены через ":")
    """
    extra = (":" + ":".join(str(i) for i in extra)) if extra else ""
    back, forward = True, True

    if curr_offset > 0:
        back_offset = curr_offset - max_elements_on_page if curr_offset > max_elements_on_page else 0
        back_cb = f"{callback_text}:{back_offset}{extra}"
        first_cb = f"{callback_text}:0{extra}"
    else:
        back, back_cb, first_cb = False, cb.EMPTY, cb.EMPTY

    if curr_offset + elements_on_page < elements_amount:
        forward_offset = curr_offset + elements_on_page
        last_page_offset = get_offset(elements_amount - 1, max_elements_on_page)
        forward_cb = f"{callback_text}:{forward_offset}{extra}"
        last_cb = f"{callback_text}:{last_page_offset}{extra}"
    else:
        forward, forward_cb, last_cb = False, cb.EMPTY, cb.EMPTY

    if back or forward:
        keyboard_obj.row(B("◀️◀️", callback_data=first_cb), B("◀️", callback_data=back_cb),
                         B("▶️", callback_data=forward_cb), B("▶️▶️", callback_data=last_cb))
    return keyboard_obj



def generate_profile_text(assistant: Assistant) -> str:
    """
    Генерирует текст с информацией об аккаунте.

    :return: сгенерированный текст с информацией об аккаунте.
    """
    account = assistant.account
    balance = assistant.balance
    return f"""Статистика аккаунта <b><i>{account.username}</i></b>

<b>ID:</b> <code>{account.id}</code>
<b>Незавершенных заказов:</b> <code>{account.active_sales}</code>
<b>Баланс:</b> 
    <b>₽:</b> <code>{balance.total_rub}₽</code>, доступно для вывода <code>{balance.available_rub}₽</code>.
    <b>$:</b> <code>{balance.total_usd}$</code>, доступно для вывода <code>{balance.available_usd}$</code>.
    <b>€:</b> <code>{balance.total_eur}€</code>, доступно для вывода <code>{balance.available_eur}€</code>.

<i>Обновлено:</i>  <code>{time.strftime('%H:%M:%S', time.localtime(account.last_update))}</code>"""

ORDER_CONFIRMED = {}

def message_hook(assistant: Assistant, event: NewMessageEvent):
    if event.message.type not in [MessageTypes.ORDER_CONFIRMED, MessageTypes.ORDER_CONFIRMED_BY_ADMIN, MessageTypes.ORDER_REOPENED, MessageTypes.REFUND]:
        return
    if event.message.type not in [MessageTypes.ORDER_REOPENED, MessageTypes.REFUND] and bs(event.message.html, "html.parser").find("a").text == assistant.account.username:
        return

    id = RegularExpressions().ORDER_ID.findall(str(event.message))[0][1:]

    if event.message.type in [MessageTypes.ORDER_REOPENED, MessageTypes.REFUND]:
        if id in ORDER_CONFIRMED:
            del ORDER_CONFIRMED[id]
    else:
        ORDER_CONFIRMED[id] = {"time": time.time(), "price": assistant.account.get_order(id).sum}
        with open("storage/cache/advProfileStat.json", "w", encoding="UTF-8") as f:
            f.write(json.dumps(ORDER_CONFIRMED, indent=4, ensure_ascii=False))

def extract_float(text: str) -> float:
    """Преобразует строку с ценой в число (пробелы, запятая/точка)."""
    s = re.sub(r"[^\d,\.]", "", text).replace("\u00A0", "").replace(" ", "")
    if not s:
        return 0.0
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def generate_adv_profile(assistant: Assistant) -> str:
    """
    Генерирует расширенную статистику профиля.
    При ошибках парсинга возвращает частичные данные без падения.
    """
    account = assistant.account
    balance = assistant.balance

    if balance.total_eur:
        currency, balance_value = "€", balance.total_eur
    elif balance.total_usd:
        currency, balance_value = "$", balance.total_usd
    elif balance.total_rub:
        currency, balance_value = "₽", balance.total_rub
    else:
        currency, balance_value = "₽", 0.0

    global ORDER_CONFIRMED
    if exists("storage/cache/advProfileStat.json"):
        ORDER_CONFIRMED = load_json_cache("storage/cache/advProfileStat.json", {})

    canWithdraw = {"now": "0", "hour": 0.0, "day": 0.0, "2day": 0.0}
    balance_display = f"{balance_value}"

    for order in ORDER_CONFIRMED.copy():
        if time.time() - ORDER_CONFIRMED[order]["time"] > 172800:
            del ORDER_CONFIRMED[order]
            continue
        if time.time() - ORDER_CONFIRMED[order]["time"] > 169200:
            canWithdraw["hour"] += ORDER_CONFIRMED[order]["price"]
        elif time.time() - ORDER_CONFIRMED[order]["time"] > 86400:
            canWithdraw["day"] += ORDER_CONFIRMED[order]["price"]
        else:
            canWithdraw["2day"] += ORDER_CONFIRMED[order]["price"]

    try:
        random_lot_link = bs(
            account.method("get", "https://funpay.com/lots/693/", {}, {}).text, "html.parser"
        ).find("a", {"class": "tc-item"})["href"]
        random_lot_page = bs(account.method("get", random_lot_link, {}, {}).text, "html.parser")
        parsed_balance = random_lot_page.select_one(".badge-balance").text.split(" ")
        balance_display, currency = parsed_balance[0], parsed_balance[1]
        selectpicker = random_lot_page.find("select", {"class": "form-control input-lg selectpicker"})
        if currency == "₽":
            canWithdraw["now"] = str(selectpicker.get("data-balance-rub", 0) or 0)
        elif currency == "$":
            canWithdraw["now"] = str(selectpicker.get("data-balance-usd", 0) or 0)
        elif currency == "€":
            canWithdraw["now"] = str(selectpicker.get("data-balance-eur", 0) or 0)
    except Exception:
        if currency == "₽":
            canWithdraw["now"] = str(balance.available_rub)
        elif currency == "$":
            canWithdraw["now"] = str(balance.available_usd)
        elif currency == "€":
            canWithdraw["now"] = str(balance.available_eur)

    try:
        next_order_id, all_sales = account.get_sells()
        while next_order_id is not None:
            time.sleep(1)
            next_order_id, new_sales = account.get_sells(start_from=next_order_id)
            all_sales += new_sales
    except Exception:
        logger.debug("TRACEBACK", exc_info=True)
        all_sales = []

    currencies = ["USD", "RUB", "EUR"]
    sym = {"USD": "$", "RUB": "₽", "EUR": "€"}
    stats = {
        cur: {
            "sales": {"day": 0, "week": 0, "month": 0, "all": 0},
            "salesPrice": {"day": 0.0, "week": 0.0, "month": 0.0, "all": 0.0},
            "refunds": {"day": 0, "week": 0, "month": 0, "all": 0},
            "refundsPrice": {"day": 0.0, "week": 0.0, "month": 0.0, "all": 0.0},
        }
        for cur in currencies
    }

    now_dt = datetime.datetime.now()
    for sale in all_sales:
        cur = getattr(sale, "currency", None)
        if cur not in stats:
            continue
        is_refund = sale.status == OrderStatuses.REFUNDED
        delta = now_dt - sale.date if hasattr(sale, "date") else datetime.timedelta.max

        if is_refund:
            stats[cur]["refunds"]["all"] += 1
            stats[cur]["refundsPrice"]["all"] += sale.price
        else:
            stats[cur]["sales"]["all"] += 1
            stats[cur]["salesPrice"]["all"] += sale.price

        if delta <= datetime.timedelta(days=1):
            if is_refund:
                stats[cur]["refunds"]["day"] += 1
                stats[cur]["refundsPrice"]["day"] += sale.price
            else:
                stats[cur]["sales"]["day"] += 1
                stats[cur]["salesPrice"]["day"] += sale.price
        if delta <= datetime.timedelta(days=7):
            if is_refund:
                stats[cur]["refunds"]["week"] += 1
                stats[cur]["refundsPrice"]["week"] += sale.price
            else:
                stats[cur]["sales"]["week"] += 1
                stats[cur]["salesPrice"]["week"] += sale.price
        if delta <= datetime.timedelta(days=30):
            if is_refund:
                stats[cur]["refunds"]["month"] += 1
                stats[cur]["refundsPrice"]["month"] += sale.price
            else:
                stats[cur]["sales"]["month"] += 1
                stats[cur]["salesPrice"]["month"] += sale.price

    sales_blocks = []
    refunds_blocks = []
    for cur in currencies:
        if stats[cur]["sales"]["all"] or stats[cur]["refunds"]["all"]:
            s, sp = stats[cur]["sales"], stats[cur]["salesPrice"]
            r, rp = stats[cur]["refunds"], stats[cur]["refundsPrice"]
            curr_sym = sym[cur]
            sales_blocks.append(
                f"<b>{curr_sym}</b>\n"
                f"<b>За день:</b> <code>{s['day']} ({sp['day']:.1f} {curr_sym})</code>\n"
                f"<b>За неделю:</b> <code>{s['week']} ({sp['week']:.1f} {curr_sym})</code>\n"
                f"<b>За месяц:</b> <code>{s['month']} ({sp['month']:.1f} {curr_sym})</code>\n"
                f"<b>За всё время:</b> <code>{s['all']} ({sp['all']:.1f} {curr_sym})</code>"
            )
            refunds_blocks.append(
                f"<b>{curr_sym}</b>\n"
                f"<b>За день:</b> <code>{r['day']} ({rp['day']:.1f} {curr_sym})</code>\n"
                f"<b>За неделю:</b> <code>{r['week']} ({rp['week']:.1f} {curr_sym})</code>\n"
                f"<b>За месяц:</b> <code>{r['month']} ({rp['month']:.1f} {curr_sym})</code>\n"
                f"<b>За всё время:</b> <code>{r['all']} ({rp['all']:.1f} {curr_sym})</code>"
            )

    sales_text = "\n\n".join(sales_blocks) if sales_blocks else "<i>Нет данных</i>"
    refunds_text = "\n\n".join(refunds_blocks) if refunds_blocks else "<i>Нет данных</i>"

    return f"""Статистика аккаунта <b><i>{account.username}</i></b>

<b>ID:</b> <code>{account.id}</code>
<b>Баланс:</b> <code>{balance_display} {currency}</code>
<b>Незавершенных заказов:</b> <code>{account.active_sales}</code>

<b>Доступно для вывода</b>
<b>Сейчас:</b> <code>{str(canWithdraw["now"]).split('.')[0]} {currency}</code>
<b>Через час:</b> <code>+{canWithdraw["hour"]:.1f} {currency}</code>
<b>Через день:</b> <code>+{canWithdraw["day"]:.1f} {currency}</code>
<b>Через 2 дня:</b> <code>+{canWithdraw["2day"]:.1f} {currency}</code>

<b>Товаров продано (по валютам)</b>
{sales_text}

<b>Товаров возвращено (по валютам)</b>
{refunds_text}

<i>Обновлено:</i>  <code>{time.strftime('%H:%M:%S', time.localtime(account.last_update))}</code>"""


def get_orders(acc: Account, start_from: str) -> tuple[str | None, list[str]]:
    """
    Получает страницу незакрытых (оплаченных) заказов.
    :return: (ID следующей страницы, список ID заказов).
    """
    attempts = 3
    while attempts:
        try:
            result = acc.get_sells(
                start_from=start_from or None,
                state="paid",
                include_paid=True,
                include_closed=False,
                include_refunded=False,
            )
            break
        except:
            attempts -= 1
            time.sleep(1)
    else:
        raise Exception
    orders = [f"#{order.id}" for order in result[1]]
    return result[0], orders

def get_all_open_orders(acc: Account) -> list[str]:
    """
    Получает список всех незакрытых (оплаченных) заказов на аккаунте.
    :param acc: экземпляр аккаунта.
    :return: список ID заказов.
    """
    start_from = ""
    open_orders = []
    while start_from is not None:
        result = get_orders(acc, start_from)
        start_from = result[0]
        open_orders.extend(result[1])
        time.sleep(1)
    return open_orders

def generate_lot_info_text(lot_obj: configparser.SectionProxy) -> str:
    """
    Генерирует текст с информацией о лоте.

    :param lot_obj: секция лота в конфиге автовыдачи.

    :return: сгенерированный текст с информацией о лоте.
    """
    if lot_obj.get("productsFileName") is None:
        file_path = "<b><u>не привязан.</u></b>"
        products_amount = "<code>∞</code>"
    else:
        file_path = f"<code>storage/products/{lot_obj.get('productsFileName')}</code>"
        if not os.path.exists(f"storage/products/{lot_obj.get('productsFileName')}"):
            with open(f"storage/products/{lot_obj.get('productsFileName')}", "w", encoding="utf-8"):
                pass
        products_amount = app.utils.assistant_tools.count_products(f"storage/products/{lot_obj.get('productsFileName')}")
        products_amount = f"<code>{products_amount}</code>"

    message = f"""<b>{escape(lot_obj.name)}</b>\n
<b><i>Текст выдачи:</i></b> <code>{escape(lot_obj["response"])}</code>\n
<b><i>Кол-во товаров: </i></b> {products_amount}\n
<b><i>Файл с товарами: </i></b>{file_path}\n
<i>Обновлено:</i>  <code>{datetime.datetime.now().strftime('%H:%M:%S')}</code>"""
    return message

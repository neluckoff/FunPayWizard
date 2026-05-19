"""
Вечерняя сводка по заказам за день (уведомление в личные чаты).
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import datetime
import logging
import time
from threading import Thread

from api.common.enums import OrderStatuses

from app.bot import helpers
from app.constants import translate as _

if TYPE_CHECKING:
    from app.assistant import Assistant

logger = logging.getLogger("FPW.daily_stats")

CACHE_PATH = "storage/cache/daily_stats.json"
REPORT_HOUR = 23


def fetch_all_sales(account) -> list:
    try:
        next_order_id, sales = account.get_sells()
        while next_order_id is not None:
            time.sleep(1)
            next_order_id, batch = account.get_sells(start_from=next_order_id)
            sales += batch
        return sales
    except Exception:
        logger.error("Не удалось загрузить список заказов для дневной сводки.")
        logger.debug("TRACEBACK", exc_info=True)
        return []


def collect_today_stats(sales: list, now: datetime.datetime | None = None) -> dict:
    now = now or datetime.datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    stats = {
        "date": now.strftime("%d.%m.%Y"),
        "orders_today": 0,
        "unclosed": 0,
        "earned": {"RUB": 0.0, "USD": 0.0, "EUR": 0.0},
    }

    for sale in sales:
        if sale.status == OrderStatuses.PAID:
            stats["unclosed"] += 1

        sale_date = getattr(sale, "date", None)
        if not sale_date or sale_date < today_start:
            continue

        if sale.status == OrderStatuses.REFUNDED:
            continue

        stats["orders_today"] += 1

        if sale.status == OrderStatuses.CLOSED:
            cur = getattr(sale, "currency", None)
            if cur in stats["earned"]:
                stats["earned"][cur] += float(sale.price)

    return stats


def format_daily_stats_message(stats: dict) -> str:
    earned_lines = []
    for cur in ("RUB", "USD", "EUR"):
        amount = stats["earned"][cur]
        if amount > 0:
            earned_lines.append(f"• <code>{helpers.format_order_price(amount, cur)}</code>")

    earned_block = "\n".join(earned_lines) if earned_lines else "• <code>0 ₽</code>"

    return _("ntfc_daily_stats",
               stats["date"],
               stats["orders_today"],
               stats["unclosed"],
               earned_block)


def _already_sent_today(today: datetime.date) -> bool:
    data = helpers.load_json_cache(CACHE_PATH, {})
    return data.get("date") == today.isoformat()


def _mark_sent_today(today: datetime.date) -> None:
    helpers.save_json_cache(CACHE_PATH, {"date": today.isoformat()})


def send_daily_stats(assistant: "Assistant") -> None:
    if not assistant.telegram or not assistant.account.is_initiated:
        return

    sales = fetch_all_sales(assistant.account)
    stats = collect_today_stats(sales)
    text = format_daily_stats_message(stats)
    assistant.telegram.send_notification(text, notification_type=helpers.NotificationTypes.daily_stats)
    logger.info(
        "Отправлена дневная сводка: заказов %s, незакрытых %s.",
        stats["orders_today"], stats["unclosed"],
    )


def daily_stats_loop(assistant: "Assistant") -> None:
    logger.info("Запущен цикл вечерней сводки (отправка в %s:00).", REPORT_HOUR)
    while True:
        try:
            now = datetime.datetime.now()
            if now.hour == REPORT_HOUR and not _already_sent_today(now.date()):
                send_daily_stats(assistant)
                _mark_sent_today(now.date())
        except Exception:
            logger.error("Ошибка в цикле вечерней сводки.")
            logger.debug("TRACEBACK", exc_info=True)
        time.sleep(60)


def start_daily_stats_loop(assistant: "Assistant", *_args) -> None:
    Thread(target=daily_stats_loop, args=(assistant,), daemon=True).start()

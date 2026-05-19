"""
Напоминание покупателю оставить отзыв через 12 часов после завершения заказа.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from threading import Thread
from typing import TYPE_CHECKING

import api.types as types
from app.utils import assistant_tools

if TYPE_CHECKING:
    from app.assistant import Assistant

logger = logging.getLogger("FPW.review_reminder")

CACHE_PATH = "storage/cache/review_reminders.json"
REMINDER_DELAY_SECONDS = 12 * 3600
POLL_INTERVAL_SECONDS = 60


def _load_store() -> list[dict]:
    if not os.path.exists(CACHE_PATH):
        return []
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        pending = data.get("pending", [])
        return pending if isinstance(pending, list) else []
    except (OSError, json.JSONDecodeError):
        logger.warning("Не удалось загрузить %s.", CACHE_PATH)
        logger.debug("TRACEBACK", exc_info=True)
        return []


def _save_store(pending: list[dict]) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump({"pending": pending}, f, ensure_ascii=False)


def _has_review(order) -> bool:
    review = getattr(order, "review", None)
    return bool(review and getattr(review, "stars", None))


def schedule_review_reminder(assistant: Assistant, order: types.OrderShortcut) -> None:
    """Ставит напоминание в очередь после подтверждения заказа."""
    if not assistant.MAIN_CFG["ReviewReminder"].getboolean("sendReminder"):
        return
    if order.status is not types.OrderStatuses.CLOSED:
        return

    pending = _load_store()
    if any(item.get("order_id") == order.id for item in pending):
        return

    send_at = time.time() + REMINDER_DELAY_SECONDS
    pending.append({
        "order_id": order.id,
        "buyer_username": order.buyer_username,
        "send_at": send_at,
    })
    _save_store(pending)
    logger.info(
        "Напоминание об отзыве для заказа $YELLOW%s$RESET (%s) запланировано на %s.",
        order.id,
        order.buyer_username,
        datetime.fromtimestamp(send_at).strftime("%d-%m-%Y %H:%M:%S"),
    )


def cancel_review_reminder(order_id: str) -> None:
    """Убирает напоминание, если покупатель уже оставил отзыв."""
    pending = _load_store()
    new_pending = [item for item in pending if item.get("order_id") != order_id]
    if len(new_pending) != len(pending):
        _save_store(new_pending)
        logger.info("Напоминание об отзыве для заказа $YELLOW%s$RESET отменено (отзыв получен).", order_id)


def _send_reminder(assistant: Assistant, item: dict) -> bool:
    order_id = item.get("order_id")
    username = item.get("buyer_username")
    if not order_id or not username:
        return True

    try:
        order = assistant.account.get_order(order_id)
    except Exception:
        logger.error("Не удалось получить заказ #%s для напоминания об отзыве.", order_id)
        logger.debug("TRACEBACK", exc_info=True)
        return False

    if _has_review(order):
        logger.info("Заказ #%s уже с отзывом — напоминание не отправляю.", order_id)
        return True

    text = assistant_tools.format_order_text(
        assistant.MAIN_CFG["ReviewReminder"]["reminderText"],
        order,
    )
    chat = assistant.account.get_chat_by_name(username, True)
    try:
        assistant.send_message(chat.id, text, username)
        logger.info(
            "Отправлено напоминание об отзыве по заказу $YELLOW%s$RESET покупателю $YELLOW%s$RESET.",
            order_id,
            username,
        )
        return True
    except Exception:
        logger.error("Не удалось отправить напоминание об отзыве по заказу #%s.", order_id)
        logger.debug("TRACEBACK", exc_info=True)
        return False


def process_due_review_reminders(assistant: Assistant) -> None:
    """Отправляет напоминания, у которых наступило время."""
    if not assistant.MAIN_CFG["ReviewReminder"].getboolean("sendReminder"):
        return

    now = time.time()
    pending = _load_store()
    if not pending:
        return

    remaining = []
    for item in pending:
        send_at = float(item.get("send_at", 0))
        if send_at > now:
            remaining.append(item)
            continue
        if not _send_reminder(assistant, item):
            remaining.append(item)

    _save_store(remaining)


def review_reminder_loop(assistant: Assistant) -> None:
    logger.info("Запущен цикл напоминаний об отзыве (через %s ч после завершения заказа).",
                REMINDER_DELAY_SECONDS // 3600)
    while True:
        try:
            process_due_review_reminders(assistant)
        except Exception:
            logger.error("Ошибка в цикле напоминаний об отзыве.")
            logger.debug("TRACEBACK", exc_info=True)
        time.sleep(POLL_INTERVAL_SECONDS)


def start_review_reminder_loop(assistant: Assistant, *_args) -> None:
    Thread(target=review_reminder_loop, args=(assistant,), daemon=True).start()

"""
Локальное время для FunPay (даты на сайте и «день» в сводках).

По умолчанию Europe/Moscow. Переопределение: FPW_TIMEZONE или TZ.
"""
from __future__ import annotations

import datetime
import logging
import os
from zoneinfo import ZoneInfo

logger = logging.getLogger("FPW.local_time")

DEFAULT_TZ = "Europe/Moscow"


def get_timezone_name() -> str:
    return (os.environ.get("FPW_TIMEZONE") or os.environ.get("TZ") or DEFAULT_TZ).strip()


def get_timezone() -> ZoneInfo:
    name = get_timezone_name()
    try:
        return ZoneInfo(name)
    except Exception:
        logger.warning("Неизвестная зона %r, используется %s.", name, DEFAULT_TZ)
        return ZoneInfo(DEFAULT_TZ)


def local_now() -> datetime.datetime:
    """Текущее время в настроенной зоне (aware)."""
    return datetime.datetime.now(get_timezone())


def local_now_naive() -> datetime.datetime:
    """Наивное локальное время — для сравнения с датами заказов FunPay."""
    return local_now().replace(tzinfo=None)

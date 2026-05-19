"""
Настраиваемая аналитика FunPay: выбор блоков отчёта и сбор статистики.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import datetime
import logging
import time
from os.path import exists

from api.common.enums import OrderStatuses
from bs4 import BeautifulSoup as bs

from app.bot import helpers
from app.bot.daily_stats import collect_today_stats, fetch_all_sales
from app.constants import translate as _

if TYPE_CHECKING:
    from app.assistant import Assistant

logger = logging.getLogger("TGBot.analytics")

PREFS_PATH = "storage/cache/analytics_prefs.json"

SECTIONS = ("balance", "withdraw", "sales", "refunds", "today", "lots")

DEFAULT_PREFS = {
    "balance": True,
    "withdraw": False,
    "sales": True,
    "refunds": True,
    "today": True,
    "lots": True,
}

_LABEL_KEYS = {
    "balance": "an_balance",
    "withdraw": "an_withdraw",
    "sales": "an_sales",
    "refunds": "an_refunds",
    "today": "an_today",
    "lots": "an_lots",
}


def section_label(section_id: str) -> str:
    return _(_LABEL_KEYS[section_id])


def load_prefs() -> dict:
    return helpers.load_json_cache(PREFS_PATH, {})


def save_prefs(data: dict) -> None:
    helpers.save_json_cache(PREFS_PATH, data)


def get_user_prefs(user_id: int) -> dict[str, bool]:
    raw = load_prefs()
    stored = raw.get(str(user_id), {})
    prefs = dict(DEFAULT_PREFS)
    for key in SECTIONS:
        if key in stored:
            prefs[key] = bool(stored[key])
    return prefs


def set_user_pref(user_id: int, section_id: str, enabled: bool) -> dict[str, bool]:
    if section_id not in SECTIONS:
        return get_user_prefs(user_id)
    data = load_prefs()
    uid = str(user_id)
    user = dict(DEFAULT_PREFS)
    user.update(data.get(uid, {}))
    user[section_id] = enabled
    data[uid] = user
    save_prefs(data)
    return get_user_prefs(user_id)


def toggle_user_pref(user_id: int, section_id: str) -> dict[str, bool]:
    prefs = get_user_prefs(user_id)
    return set_user_pref(user_id, section_id, not prefs.get(section_id, False))


def enabled_sections(user_id: int) -> list[str]:
    prefs = get_user_prefs(user_id)
    return [s for s in SECTIONS if prefs.get(s)]


def _sales_stats(all_sales: list) -> dict:
    currencies = ["USD", "RUB", "EUR"]
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

        bucket = "refunds" if is_refund else "sales"
        price_bucket = "refundsPrice" if is_refund else "salesPrice"
        stats[cur][bucket]["all"] += 1
        stats[cur][price_bucket]["all"] += sale.price

        if delta <= datetime.timedelta(days=1):
            stats[cur][bucket]["day"] += 1
            stats[cur][price_bucket]["day"] += sale.price
        if delta <= datetime.timedelta(days=7):
            stats[cur][bucket]["week"] += 1
            stats[cur][price_bucket]["week"] += sale.price
        if delta <= datetime.timedelta(days=30):
            stats[cur][bucket]["month"] += 1
            stats[cur][price_bucket]["month"] += sale.price
    return stats


def _format_currency_blocks(stats: dict, bucket: str, price_bucket: str) -> str:
    sym = {"USD": "$", "RUB": "₽", "EUR": "€"}
    blocks = []
    for cur in ("RUB", "USD", "EUR"):
        counts = stats[cur][bucket]
        prices = stats[cur][price_bucket]
        if not counts["all"]:
            continue
        curr_sym = sym[cur]
        blocks.append(
            f"<b>{curr_sym}</b>\n"
            f"<b>За день:</b> <code>{counts['day']} ({prices['day']:.1f} {curr_sym})</code>\n"
            f"<b>За неделю:</b> <code>{counts['week']} ({prices['week']:.1f} {curr_sym})</code>\n"
            f"<b>За месяц:</b> <code>{counts['month']} ({prices['month']:.1f} {curr_sym})</code>\n"
            f"<b>За всё время:</b> <code>{counts['all']} ({prices['all']:.1f} {curr_sym})</code>"
        )
    return "\n\n".join(blocks) if blocks else "<i>Нет данных</i>"


def _withdraw_block(assistant: Assistant) -> str:
    from app.bot.helpers import ORDER_CONFIRMED, load_json_cache

    account = assistant.account
    balance = assistant.balance
    currency, balance_value = "₽", balance.total_rub
    if balance.total_eur:
        currency, balance_value = "€", balance.total_eur
    elif balance.total_usd:
        currency, balance_value = "$", balance.total_usd

    confirmed = dict(ORDER_CONFIRMED)
    if exists("storage/cache/advProfileStat.json"):
        confirmed = load_json_cache("storage/cache/advProfileStat.json", {})

    can_withdraw = {"now": "0", "hour": 0.0, "day": 0.0, "2day": 0.0}
    for order_id, data in list(confirmed.items()):
        if time.time() - data["time"] > 172800:
            continue
        age = time.time() - data["time"]
        if age > 169200:
            can_withdraw["hour"] += data["price"]
        elif age > 86400:
            can_withdraw["day"] += data["price"]
        else:
            can_withdraw["2day"] += data["price"]

    try:
        random_lot_page = bs(
            account.method("get", "https://funpay.com/lots/693/", {}, {}).text, "html.parser"
        )
        lot_link = random_lot_page.find("a", {"class": "tc-item"})["href"]
        page = bs(account.method("get", lot_link, {}, {}).text, "html.parser")
        selectpicker = page.find("select", {"class": "form-control input-lg selectpicker"})
        if currency == "₽":
            can_withdraw["now"] = str(selectpicker.get("data-balance-rub", 0) or 0)
        elif currency == "$":
            can_withdraw["now"] = str(selectpicker.get("data-balance-usd", 0) or 0)
        elif currency == "€":
            can_withdraw["now"] = str(selectpicker.get("data-balance-eur", 0) or 0)
    except Exception:
        if currency == "₽":
            can_withdraw["now"] = str(balance.available_rub)
        elif currency == "$":
            can_withdraw["now"] = str(balance.available_usd)
        elif currency == "€":
            can_withdraw["now"] = str(balance.available_eur)

    return _(
        "an_block_withdraw",
        balance_value,
        currency,
        str(can_withdraw["now"]).split(".")[0],
        currency,
        can_withdraw["hour"],
        currency,
        can_withdraw["day"],
        currency,
        can_withdraw["2day"],
        currency,
    )


class _ReportContext:
    def __init__(self, assistant: Assistant):
        self.assistant = assistant
        self.all_sales: list | None = None
        self.sales_stats: dict | None = None

    def sales(self) -> list:
        if self.all_sales is None:
            self.all_sales = fetch_all_sales(self.assistant.account)
            self.sales_stats = _sales_stats(self.all_sales)
        return self.all_sales


def build_report(assistant: Assistant, user_id: int) -> str:
    sections = enabled_sections(user_id)
    if not sections:
        return _("an_select_one")

    account = assistant.account
    balance = assistant.balance
    ctx = _ReportContext(assistant)
    parts: list[str] = [_("an_report_header", account.username)]

    for section_id in sections:
        if section_id == "balance":
            parts.append(_(
                "an_block_balance",
                account.id,
                account.active_sales,
                balance.total_rub,
                balance.available_rub,
                balance.total_usd,
                balance.available_usd,
                balance.total_eur,
                balance.available_eur,
            ))
        elif section_id == "withdraw":
            parts.append(_withdraw_block(assistant))
        elif section_id == "sales":
            ctx.sales()
            text = _format_currency_blocks(ctx.sales_stats, "sales", "salesPrice")
            parts.append(_("an_block_sales", text))
        elif section_id == "refunds":
            ctx.sales()
            text = _format_currency_blocks(ctx.sales_stats, "refunds", "refundsPrice")
            parts.append(_("an_block_refunds", text))
        elif section_id == "today":
            stats = collect_today_stats(ctx.sales())
            earned_lines = []
            for cur in ("RUB", "USD", "EUR"):
                amount = stats["earned"][cur]
                if amount > 0:
                    earned_lines.append(f"• <code>{helpers.format_order_price(amount, cur)}</code>")
            earned_block = "\n".join(earned_lines) if earned_lines else "• <code>0 ₽</code>"
            parts.append(_(
                "an_block_today",
                stats["date"],
                stats["orders_today"],
                stats["unclosed"],
                earned_block,
            ))
        elif section_id == "lots":
            profile = assistant.tg_profile or assistant.profile
            if profile:
                total = len(profile.get_lots())
                try:
                    active = len(profile.get_sorted_lots(1))
                except Exception:
                    active = total
                parts.append(_("an_block_lots", total, active))
            else:
                parts.append(_("an_block_lots_empty"))

    updated = time.strftime("%H:%M:%S", time.localtime(account.last_update))
    parts.append(f"<i>{_('an_updated', updated)}</i>")
    return "\n\n".join(parts)

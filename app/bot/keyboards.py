"""
Функции генерации клавиатур для суб-панелей управления.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.assistant import Assistant

from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B, Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

from app.bot import analytics, callbacks as cb, menu_config
from app.bot.helpers import NotificationTypes, bool_to_text, add_navigation_buttons

from app.utils import assistant_tools
from app.constants import translate as _

import logging
import random
import os

logger = logging.getLogger("TGBot")

def power_off(instance_id: int, state: int) -> K:
    """
    Генерирует клавиатуру выключения бота (cb.SHUT_DOWN:<state>:<instance_id>).

    :param instance_id: ID запуска бота.
    :param state: текущей этап клавиатуры.

    :return: объект клавиатуры выключения бота.
    """
    kb = K()
    if state == 0:
        kb.row(B(_("gl_yes"), None, f"{cb.SHUT_DOWN}:1:{instance_id}"),
               B(_("gl_no"), None, cb.CANCEL_SHUTTING_DOWN))
    elif state == 1:
        kb.row(B(_("gl_no"), None, cb.CANCEL_SHUTTING_DOWN),
               B(_("gl_yes"), None, f"{cb.SHUT_DOWN}:2:{instance_id}"))
    elif state == 2:
        yes_button_num = random.randint(1, 10)
        yes_button = B(_("gl_yes"), None, f"{cb.SHUT_DOWN}:3:{instance_id}")
        no_button = B(_("gl_no"), None, cb.CANCEL_SHUTTING_DOWN)
        buttons = [*[no_button] * (yes_button_num - 1), yes_button, *[no_button] * (10 - yes_button_num)]
        kb.add(*buttons, row_width=2)
    elif state == 3:
        yes_button_num = random.randint(1, 30)
        yes_button = B(_("gl_yes"), None, f"{cb.SHUT_DOWN}:4:{instance_id}")
        no_button = B(_("gl_no"), None, cb.CANCEL_SHUTTING_DOWN)
        buttons = [*[no_button] * (yes_button_num - 1), yes_button, *[no_button] * (30 - yes_button_num)]
        kb.add(*buttons, row_width=5)
    elif state == 4:
        yes_button_num = random.randint(1, 40)
        yes_button = B(_("gl_no"), None, f"{cb.SHUT_DOWN}:5:{instance_id}")
        no_button = B(_("gl_yes"), None, cb.CANCEL_SHUTTING_DOWN)
        buttons = [*[yes_button] * (yes_button_num - 1), no_button, *[yes_button] * (40 - yes_button_num)]
        kb.add(*buttons, row_width=7)
    elif state == 5:
        kb.add(B(_("gl_yep"), None, f"{cb.SHUT_DOWN}:6:{instance_id}"))
    return kb


def settings_sections(c: Assistant) -> K:
    kb = K()
    kb.row(
        B(_("mm_global"), callback_data=f"{cb.CATEGORY}:main"),
        B(_("mm_notifications"), callback_data=f"{cb.CATEGORY}:tg"),
    ).row(
        B(_("mm_profile"), callback_data=cb.MENU_PROFILE),
        B(_("mm_old_orders"), callback_data=cb.MENU_OLD_ORDERS),
    ).row(
        B(_("mm_group_topics"), callback_data=f"{cb.CATEGORY}:gt"),
        B(_("mm_analytics"), callback_data=cb.ANALYTICS),
    ).row(
        B(_("mm_deep_settings"), callback_data=cb.DEEP_SETTINGS),
        B(_("mm_support"), callback_data=f"{cb.CATEGORY}:sp"),
    )
    return kb


def analytics_menu(user_id: int) -> K:
    prefs = analytics.get_user_prefs(user_id)

    def toggle_btn(section_id: str) -> B:
        mark = "🟢" if prefs.get(section_id) else "🔴"
        return B(f"{mark} {analytics.section_label(section_id)}", callback_data=f"{cb.ANALYTICS_TOGGLE}:{section_id}")

    kb = K()
    kb.row(toggle_btn("balance"), toggle_btn("sales"))
    kb.row(toggle_btn("withdraw"), toggle_btn("refunds"))
    kb.row(toggle_btn("today"), toggle_btn("lots"))
    kb.add(B(_("an_show"), callback_data=cb.ANALYTICS_RUN))
    kb.add(B(_("gl_back"), callback_data=cb.MAIN))
    return kb


def analytics_report_actions() -> K:
    return K().row(
        B(_("gl_refresh"), callback_data=cb.ANALYTICS_RUN),
        B(_("gl_back"), callback_data=cb.ANALYTICS),
    )


def support_settings(c: Assistant) -> K:
    return K()\
        .add(B(_("support_open_group"), url=_("support_group_url")))\
        .add(B(_("gl_back"), None, cb.MAIN))


def deep_settings_sections(c: Assistant) -> K:
    kb = K()
    kb.row(
        B(_("mm_autoresponse"), callback_data=f"{cb.CATEGORY}:ar"),
        B(_("mm_autodelivery"), callback_data=f"{cb.CATEGORY}:ad"),
    ).row(
        B(_("mm_blacklist"), callback_data=f"{cb.CATEGORY}:bl"),
        B(_("mm_templates"), callback_data=f"{cb.TMPLT_LIST}:0"),
    ).row(
        B(_("mm_greetings"), callback_data=f"{cb.CATEGORY}:gr"),
        B(_("mm_order_confirm"), callback_data=f"{cb.CATEGORY}:oc"),
    ).row(
        B(_("mm_review_reminder"), callback_data=f"{cb.CATEGORY}:rm"),
        B(_("mm_review_reply"), callback_data=f"{cb.CATEGORY}:rr"),
    ).add(
        B(_("mm_new_msg_view"), callback_data=f"{cb.CATEGORY}:mv"),
    ).add(
        B(_("mm_configs"), callback_data="config_loader"),
    ).add(
        B(_("gl_back"), callback_data=cb.MAIN),
    )
    return kb


def main_settings(c: Assistant) -> K:
    """
    Генерирует клавиатуру основных переключателей (cb.CATEGORY:main).

    :param c: объект ассистента.

    :return: объект клавиатуры основных переключателей.
    """
    p = f"{cb.SWITCH}:FunPay"

    def l(s):
        return '🟢' if c.MAIN_CFG["FunPay"].getboolean(s) else '🔴'

    kb = K()\
        .row(B(_("gs_autoraise", l('autoRaise')), None, f"{p}:autoRaise"),
             B(_("gs_autoresponse", l('autoResponse')), None, f"{p}:autoResponse"))\
        .row(B(_("gs_autodelivery", l('autoDelivery')), None, f"{p}:autoDelivery"),
             B(_("gs_nultidelivery", l('multiDelivery')), None, f"{p}:multiDelivery"))\
        .row(B(_("gs_autorestore", l('autoRestore')), None, f"{p}:autoRestore"),
             B(_("gs_autodisable", l('autoDisable')), None, f"{p}:autoDisable"))\
        .add(B(_("gl_back"), None, cb.MAIN))
    return kb


def new_message_view_settings(c: Assistant) -> K:
    """
    Генерирует клавиатуру настроек вида уведомлений о новых сообщениях (cb.CATEGORY:newMessageView).

    :param c: объект ассистента.

    :return: объект клавиатуры настроек вида уведомлений о новых сообщениях.
    """
    p = f"{cb.SWITCH}:NewMessageView"

    def l(s):
        return '🟢' if c.MAIN_CFG["NewMessageView"].getboolean(s) else '🔴'

    kb = K()
    kb.row(
        B(_("mv_incl_my_msg", l("includeMyMessages")), None, f"{p}:includeMyMessages"),
        B(_("mv_incl_fp_msg", l("includeFPMessages")), None, f"{p}:includeFPMessages"),
    )
    kb.add(B(_("mv_incl_bot_msg", l("includeBotMessages")), callback_data=f"{p}:includeBotMessages"))
    kb.row(
        B(_("mv_only_my_msg", l("notifyOnlyMyMessages")), None, f"{p}:notifyOnlyMyMessages"),
        B(_("mv_only_fp_msg", l("notifyOnlyFPMessages")), None, f"{p}:notifyOnlyFPMessages"),
    )
    kb.add(B(_("mv_only_bot_msg", l("notifyOnlyBotMessages")), callback_data=f"{p}:notifyOnlyBotMessages"))
    kb.add(B(_("gl_back_to_deep"), None, cb.DEEP_SETTINGS))
    return kb


def greeting_settings(c: Assistant):
    """
    Генерирует клавиатуру настроек приветственного сообщения (cb.CATEGORY:greetings).

    :param c: объект ассистента.

    :return: объект клавиатуры настроек приветственного сообщения.
    """
    p = f"{cb.SWITCH}:Greetings"

    def l(s):
        return '🟢' if c.MAIN_CFG["Greetings"].getboolean(s) else '🔴'

    kb = K()\
        .row(B(_("gr_greetings", l("sendGreetings")), None, f"{p}:sendGreetings"),
             B(_("gr_cache_init_chats", l("cacheInitChats")), None, f"{p}:cacheInitChats"))\
        .add(B(_("gr_ignore_sys_msgs", l("ignoreSystemMessages")), None, f"{p}:ignoreSystemMessages"))\
        .add(B(_("gr_edit_message"), None, cb.EDIT_GREETINGS_TEXT))\
        .add(B(_("gl_back_to_deep"), None, cb.DEEP_SETTINGS))
    return kb


def review_reminder_settings(c: Assistant):
    """
    Генерирует клавиатуру напоминания об отзыве (cb.CATEGORY:rm).
    """
    kb = K()\
        .add(B(_("rrm_send_reminder", bool_to_text(int(c.MAIN_CFG['ReviewReminder']['sendReminder']))),
               None, f"{cb.SWITCH}:ReviewReminder:sendReminder"))\
        .add(B(_("rrm_edit_message"), None, cb.EDIT_REVIEW_REMINDER_TEXT))\
        .add(B(_("gl_back_to_deep"), None, cb.DEEP_SETTINGS))
    return kb


def order_confirm_reply_settings(c: Assistant):
    """
    Генерирует клавиатуру настроек ответа на подтверждение заказа (cb.CATEGORY:orderConfirm).

    :param c: объект ассистента.

    :return: объект клавиатуры настроек ответа на подтверждение заказа.
    """
    kb = K()\
        .add(B(_("oc_send_reply", bool_to_text(int(c.MAIN_CFG['OrderConfirm']['sendReply']))),
               None, f"{cb.SWITCH}:OrderConfirm:sendReply"))\
        .add(B(_("oc_edit_message"), None, cb.EDIT_ORDER_CONFIRM_REPLY_TEXT))\
        .add(B(_("gl_back_to_deep"), None, cb.DEEP_SETTINGS))
    return kb


def review_reply_settings(c: Assistant):
    """
    Генерирует клавиатуру настроек ответа на отзыв (cb.CATEGORY:reviewReply).

    :param c: объект ассистента.

    :return: объект клавиатуры настроек ответа на отзыв.
    """
    kb = K()
    for i in range(1, 6):
        kb.row(B(f"{'⭐' * i}", None, f"{cb.SEND_REVIEW_REPLY_TEXT}:{i}"),
               B(f"{bool_to_text(int(c.MAIN_CFG['ReviewReply'][f'star{i}Reply']))}",
                 None, f"{cb.SWITCH}:ReviewReply:star{i}Reply"),
               B(f"✏️", None, f"{cb.EDIT_REVIEW_REPLY_TEXT}:{i}"))
    kb.add(B(_("gl_back_to_deep"), None, cb.DEEP_SETTINGS))
    return kb


def group_topics_settings(c: Assistant) -> K:
    p = f"{cb.SWITCH}:Telegram"
    enabled = c.MAIN_CFG["Telegram"].getboolean("groupTopicsEnabled")
    status = "🟢" if enabled else "🔴"
    gid = c.MAIN_CFG["Telegram"].get("groupChatId", "").strip() or "—"
    kb = K()\
        .add(B(_("gt_enabled", status), None, f"{p}:groupTopicsEnabled"))\
        .add(B(_("gt_group_id", gid), None, cb.EMPTY))\
        .add(B(_("gt_set_id"), None, cb.EDIT_GROUP_CHAT_ID))\
        .add(B(_("gl_back"), None, cb.MAIN))
    return kb


def notifications_settings(c: Assistant, chat_id: int) -> K:
    """
    Генерирует клавиатуру общих настроек уведомлений (cb.CATEGORY:telegram).

    :param c: объект ассистента.
    :param chat_id: ID лички администратора (единое хранилище настроек).

    :return: объект клавиатуры настроек уведомлений.
    """
    store_id = c.telegram.primary_notification_chat_id() or chat_id
    p = f"{cb.SWITCH_TG_NOTIFICATIONS}:{store_id}"
    n = NotificationTypes

    def l(nt):
        return '🔔' if c.telegram.is_notification_enabled(store_id, nt) else '🔕'

    kb = K()
    if c.telegram.group_topics.is_active():
        to_group = c.MAIN_CFG["Telegram"].getboolean("groupNotificationsEnabled")
        group_mark = "🟢" if to_group else "🔴"
        kb.add(B(_("ns_all_to_group", group_mark), callback_data=f"{cb.TOGGLE_GROUP_NOTIFICATIONS}:{store_id}"))
    kb.row(B(_("ns_new_msg", l(n.new_message)), None, f"{p}:{n.new_message}"),
             B(_("ns_cmd", l(n.command)), None, f"{p}:{n.command}"))\
        .row(B(_("ns_new_order", l(n.new_order)), None, f"{p}:{n.new_order}"),
             B(_("ns_order_confirmed", l(n.order_confirmed)), None, f"{p}:{n.order_confirmed}"))\
        .row(B(_("ns_lot_activate", l(n.lots_restore)), None, f"{p}:{n.lots_restore}"),
             B(_("ns_lot_deactivate", l(n.lots_deactivate)), None, f"{p}:{n.lots_deactivate}"))\
        .row(B(_("ns_delivery", l(n.delivery)), None, f"{p}:{n.delivery}"),
             B(_("ns_raise", l(n.lots_raise)), None, f"{p}:{n.lots_raise}"))\
        .row(B(_("ns_new_review", l(n.review)), None, f"{p}:{n.review}"),
             B(_("ns_bot_start", l(n.bot_start)), None, f"{p}:{n.bot_start}"))\
        .add(B(_("ns_daily_stats", l(n.daily_stats)), None, f"{p}:{n.daily_stats}"))\
        .add(B(_("gl_back"), None, cb.MAIN))
    return kb


def announcements_settings(c: Assistant, chat_id: int):
    """
    Генерирует клавиатуру настроек уведомлений объявлений.

    :param c: объект ассистента.
    :param chat_id: ID чата, в котором вызвана клавиатура.

    :return: объект клавиатуры настроек уведомлений объявлений.
    """
    p = f"{cb.SWITCH_TG_NOTIFICATIONS}:{chat_id}"
    n = NotificationTypes

    def l(nt):
        return '🔔' if c.telegram.is_notification_enabled(chat_id, nt) else '🔕'

    kb = K()\
        .add(B(_("an_an", l(n.announcement)), None, f"{p}:{n.announcement}"))\
        .add(B(_("an_ad", l(n.ad)), None, f"{p}:{n.ad}"))
    return kb


def blacklist_settings(c: Assistant) -> K:
    """
    Генерирует клавиатуру настроек черного списка (cb.CATEGORY:blockList).

    :param c: объект ассистента.

    :return: объект клавиатуры настроек черного списка.
    """
    p = f"{cb.SWITCH}:BlockList"

    def l(s):
        return '🟢' if c.MAIN_CFG["BlockList"].getboolean(s) else '🔴'

    kb = K()\
        .row(B(_("bl_autodelivery", l("blockDelivery")), None, f"{p}:blockDelivery"),
             B(_("bl_autoresponse", l("blockResponse")), None, f"{p}:blockResponse"))\
        .row(B(_("bl_new_msg_notifications", l("blockNewMessageNotification")), None, f"{p}:blockNewMessageNotification"),
             B(_("bl_new_order_notifications", l("blockNewOrderNotification")), None, f"{p}:blockNewOrderNotification"))\
        .add(B(_("bl_command_notifications", l("blockCommandNotification")), None, f"{p}:blockCommandNotification"))\
        .add(B(_("gl_back_to_deep"), None, cb.DEEP_SETTINGS))
    return kb


def commands_list(c: Assistant, offset: int) -> K:
    """
    Генерирует клавиатуру со списком команд (cb.CMD_LIST:<offset>).

    :param c: объект ассистента.
    :param offset: смещение списка команд.

    :return: объект клавиатуры со списком команд.
    """
    kb = K()
    commands = c.RAW_AR_CFG.sections()[offset: offset + menu_config.AR_BTNS_AMOUNT]
    if not commands and offset != 0:
        offset = 0
        commands = c.RAW_AR_CFG.sections()[offset: offset + menu_config.AR_BTNS_AMOUNT]

    for index, cmd in enumerate(commands):
        #  cb.EDIT_CMD:номер команды:смещение (для кнопки назад)
        kb.add(B(cmd, None, f"{cb.EDIT_CMD}:{offset + index}:{offset}"))

    kb = add_navigation_buttons(kb, offset, menu_config.AR_BTNS_AMOUNT, len(commands), len(c.RAW_AR_CFG.sections()), cb.CMD_LIST)

    kb.add(B(_("ar_to_ar"), None, f"{cb.CATEGORY}:ar"))\
        .add(B(_("gl_back_to_deep"), None, cb.DEEP_SETTINGS))
    return kb


def edit_command(c: Assistant, command_index: int, offset: int) -> K:
    """
    Генерирует клавиатуру изменения параметров команды (cb.EDIT_CMD:<command_num>:<offset>).

    :param c: объект ассистента.
    :param command_index: номер команды.
    :param offset: смещение списка команд.

    :return объект клавиатуры изменения параметров команды.
    """
    command = c.RAW_AR_CFG.sections()[command_index]
    command_obj = c.RAW_AR_CFG[command]
    kb = K()\
        .add(B(_("ar_edit_response"), None, f"{cb.EDIT_CMD_RESPONSE_TEXT}:{command_index}:{offset}"))\
        .add(B(_("ar_edit_notification"), None, f"{cb.EDIT_CMD_NOTIFICATION_TEXT}:{command_index}:{offset}"))\
        .add(B(_("ar_notification", bool_to_text(command_obj.get('telegramNotification'), '🔔', '🔕')),
               None, f"{cb.SWITCH_CMD_NOTIFICATION}:{command_index}:{offset}"))\
        .add(B(_("gl_delete"), None, f"{cb.DEL_CMD}:{command_index}:{offset}"))\
        .row(B(_("gl_back"), None, f"{cb.CMD_LIST}:{offset}"),
             B(_("gl_refresh"), None, f"{cb.EDIT_CMD}:{command_index}:{offset}"))
    return kb


def products_files_list(offset: int) -> K:
    """
    Генерирует клавиатуру со списком товарных файлов (cb.PRODUCTS_FILES_LIST:<offset>).

    :param offset: смещение списка товарных файлов.

    :return: объект клавиатуры со списком товарных файлов.
    """
    keyboard = K()
    files = os.listdir("storage/products")[offset:offset + menu_config.PF_BTNS_AMOUNT]
    if not files and offset != 0:
        offset = 0
        files = os.listdir("storage/products")[offset:offset + 5]

    for index, name in enumerate(files):
        amount = assistant_tools.count_products(f"storage/products/{name}")
        keyboard.add(B(f"{amount} {_('gl_pcs')}, {name}", None, f"{cb.EDIT_PRODUCTS_FILE}:{offset + index}:{offset}"))

    keyboard = add_navigation_buttons(keyboard, offset, menu_config.PF_BTNS_AMOUNT, len(files),
                                      len(os.listdir("storage/products")), cb.PRODUCTS_FILES_LIST)

    keyboard.add(B(_("ad_to_ad"), None, f"{cb.CATEGORY}:ad"))\
        .add(B(_("gl_back_to_deep"), None, cb.DEEP_SETTINGS))
    return keyboard


def products_file_edit(file_number: int, offset: int, confirmation: bool = False)\
        -> K:
    """
    Генерирует клавиатуру изменения товарного файла (cb.EDIT_PRODUCTS_FILE:<file_index>:<offset>).

    :param file_number: номер файла.
    :param offset: смещение списка товарных файлов.
    :param confirmation: включить ли в клавиатуру подтверждение удаления файла.

    :return: объект клавиатуры изменения товарного файла.
    """
    keyboard = K()\
        .add(B(_("gf_add_goods"), None, f"{cb.ADD_PRODUCTS_TO_FILE}:{file_number}:{file_number}:{offset}:0"))\
        .add(B(_("gf_download"), None, f"download_products_file:{file_number}:{offset}"))
    if not confirmation:
        keyboard.add(B(_("gl_delete"), None, f"del_products_file:{file_number}:{offset}"))
    else:
        keyboard.row(B(_("gl_yes"), None, f"confirm_del_products_file:{file_number}:{offset}"),
                     B(_("gl_no"), None, f"{cb.EDIT_PRODUCTS_FILE}:{file_number}:{offset}"))
    keyboard.row(B(_("gl_back"), None, f"{cb.PRODUCTS_FILES_LIST}:{offset}"),
                 B(_("gl_refresh"), None, f"{cb.EDIT_PRODUCTS_FILE}:{file_number}:{offset}"))
    return keyboard


def lots_list(assistant: Assistant, offset: int) -> K:
    """
    Создает клавиатуру со списком лотов с автовыдачей. (lots:<offset>).

    :param assistant: объект ассистента.
    :param offset: смещение списка лотов.

    :return: объект клавиатуры со списком лотов с автовыдачей.
    """
    keyboard = K()
    lots = assistant.AD_CFG.sections()[offset: offset + menu_config.AD_BTNS_AMOUNT]
    if not lots and offset != 0:
        offset = 0
        lots = assistant.AD_CFG.sections()[offset: offset + menu_config.AD_BTNS_AMOUNT]

    for index, lot in enumerate(lots):
        keyboard.add(B(lot, None, f"{cb.EDIT_AD_LOT}:{offset + index}:{offset}"))

    keyboard = add_navigation_buttons(keyboard, offset, menu_config.AD_BTNS_AMOUNT, len(lots),
                                      len(assistant.AD_CFG.sections()), cb.AD_LOTS_LIST)

    keyboard.add(B(_("ad_to_ad"), None, f"{cb.CATEGORY}:ad"))\
        .add(B(_("gl_back_to_deep"), None, cb.DEEP_SETTINGS))
    return keyboard


def funpay_lots_list(c: Assistant, offset: int):
    """
    Генерирует клавиатуру со списком лотов текущего профиля (funpay_lots:<offset>).

    :param c: объект ассистента.
    :param offset: смещение списка слотов.

    :return: объект клавиатуры со списком лотов текущего профиля.
    """
    keyboard = K()
    lots = c.tg_profile.get_common_lots()
    lots = lots[offset: offset + menu_config.FP_LOTS_BTNS_AMOUNT]
    if not lots and offset != 0:
        offset = 0
        lots = c.tg_profile.get_common_lots()[offset: offset + menu_config.FP_LOTS_BTNS_AMOUNT]

    for index, lot in enumerate(lots):
        keyboard.add(B(lot.description, None, f"{cb.ADD_AD_TO_LOT}:{offset + index}:{offset}"))

    keyboard = add_navigation_buttons(keyboard, offset, menu_config.FP_LOTS_BTNS_AMOUNT, len(lots),
                                      len(c.tg_profile.get_common_lots()), cb.FP_LOTS_LIST)

    keyboard.row(B(_("fl_manual"), None, f"{cb.ADD_AD_TO_LOT_MANUALLY}:{offset}"),
                 B(_("gl_refresh"), None, f"update_funpay_lots:{offset}"))\
        .add(B(_("ad_to_ad"), None, f"{cb.CATEGORY}:ad"))\
        .add(B(_("gl_back_to_deep"), None, cb.DEEP_SETTINGS))
    return keyboard


def edit_lot(c: Assistant, lot_number: int, offset: int) -> K:
    """
    Генерирует клавиатуру изменения лота (cb.EDIT_AD_LOT:<lot_num>:<offset>).

    :param c: экземпляр ассистента.
    :param lot_number: номер лота.
    :param offset: смещение списка слотов.

    :return: объект клавиатуры изменения лота.
    """
    lot = c.AD_CFG.sections()[lot_number]
    lot_obj = c.AD_CFG[lot]
    file_name = lot_obj.get("productsFileName")
    kb = K()\
        .add(B(_("ea_edit_delivery_text"),  None, f"{cb.EDIT_LOT_DELIVERY_TEXT}:{lot_number}:{offset}"))
    if not file_name:
        kb.add(B(_("ea_link_goods_file"), None, f"{cb.BIND_PRODUCTS_FILE}:{lot_number}:{offset}"))
    else:
        if file_name not in os.listdir("storage/products"):
            with open(f"storage/products/{file_name}", "w", encoding="utf-8"):
                pass
        file_number = os.listdir("storage/products").index(file_name)

        kb.row(B(_("ea_link_goods_file"), None, f"{cb.BIND_PRODUCTS_FILE}:{lot_number}:{offset}"),
               B(_("gf_add_goods"), None, f"{cb.ADD_PRODUCTS_TO_FILE}:{file_number}:{lot_number}:{offset}:1"))

    p = {
        "ad": (c.MAIN_CFG["FunPay"].getboolean("autoDelivery"), "disable"),
        "md": (c.MAIN_CFG["FunPay"].getboolean("multiDelivery"), "disableMultiDelivery"),
        "ares": (c.MAIN_CFG["FunPay"].getboolean("autoRestore"), "disableAutoRestore"),
        "adis": (c.MAIN_CFG["FunPay"].getboolean("autoDisable"), "disableAutoDisable"),
    }
    info, sl, dis = f"{lot_number}:{offset}", "switch_lot", cb.PARAM_DISABLED

    def l(s):
        return '⚪' if not p[s][0] else '🔴' if lot_obj.getboolean(p[s][1]) else '🟢'

    kb.row(B(_("ea_delivery", l("ad")), None, f"{f'{sl}:disable:{info}' if p['ad'][0] else dis}"),
           B(_("ea_multidelivery", l("md")), None, f"{f'{sl}:disableMultiDelivery:{info}' if p['md'][0] else dis}"))\
        .row(B(_("ea_restore", l("ares")), None, f"{f'{sl}:disableAutoRestore:{info}' if p['ares'][0] else dis}"),
             B(_("ea_deactivate", l("adis")), None, f"{f'{sl}:disableAutoDisable:{info}' if p['adis'][0] else dis}"))\
        .row(B(_("ea_test"), None, f"test_auto_delivery:{info}"),
             B(_("gl_delete"), None, f"{cb.DEL_AD_LOT}:{info}"))\
        .row(B(_("gl_back"), None, f"{cb.AD_LOTS_LIST}:{offset}"),
             B(_("gl_refresh"), None, f"{cb.EDIT_AD_LOT}:{info}"))
    return kb


# Прочее
def new_order(order_id: str, username: str, node_id: int,
              confirmation: bool = False, no_refund: bool = False) -> K:
    """
    Генерирует клавиатуру для сообщения о новом заказе.

    :param order_id: ID заказа (без #).
    :param username: никнейм покупателя.
    :param node_id: ID чата с покупателем.
    :param confirmation: заменить ли кнопку "Вернуть деньги" на подтверждение "Да" / "Нет"?
    :param no_refund: убрать ли кнопки, связанные с возвратом денег?

    :return: объект клавиатуры для сообщения о новом заказе.
    """
    kb = K()
    if not no_refund:
        if confirmation:
            kb.row(B(_("gl_yes"), None, f"{cb.REFUND_CONFIRMED}:{order_id}:{node_id}:{username}"),
                   B(_("gl_no"), None, f"{cb.REFUND_CANCELLED}:{order_id}:{node_id}:{username}"))
        else:
            kb.add(B(_("ord_refund"), None, f"{cb.REQUEST_REFUND}:{order_id}:{node_id}:{username}"))

    kb.add(B(_("ord_open"), url=f"https://funpay.com/orders/{order_id}/"))\
        .row(B(_("ord_answer"), None, f"{cb.SEND_FP_MESSAGE}:{node_id}:{username}"),
             B(_("ord_templates"), None, f"{cb.TMPLT_LIST_ANS_MODE}:0:{node_id}:{username}:2:{order_id}:{1 if no_refund else 0}"))
    return kb


def reply(node_id: int, username: str, again: bool = False, extend: bool = False) -> K:
    """
    Генерирует клавиатуру для отправки сообщения в чат FunPay.

    :param node_id: ID переписки, в которую нужно отправить сообщение.
    :param username: никнейм пользователя, с которым ведется переписка.
    :param again: заменить текст "Отправить" на "Отправить еще"?
    :param extend: добавить ли кнопку "Расширить"?

    :return: объект клавиатуры для отправки сообщения в чат FunPay.
    """
    bts = [B(_("msg_reply2") if again else _("msg_reply"), None, f"{cb.SEND_FP_MESSAGE}:{node_id}:{username}"),
           B(_("msg_templates"), None, f"{cb.TMPLT_LIST_ANS_MODE}:0:{node_id}:{username}:{int(again)}:{int(extend)}")]
    if extend:
        bts.append(B(_("msg_more"), None, f"{cb.EXTEND_CHAT}:{node_id}:{username}"))
    bts.append(B(f"🌐 {username}", url=f"https://funpay.com/chat/?node={node_id}"))
    kb = K()\
        .row(*bts)
    return kb


def templates_list(c: Assistant, offset: int) -> K:
    """
    Генерирует клавиатуру со списком шаблонов ответов. (cb.TMPLT_LIST:<offset>).

    :param c: экземпляр ассистента.
    :param offset: смещение списка шаблонов.

    :return: объект клавиатуры со списком шаблонов ответов.
    """
    kb = K()
    templates = c.telegram.answer_templates[offset: offset + menu_config.TMPLT_BTNS_AMOUNT]
    if not templates and offset != 0:
        offset = 0
        templates = c.telegram.answer_templates[offset: offset + menu_config.TMPLT_BTNS_AMOUNT]

    for index, tmplt in enumerate(templates):
        kb.add(B(tmplt, None, f"{cb.EDIT_TMPLT}:{offset + index}:{offset}"))

    kb = add_navigation_buttons(kb, offset, menu_config.TMPLT_BTNS_AMOUNT, len(templates),
                                len(c.telegram.answer_templates), cb.TMPLT_LIST)
    kb.add(B(_("tmplt_add"), None, f"{cb.ADD_TMPLT}:{offset}"))\
        .add(B(_("gl_back_to_deep"), None, cb.DEEP_SETTINGS))
    return kb


def edit_template(c: Assistant, template_index: int, offset: int) -> K:
    """
    Генерирует клавиатуру изменения шаблона ответа (cb.EDIT_TMPLT:<template_index>:<offset>).

    :param c: экземпляр ассистента.
    :param template_index: числовой индекс шаблона ответа.
    :param offset: смещение списка шаблонов ответа.

    :return: объект клавиатуры изменения шаблона ответа.
    """
    kb = K() \
        .add(B(_("gl_delete"), None, f"{cb.DEL_TMPLT}:{template_index}:{offset}"))\
        .add(B(_("gl_back"), None, f"{cb.TMPLT_LIST}:{offset}"))
    return kb


def templates_list_ans_mode(c: Assistant, offset: int, node_id: int, username: str, prev_page: int,
                            extra: list | None = None):
    """
    Генерирует клавиатуру со списком шаблонов ответов.
    (cb.TMPLT_LIST_ANS_MODE:{offset}:{node_id}:{username}:{prev_page}:{extra}).


    :param c: объект ассистента.
    :param offset: смещение списка шаблонов ответа.
    :param node_id: ID чата, в который нужно отправить шаблон.
    :param username: никнейм пользователя, с которым ведется переписка.
    :param prev_page: предыдущая страница.
    :param extra: доп данные для пред. страницы.

    :return: объект клавиатуры со списком шаблонов ответов.
    """

    kb = K()
    templates = c.telegram.answer_templates[offset: offset + menu_config.TMPLT_BTNS_AMOUNT]
    extra_str = ":" + ":".join(str(i) for i in extra) if extra else ""

    if not templates and offset != 0:
        offset = 0
        templates = c.telegram.answer_templates[offset: offset + menu_config.TMPLT_BTNS_AMOUNT]

    for index, tmplt in enumerate(templates):
        kb.add(B(tmplt.replace("$username", username),
                 None, f"{cb.SEND_TMPLT}:{offset + index}:{node_id}:{username}:{prev_page}{extra_str}"))

    extra_list = [node_id, username, prev_page]
    extra_list.extend(extra)
    kb = add_navigation_buttons(kb, offset, menu_config.TMPLT_BTNS_AMOUNT, len(templates),
                                len(c.telegram.answer_templates), cb.TMPLT_LIST_ANS_MODE,
                                extra_list)

    if prev_page == 0:
        kb.add(B(_("gl_back"), None, f"{cb.BACK_TO_REPLY_KB}:{node_id}:{username}:0{extra_str}"))
    elif prev_page == 1:
        kb.add(B(_("gl_back"), None, f"{cb.BACK_TO_REPLY_KB}:{node_id}:{username}:1{extra_str}"))
    elif prev_page == 2:
        kb.add(B(_("gl_back"), None, f"{cb.BACK_TO_ORDER_KB}:{node_id}:{username}{extra_str}"))
    return kb


def buyer_topic_templates(c: Assistant, fp_chat_id: int, username: str, offset: int = 0) -> K:
    """
    Inline-клавиатура шаблонов в топике покупателя (только отправка, без редактирования).
    """
    kb = K()
    templates = c.telegram.answer_templates
    if not templates:
        kb.add(B(_("gt_no_templates"), None, cb.EMPTY))
        return kb

    page = templates[offset: offset + menu_config.TMPLT_BTNS_AMOUNT]
    if not page and offset != 0:
        offset = 0
        page = templates[offset: offset + menu_config.TMPLT_BTNS_AMOUNT]

    for index, tmplt in enumerate(page):
        preview = tmplt.replace("$username", username).replace("\n", " ")
        if len(preview) > 58:
            preview = preview[:55] + "..."
        kb.add(B(preview, None, f"{cb.GT_SEND_TMPLT}:{fp_chat_id}:{offset + index}:{offset}"))

    kb = add_navigation_buttons(
        kb, offset, menu_config.TMPLT_BTNS_AMOUNT, len(page), len(templates),
        cb.GT_TMPLT_LIST, [fp_chat_id],
    )
    return kb


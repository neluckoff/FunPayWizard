from telebot.types import InlineKeyboardMarkup as K, InlineKeyboardButton as B, ReplyKeyboardMarkup, KeyboardButton
from app.bot import callbacks as cb
from app.constants import translate as _



OLD_KEYBOARD = ReplyKeyboardMarkup(resize_keyboard=True)\
    .row(KeyboardButton(_("kb_logs")), KeyboardButton(_("kb_menu")), KeyboardButton(_("kb_sys")))\
    .row(KeyboardButton(_("kb_restart")), KeyboardButton(_("kb_hide")), KeyboardButton(_("kb_poweroff")))

def CLEAR_STATE_BTN() -> K:
    return K().add(B(_("gl_cancel"), callback_data=cb.CLEAR_STATE))


def REFRESH_BTN() -> K:
    return K().add(B(_("gl_refresh"), callback_data=cb.UPDATE_PROFILE))


def AR_SETTINGS() -> K:
    return K()\
        .add(B(_("ar_edit_commands"), callback_data=f"{cb.CMD_LIST}:0")) \
        .add(B(_("ar_add_command"), callback_data=cb.ADD_CMD)) \
        .add(B(_("gl_back_to_deep"), callback_data=cb.DEEP_SETTINGS))


def AD_SETTINGS() -> K:
    return K()\
        .add(B(_("ad_edit_autodelivery"), callback_data=f"{cb.AD_LOTS_LIST}:0")) \
        .add(B(_("ad_add_autodelivery"), callback_data=f"{cb.FP_LOTS_LIST}:0"))\
        .add(B(_("ad_edit_goods_file"), callback_data=f"{cb.PRODUCTS_FILES_LIST}:0"))\
        .row(B(_("ad_upload_goods_file"), callback_data=cb.UPLOAD_PRODUCTS_FILE),
             B(_("ad_create_goods_file"), callback_data=cb.CREATE_PRODUCTS_FILE))\
        .add(B(_("gl_back_to_deep"), callback_data=cb.DEEP_SETTINGS))


def CONFIGS_UPLOADER() -> K:
    return K()\
        .row(B(_("cfg_download_main"), callback_data=f"{cb.DOWNLOAD_CFG}:main"),
             B(_("cfg_upload_main"), callback_data="upload_main_config")) \
        .row(B(_("cfg_download_ar"), callback_data=f"{cb.DOWNLOAD_CFG}:autoResponse"),
             B(_("cfg_upload_ar"), callback_data="upload_auto_response_config")) \
        .row(B(_("cfg_download_ad"), callback_data=f"{cb.DOWNLOAD_CFG}:autoDelivery"),
             B(_("cfg_upload_ad"), callback_data="upload_auto_delivery_config")) \
        .add(B(_("gl_back_to_deep"), callback_data=cb.DEEP_SETTINGS))

"""
В данном модуле написан Telegram бот.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.assistant import Assistant
import re
import os
import time
import random
import string
import psutil
import telebot
import logging
import json
from threading import Thread
from os.path import exists
from telebot.types import (
    InlineKeyboardMarkup as K,
    InlineKeyboardButton as B,
    Message,
    CallbackQuery,
    BotCommand,
    ReplyKeyboardRemove,
    InputMediaPhoto,
)
from app.bot import analytics, helpers, keyboards_presets as presets, keyboards as kb, callbacks as cb
from app.bot import static_assets
from app.bot.onboarding import SetupWizard
from app.bot.group_topics import GroupTopicsManager
from app.utils import assistant_tools
from app.utils.env import get_telegram_token
from app.constants import translate as _
from app.setup import is_setup_required

logger = logging.getLogger("TGBot")
telebot.apihelper.ENABLE_MIDDLEWARE = True


class TGBot:
    def __init__(self, assistant: Assistant):
        self.assistant = assistant
        token = get_telegram_token() or self.assistant.MAIN_CFG["Telegram"]["token"].strip()
        if not token:
            raise ValueError(
                "Не задан токен Telegram-бота. Укажите TELEGRAM_BOT_TOKEN в файле .env"
            )
        self.bot = telebot.TeleBot(token, parse_mode="HTML",
                                   allow_sending_without_reply=True, num_threads=5)
        self.setup_wizard = SetupWizard(self)

        tg_proxy = self.assistant.MAIN_CFG["Telegram"].get("proxy", "").strip()
        if tg_proxy:
            telebot.apihelper.proxy = {"https": tg_proxy}

        self.file_handlers = {}  # хэндлеры, привязанные к получению файла.
        self.attempts = {}  # {user_id: attempts} - попытки авторизации в Telegram ПУ.
        self.init_messages = []  # [(chat_id, message_id)] - список сообщений о запуске TG бота.

        # {
        #     chat_id: {
        #         user_id: {
        #             "state": "state",
        #             "data": { ... },
        #             "mid": int
        #         }
        #     }
        # }
        self.user_states = {}

        # {
        #    chat_id: {
        #        helpers.NotificationTypes.new_message: bool,
        #        helpers.NotificationTypes.new_order: bool,
        #        ...
        #    },
        # }
        #
        self.notification_settings = helpers.load_notification_settings()  # настройки уведомлений.
        self.answer_templates = helpers.load_answer_templates()  # заготовки ответов.
        self.authorized_users = helpers.load_authorized_users()  # авторизированные пользователи.
        self._migrate_notification_settings()
        self.group_topics = GroupTopicsManager(self)

        self.commands = {
            "start": "первичная настройка / главное меню",
            "menu": _("cmd_menu"),
            "profile": _("cmd_profile"),
            "test_delivery": _("cmd_test_delivery"),
            "upload_img": _("cmd_upload_img"),
            "ban": _("cmd_ban"),
            "unban": _("cmd_unban"),
            "black_list": _("cmd_black_list"),
            "logs": _("cmd_logs"),
            "del_logs": _("cmd_del_logs"),
            "about": _("cmd_about"),
            "sys": _("cmd_sys"),
            "old_orders": _("cmd_old_orders"),
            "keyboard": _("cmd_keyboard"),
            "golden_key": _("cmd_golden_key"),
            "restart": _("cmd_restart"),
            "power_off": _("cmd_power_off")
        }
        self.__default_notification_settings = {
            helpers.NotificationTypes.ad: 1,
            helpers.NotificationTypes.announcement: 1
        }

    # User states
    def get_state(self, chat_id: int, user_id: int) -> dict | None:
        """
        Получает текущее состояние пользователя.

        :param chat_id: id чата.
        :param user_id: id пользователя.

        :return: данные состояния пользователя.
        """
        try:
            return self.user_states[chat_id][user_id]
        except KeyError:
            return None

    def set_state(self, chat_id: int, message_id: int, user_id: int, state: str, data: dict | None = None):
        """
        Устанавливает состояние для пользователя.

        :param chat_id: id чата.
        :param message_id: id сообщения, после которого устанавливается данное состояние.
        :param user_id: id пользователя.
        :param state: состояние.
        :param data: доп. данные.
        """
        if chat_id not in self.user_states:
            self.user_states[chat_id] = {}
        self.user_states[chat_id][user_id] = {"state": state, "mid": message_id, "data": data or {}}

    def clear_state(self, chat_id: int, user_id: int, del_msg: bool = False) -> int | None:
        """
        Очищает состояние пользователя.

        :param chat_id: id чата.
        :param user_id: id пользователя.
        :param del_msg: удалять ли сообщение, после которого было обозначено текущее состояние.

        :return: ID сообщения-инициатора или None, если состояние и так было пустое.
        """
        try:
            state = self.user_states[chat_id][user_id]
        except KeyError:
            return None

        msg_id = state.get("mid")
        del self.user_states[chat_id][user_id]
        if del_msg:
            try:
                self.bot.delete_message(chat_id, msg_id)
            except:
                pass
        return msg_id

    def check_state(self, chat_id: int, user_id: int, state: str) -> bool:
        """
        Проверяет, является ли состояние указанным.

        :param chat_id: id чата.
        :param user_id: id пользователя.
        :param state: состояние.

        :return: True / False
        """
        try:
            return self.user_states[chat_id][user_id]["state"] == state
        except KeyError:
            return False

    # Notification settings
    @staticmethod
    def _notification_flag(value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() not in ("0", "false", "")
        return bool(value)

    def primary_notification_chat_id(self) -> int | None:
        """Единый чат настроек уведомлений (личка администратора)."""
        if self.authorized_users:
            return self.authorized_users[0]
        for chat_id in self.notification_settings:
            if not self._is_group_chat_key(chat_id):
                try:
                    return int(chat_id)
                except ValueError:
                    continue
        return None

    def is_notification_enabled(self, chat_id: int | str, notification_type: str) -> bool:
        """
        Включен ли тип уведомлений (общие настройки, не зависят от chat_id группы).

        :param chat_id: игнорируется для групп; для совместимости API.
        :param notification_type: тип уведомлений.
        """
        if self._is_group_chat_key(str(chat_id)):
            chat_id = self.primary_notification_chat_id()
            if chat_id is None:
                return False
        try:
            return self._notification_flag(self.notification_settings[str(chat_id)][notification_type])
        except KeyError:
            return False

    def _migrate_notification_settings(self) -> None:
        """Переносит настройки группы в личку и удаляет отдельные ключи группы."""
        primary = self.primary_notification_chat_id()
        changed = False
        merged: dict = {}
        for key in list(self.notification_settings):
            if not self._is_group_chat_key(key):
                continue
            for nt, val in self.notification_settings[key].items():
                merged.setdefault(nt, val)
            del self.notification_settings[key]
            changed = True
        if primary is not None and merged:
            store = self.notification_settings.setdefault(str(primary), {})
            for nt, val in merged.items():
                if nt not in store:
                    store[nt] = val
                    changed = True
        if changed:
            helpers.save_notification_settings(self.notification_settings)

    @staticmethod
    def _is_group_chat_key(chat_id: str) -> bool:
        try:
            return int(chat_id) < 0
        except ValueError:
            return False

    def group_notifications_enabled(self) -> bool:
        if not self.group_topics.is_active():
            return False
        return self.assistant.MAIN_CFG["Telegram"].getboolean("groupNotificationsEnabled")

    def is_notification_enabled_globally(self, notification_type: str) -> bool:
        """Включён ли тип в общих настройках (личка = группа)."""
        primary = self.primary_notification_chat_id()
        if primary is None:
            return False
        return self.is_notification_enabled(primary, notification_type)

    def toggle_notification(self, chat_id: int, notification_type: str) -> bool:
        """
        Переключает тип уведомлений в общих настройках (личка и группа).

        :param chat_id: ID чата из callback (для группы подставляется личка админа).
        :param notification_type: тип уведомлений.

        :return: новое состояние переключателя.
        """
        self._migrate_notification_settings()
        primary = self.primary_notification_chat_id()
        if primary is None:
            try:
                primary = int(chat_id)
            except (TypeError, ValueError):
                return False
        if self._is_group_chat_key(str(chat_id)):
            chat_id = primary

        store_key = str(primary)
        if store_key not in self.notification_settings:
            self.notification_settings[store_key] = {}

        enabled = not self.is_notification_enabled(primary, notification_type)
        for uid in self.authorized_users:
            key = str(uid)
            if key not in self.notification_settings:
                self.notification_settings[key] = {}
            self.notification_settings[key][notification_type] = enabled
        self.notification_settings[store_key][notification_type] = enabled
        self._migrate_notification_settings()
        helpers.save_notification_settings(self.notification_settings)
        return enabled

    # handler binders
    def is_file_handler(self, m: Message):
        return self.get_state(m.chat.id, m.from_user.id) and m.content_type in ["photo", "document"]

    def file_handler(self, state, handler):
        self.file_handlers[state] = handler

    def run_file_handlers(self, m: Message):
        if (state := self.get_state(m.chat.id, m.from_user.id)) is None \
                or state["state"] not in self.file_handlers:
            return
        try:
            self.file_handlers[state["state"]](m)
        except:
            logger.error(_("log_tg_handler_error"))
            logger.debug("TRACEBACK", exc_info=True)

    def msg_handler(self, handler, **kwargs):
        """
        Регистрирует хэндлер, срабатывающий при новом сообщении.

        :param handler: хэндлер.
        :param kwargs: аргументы для хэндлера.
        """
        bot_instance = self.bot

        @bot_instance.message_handler(**kwargs)
        def run_handler(message: Message):
            try:
                handler(message)
            except:
                logger.error(_("log_tg_handler_error"))
                logger.debug("TRACEBACK", exc_info=True)

    def cbq_handler(self, handler, func, **kwargs):
        """
        Регистрирует хэндлер, срабатывающий при новом callback'е.

        :param handler: хэндлер.
        :param func: функция-фильтр.
        :param kwargs: аргументы для хэндлера.
        """
        bot_instance = self.bot

        @bot_instance.callback_query_handler(func, **kwargs)
        def run_handler(call: CallbackQuery):
            try:
                handler(call)
            except:
                logger.error(_("log_tg_handler_error"))
                logger.debug("TRACEBACK", exc_info=True)

    def mdw_handler(self, handler, **kwargs):
        """
        Регистрирует промежуточный хэндлер.

        :param handler: хэндлер.
        :param kwargs: аргументы для хэндлера.
        """
        bot_instance = self.bot

        @bot_instance.middleware_handler(**kwargs)
        def run_handler(bot, update):
            try:
                handler(bot, update)
            except:
                logger.error(_("log_tg_handler_error"))
                logger.debug("TRACEBACK", exc_info=True)

    # Система свой-чужой 0_0
    def handle_group_topics(self, bot: TGBot, m: Message):
        if getattr(m, "forum_topic_created", None):
            self.group_topics.on_forum_topic_created(m)
        if m.content_type not in ("text", "photo"):
            return
        if self.assistant.setup_mode:
            return
        if not m.from_user or m.from_user.is_bot:
            return
        if m.chat.type in ("supergroup", "group"):
            if self.group_topics.try_link_from_message(m):
                return
        if self._is_group_topic_reply(m):
            self.group_topics.handle_group_reply(m)

    def _is_group_topic_reply(self, m: Message) -> bool:
        if not self.group_topics.is_active():
            return False
        if m.chat.type not in ("supergroup", "group"):
            return False
        if m.from_user.id not in self.authorized_users:
            return False
        if not m.message_thread_id:
            return False
        if self.check_state(m.chat.id, m.from_user.id, cb.SEND_FP_MESSAGE):
            return False
        return self.group_topics.is_buyer_topic(m.message_thread_id)

    def setup_chat_notifications(self, bot: TGBot, m: Message):
        """
        Устанавливает настройки уведомлений по умолчанию в новом чате.
        """
        if m.reply_to_message and m.reply_to_message.forum_topic_created:
            return
        if str(m.chat.id) in self.notification_settings:
            return
        if m.chat.type in ("supergroup", "group") and self.group_topics.is_enabled():
            return
        if m.chat.type != "private" or m.chat.id in self.authorized_users:
            self.notification_settings[str(m.chat.id)] = self.__default_notification_settings
            helpers.save_notification_settings(self.notification_settings)

    @staticmethod
    def _is_command_start(m: Message) -> bool:
        if not m.text:
            return False
        return m.text.strip().split()[0].split("@")[0].lower() == "/start"

    def _setup_active(self, chat_id: int, user_id: int) -> bool:
        if is_setup_required(self.assistant.MAIN_CFG):
            return True
        state = self.get_state(chat_id, user_id)
        return bool(state and state["state"] in SetupWizard.SETUP_STATES)

    def handle_start(self, m: Message):
        """Команда /start: мастер настройки или вход в панель."""
        if m.chat.type != "private":
            return
        logger.info("Получена команда /start от %s (ID: %s).", m.from_user.username, m.from_user.id)
        if self._setup_active(m.chat.id, m.from_user.id):
            self.setup_wizard.start(m)
            return
        if m.from_user.id in self.authorized_users:
            self.send_settings_menu(m)
            return
        self.bot.send_message(m.chat.id, _("access_denied", m.from_user.username))

    def handle_setup(self, m: Message):
        """Сообщения во время первичной настройки."""
        if self._is_command_start(m):
            self.setup_wizard.start(m)
            return
        if m.text and m.text.startswith("/"):
            self.bot.send_message(m.chat.id, _("setup_in_progress"))
            return
        self.setup_wizard.handle_message(m)

    def reg_admin(self, m: Message):
        """
        Проверяет, есть ли пользователь в списке пользователей с доступом к ПУ TG.
        """
        if m.chat.type != "private" or (m.from_user.id in self.attempts and self.attempts.get(m.from_user.id) >= 5):
            return
        if m.text == self.assistant.MAIN_CFG["Telegram"]["secretKey"]:
            self.authorized_users.append(m.from_user.id)
            helpers.save_authorized_users(self.authorized_users)
            if str(m.chat.id) not in self.notification_settings:
                self.notification_settings[str(m.chat.id)] = self.__default_notification_settings
                helpers.save_notification_settings(self.notification_settings)
            text = _("access_granted")
            logger.warning(_("log_access_granted", m.from_user.username, m.from_user.id))
        else:
            self.attempts[m.from_user.id] = self.attempts[m.from_user.id] + 1 if m.from_user.id in self.attempts else 1
            text = _("access_denied", m.from_user.username)
            logger.warning(_("log_access_attempt", m.from_user.username, m.from_user.id))
        self.bot.send_message(m.chat.id, text)

    @staticmethod
    def ignore_unauthorized_users(c: CallbackQuery):
        """
        Игнорирует callback'и от не авторизированных пользователей.
        """
        logger.warning(_("log_click_attempt", c.from_user.username, c.from_user.id, c.message.chat.username,
                         c.message.chat.id))
        return

    @staticmethod
    def _is_photo_message(message: Message) -> bool:
        return message.content_type == "photo" or bool(message.photo)

    def _send_photo_screen(self, chat_id: int, image_path, caption: str,
                           reply_markup: K | None = None) -> Message | None:
        if not image_path.is_file():
            return self.bot.send_message(
                chat_id, caption, reply_markup=reply_markup, parse_mode="HTML",
            )
        with open(image_path, "rb") as photo:
            return self.bot.send_photo(
                chat_id, photo, caption=caption, reply_markup=reply_markup, parse_mode="HTML",
            )

    def _edit_photo_screen(self, chat_id: int, message_id: int, image_path, caption: str,
                           reply_markup: K, *, from_photo: bool) -> None:
        if not image_path.is_file():
            if from_photo:
                self.bot.edit_message_caption(
                    caption, chat_id, message_id, reply_markup=reply_markup, parse_mode="HTML",
                )
            else:
                self.bot.edit_message_text(
                    caption, chat_id, message_id, reply_markup=reply_markup, parse_mode="HTML",
                )
            return
        with open(image_path, "rb") as photo:
            if from_photo:
                self.bot.edit_message_media(
                    InputMediaPhoto(photo, caption=caption, parse_mode="HTML"),
                    chat_id, message_id, reply_markup=reply_markup,
                )
            else:
                try:
                    self.bot.delete_message(chat_id, message_id)
                except Exception:
                    logger.debug("Не удалось удалить сообщение перед отправкой фото.", exc_info=True)
                photo.seek(0)
                self.bot.send_photo(
                    chat_id, photo, caption=caption, reply_markup=reply_markup, parse_mode="HTML",
                )

    def _edit_text_screen(self, chat_id: int, message_id: int, text: str, reply_markup: K,
                          *, from_photo: bool) -> None:
        if from_photo:
            try:
                self.bot.delete_message(chat_id, message_id)
            except Exception:
                logger.debug("Не удалось удалить фото-сообщение перед текстовым экраном.", exc_info=True)
            self.bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            self.bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup, parse_mode="HTML")

    # Команды
    def send_settings_menu(self, m: Message):
        """
        Отправляет основное меню настроек (новым сообщением).
        """
        if self.assistant.setup_mode:
            self.bot.send_message(m.chat.id, _("setup_in_progress"))
            return
        if self.assistant.account is None:
            self.bot.send_message(m.chat.id, _("setup_in_progress"))
            return
        try:
            self.assistant.account.get()
            self.assistant.balance = self.assistant.get_balance()
        except Exception:
            logger.error("Не удалось обновить профиль перед открытием меню.")
            logger.debug("TRACEBACK", exc_info=True)
            self.bot.send_message(m.chat.id, _("profile_updating_error"))
            return
        self._send_photo_screen(
            m.chat.id,
            static_assets.MAIN_MENU_IMAGE,
            _("desc_main"),
            kb.settings_sections(self.assistant),
        )

    def _send_profile_to_chat(self, chat_id: int) -> None:
        new_msg = self.bot.send_message(chat_id, _("updating_profile"))
        try:
            self.assistant.account.get()
            self.assistant.balance = self.assistant.get_balance()
            self.bot.send_message(
                chat_id,
                helpers.generate_profile_text(self.assistant),
                reply_markup=telebot.types.InlineKeyboardMarkup()
                .add(telebot.types.InlineKeyboardButton("🔄 Обновить", callback_data="update_profile"))
                .add(telebot.types.InlineKeyboardButton("▶️ Еще", callback_data="update_adv_profile")),
            )
            self.bot.delete_message(new_msg.chat.id, new_msg.id)
        except Exception:
            self.bot.edit_message_text(_("profile_updating_error"), new_msg.chat.id, new_msg.id)
            logger.debug("TRACEBACK", exc_info=True)

    def send_profile(self, m: Message):
        """Отправляет статистику аккаунта."""
        self._send_profile_to_chat(m.chat.id)

    def open_menu_profile(self, c: CallbackQuery):
        """Профиль из главного меню."""
        self.bot.answer_callback_query(c.id)
        self._send_profile_to_chat(c.message.chat.id)

    def update_profile(self, c: CallbackQuery):
        """
        Обновляет статистику аккаунта.
        """
        self.bot.answer_callback_query(c.id)
        new_msg = self.bot.send_message(c.message.chat.id, _("updating_profile"))
        try:
            self.assistant.account.get()
            self.assistant.balance = self.assistant.get_balance()
            self.bot.edit_message_text(helpers.generate_profile_text(self.assistant), c.message.chat.id,
                                c.message.id,
                                reply_markup=telebot.types.InlineKeyboardMarkup()
                                .add(telebot.types.InlineKeyboardButton("🔄 Обновить", callback_data="update_profile"))
                                .add(telebot.types.InlineKeyboardButton("▶️ Еще", callback_data="update_adv_profile"))
                                )
            self.bot.delete_message(new_msg.chat.id, new_msg.id)
        except:
            self.bot.edit_message_text(_("profile_updating_error"), new_msg.chat.id, new_msg.id)
            logger.debug("TRACEBACK", exc_info=True)
            return

    def golden_key(self, m: telebot.types.Message):
        parts = m.text.split(maxsplit=1)
        if len(parts) != 2:
            self.bot.send_message(m.chat.id, "Команда введена неправильно: /golden_key <ключ>")
            return

        new_golden_key = parts[1].strip()
        if len(new_golden_key) != 32:
            self.bot.send_message(m.chat.id, "Неверный формат токена. Попробуй еще раз!")
            return

        old_golden_key = self.assistant.account.golden_key
        self.assistant.account.golden_key = new_golden_key
        try:
            self.assistant.account.get(True)
        except Exception:
            self.assistant.account.golden_key = old_golden_key
            self.bot.send_message(m.chat.id, "❌ Не удалось проверить новый golden_key. Старый ключ сохранен.")
            logger.debug("TRACEBACK", exc_info=True)
            return

        self.assistant.MAIN_CFG.set("FunPay", "golden_key", new_golden_key)
        self.assistant.save_config(self.assistant.MAIN_CFG, "configs/_main.cfg")
        self.bot.send_message(m.chat.id, "✅ Успешно изменено перезапустите бота.")

    def update_adv_profile(self, c: CallbackQuery):
        """
        Обновляет дополнительную статистику аккаунта.
        """
        self.bot.answer_callback_query(c.id)
        new_msg = self.bot.send_message(c.message.chat.id, _("updating_profile"))
        try:
            self.assistant.account.get()
            self.assistant.balance = self.assistant.get_balance()
            self.bot.edit_message_text(helpers.generate_adv_profile(self.assistant), c.message.chat.id,
                                c.message.id,
                                reply_markup=telebot.types.InlineKeyboardMarkup()
                                .add(telebot.types.InlineKeyboardButton("🔄 Обновить", callback_data="update_adv_profile"))
                                .add(telebot.types.InlineKeyboardButton("◀️ Назад", callback_data="update_profile"))
                                )
            self.bot.delete_message(new_msg.chat.id, new_msg.id)
        except:
            self.bot.edit_message_text(_("profile_updating_error"), new_msg.chat.id, new_msg.id)
            logger.debug("TRACEBACK", exc_info=True)
            return

    def _send_old_orders_to_chat(self, chat_id: int) -> None:
        new_mes = self.bot.send_message(chat_id, _("old_orders_scanning"))
        try:
            orders = helpers.get_all_open_orders(self.assistant.account)
        except Exception:
            self.bot.edit_message_text(_("old_orders_fetch_error"), new_mes.chat.id, new_mes.id)
            logger.debug("TRACEBACK", exc_info=True)
            return

        if not orders:
            self.bot.edit_message_text(_("old_orders_empty"), new_mes.chat.id, new_mes.id)
            return

        orders_text = ", ".join(orders)
        copy_message = helpers.escape(_("old_orders_copy_text", orders_text))
        text = _("old_orders_result", _("old_orders_ticket_url"), copy_message)
        self.bot.edit_message_text(text, new_mes.chat.id, new_mes.id, disable_web_page_preview=True)

    def send_orders(self, m: telebot.types.Message):
        self._send_old_orders_to_chat(m.chat.id)

    def open_menu_old_orders(self, c: CallbackQuery):
        """Старые заказы из главного меню."""
        self.bot.answer_callback_query(c.id)
        self._send_old_orders_to_chat(c.message.chat.id)

    def act_manual_delivery_test(self, m: Message):
        """
        Активирует режим ввода названия лота для ручной генерации ключа теста автовыдачи.
        """
        result = self.bot.send_message(m.chat.id, _("create_test_ad_key"), reply_markup=presets.CLEAR_STATE_BTN())
        self.set_state(m.chat.id, result.id, m.from_user.id, cb.MANUAL_AD_TEST)

    def manual_delivery_text(self, m: Message):
        """
        Генерирует ключ теста автовыдачи (ручной режим).
        """
        self.clear_state(m.chat.id, m.from_user.id, True)
        lot_name = m.text.strip()
        key = "".join(random.sample(string.ascii_letters + string.digits, 50))
        self.assistant.delivery_tests[key] = lot_name

        logger.info(_("log_new_ad_key", m.from_user.username, m.from_user.id, lot_name, key))
        self.bot.send_message(m.chat.id, _("test_ad_key_created", helpers.escape(lot_name), key))

    def act_ban(self, m: Message):
        """
        Активирует режим ввода никнейма пользователя, которого нужно добавить в ЧС.
        """
        result = self.bot.send_message(m.chat.id, _("act_blacklist"), reply_markup=presets.CLEAR_STATE_BTN())
        self.set_state(m.chat.id, result.id, m.from_user.id, cb.BAN)

    def ban(self, m: Message):
        """
        Добавляет пользователя в ЧС.
        """
        self.clear_state(m.chat.id, m.from_user.id, True)
        nickname = m.text.strip()

        if nickname in self.assistant.blacklist:
            self.bot.send_message(m.chat.id, _("already_blacklisted", nickname))
            return

        self.assistant.blacklist.append(nickname)
        assistant_tools.cache_blacklist(self.assistant.blacklist)
        logger.info(_("log_user_blacklisted", m.from_user.username, m.from_user.id, nickname))
        self.bot.send_message(m.chat.id, _("user_blacklisted", nickname))

    def act_unban(self, m: Message):
        """
        Активирует режим ввода никнейма пользователя, которого нужно удалить из ЧС.
        """
        result = self.bot.send_message(m.chat.id, _("act_unban"), reply_markup=presets.CLEAR_STATE_BTN())
        self.set_state(m.chat.id, result.id, m.from_user.id, cb.UNBAN)

    def unban(self, m: Message):
        """
        Удаляет пользователя из ЧС.
        """
        self.clear_state(m.chat.id, m.from_user.id, True)
        nickname = m.text.strip()
        if nickname not in self.assistant.blacklist:
            self.bot.send_message(m.chat.id, _("not_blacklisted", nickname))
            return
        self.assistant.blacklist.remove(nickname)
        assistant_tools.cache_blacklist(self.assistant.blacklist)
        logger.info(_("log_user_unbanned", m.from_user.username, m.from_user.id, nickname))
        self.bot.send_message(m.chat.id, _("user_unbanned", nickname))

    def send_ban_list(self, m: Message):
        """
        Отправляет ЧС.
        """
        if not self.assistant.blacklist:
            self.bot.send_message(m.chat.id, _("blacklist_empty"))
            return
        blacklist = ", ".join(f"<code>{i}</code>" for i in self.assistant.blacklist)
        self.bot.send_message(m.chat.id, blacklist)

    def handle_setup_group_id(self, m: Message) -> None:
        """Привязка группы по ID во время первичной настройки (после выбора «Да»)."""
        if m.chat.type != "private" or not self.assistant.awaiting_setup_group_link:
            return
        if m.from_user.id not in self.authorized_users:
            return
        raw = (m.text or "").strip()
        if not raw or not re.fullmatch(r"-?\d+", raw.replace(" ", "")):
            return
        ok, text = self.group_topics.link_group_by_id(raw)
        self.bot.send_message(m.chat.id, text)

    def act_set_group_chat_id(self, c: CallbackQuery):
        self.bot.answer_callback_query(c.id)
        result = self.bot.send_message(
            c.message.chat.id,
            _("act_set_group_chat_id"),
            reply_markup=presets.CLEAR_STATE_BTN(),
        )
        self.set_state(c.message.chat.id, result.message_id, c.from_user.id, cb.EDIT_GROUP_CHAT_ID)

    def set_group_chat_id(self, m: Message):
        self.clear_state(m.chat.id, m.from_user.id, True)
        ok, text = self.group_topics.link_group_by_id(m.text or "")
        keyboard = kb.group_topics_settings(self.assistant)
        self.bot.send_message(m.chat.id, text, reply_markup=keyboard)
        if ok:
            logger.info(
                "Группа привязана вручную пользователем %s (ID: %s): %s",
                m.from_user.username, m.from_user.id, self.group_topics.group_chat_id(),
            )

    def send_logs(self, m: Message):
        """
        Отправляет файл логов.
        """
        if not os.path.exists("logs/log.log"):
            self.bot.send_message(m.chat.id, _("logfile_not_found"))
        else:
            self.bot.send_message(m.chat.id, _("logfile_sending"))
            try:
                with open("logs/log.log", "r", encoding="utf-8") as f:
                    self.bot.send_document(m.chat.id, f)
            except:
                self.bot.send_message(m.chat.id, _("logfile_error"))
                logger.debug("TRACEBACK", exc_info=True)

    def del_logs(self, m: Message):
        """
        Удаляет старые лог-файлы.
        """
        deleted = 0
        for file in os.listdir("logs"):
            if not file.endswith(".log"):
                try:
                    os.remove(f"logs/{file}")
                    deleted += 1
                except:
                    continue
        self.bot.send_message(m.chat.id, _("logfile_deleted"))

    def about(self, m: Message):
        """
        Отправляет информацию о текущей версии бота.
        """
        self.bot.send_message(m.chat.id, _("about", self.assistant.VERSION))

    def send_system_info(self, m: Message):
        """
        Отправляет информацию о нагрузке на систему.
        """
        current_time = int(time.time())
        uptime = current_time - self.assistant.start_time

        ram = psutil.virtual_memory()
        cpu_usage = "\n".join(
            f"    CPU {i}:  <code>{l}%</code>" for i, l in enumerate(psutil.cpu_percent(percpu=True)))
        self.bot.send_message(m.chat.id, _("sys_info", cpu_usage, psutil.Process().cpu_percent(),
                                           ram.total // 1048576, ram.used // 1048576, ram.free // 1048576,
                                           psutil.Process().memory_info().rss // 1048576,
                                           assistant_tools.time_to_str(uptime), m.chat.id))

    def restart_assistant(self, m: Message):
        """
        Перезапускает ассистент.
        """
        self.bot.send_message(m.chat.id, _("restarting"))
        assistant_tools.restart_program()

    def ask_power_off(self, m: Message):
        """
        Просит подтверждение на отключение FPW.
        """
        self.bot.send_message(m.chat.id, _("power_off_0"), reply_markup=kb.power_off(self.assistant.instance_id, 0))

    def cancel_power_off(self, c: CallbackQuery):
        """
        Отменяет выключение (удаляет клавиатуру с кнопками подтверждения).
        """
        self.bot.edit_message_text(_("power_off_cancelled"), c.message.chat.id, c.message.id)
        self.bot.answer_callback_query(c.id)

    def power_off(self, c: CallbackQuery):
        """
        Отключает FPW.
        """
        split = c.data.split(":")
        state = int(split[1])
        instance_id = int(split[2])

        if instance_id != self.assistant.instance_id:
            self.bot.edit_message_text(_("power_off_error"), c.message.chat.id, c.message.id)
            self.bot.answer_callback_query(c.id)
            return

        if state == 6:
            self.bot.edit_message_text(_("power_off_6"), c.message.chat.id, c.message.id)
            self.bot.answer_callback_query(c.id)
            assistant_tools.shut_down()
            return

        self.bot.edit_message_text(_(f"power_off_{state}"), c.message.chat.id, c.message.id,
                                   reply_markup=kb.power_off(instance_id, state))
        self.bot.answer_callback_query(c.id)

    # Чат FunPay
    def act_send_funpay_message(self, c: CallbackQuery):
        """
        Открывает топик покупателя в группе или активирует ввод ответа в FunPay (без топиков).
        """
        split = c.data.split(":")
        node_id = int(split[1])
        try:
            username = split[2]
        except IndexError:
            username = None

        if self.group_topics.is_active() and username:
            if self.group_topics.open_buyer_topic_for_reply(node_id, username, c.from_user.id):
                self.bot.answer_callback_query(c.id, _("gt_topic_open_alert"))
                return
            self.bot.answer_callback_query(c.id, _("gt_topic_open_failed"), show_alert=True)

        result = self.bot.send_message(c.message.chat.id, _("enter_msg_text"), reply_markup=presets.CLEAR_STATE_BTN())
        self.set_state(c.message.chat.id, result.id, c.from_user.id,
                       cb.SEND_FP_MESSAGE, {"node_id": node_id, "username": username})
        self.bot.answer_callback_query(c.id)

    def send_funpay_message(self, message: Message):
        """
        Отправляет сообщение в чат FunPay.
        """
        data = self.get_state(message.chat.id, message.from_user.id)["data"]
        node_id, username = data["node_id"], data["username"]
        self.clear_state(message.chat.id, message.from_user.id, True)
        response_text = message.text.strip()
        result = self.assistant.send_message(node_id, response_text, username)
        if result:
            self.bot.reply_to(message, _("msg_sent", node_id, username),
                              reply_markup=kb.reply(node_id, username, again=True, extend=True))
        else:
            self.bot.reply_to(message, _("msg_sending_error", node_id, username),
                              reply_markup=kb.reply(node_id, username, again=True, extend=True))

    def act_upload_image(self, m: Message):
        """
        Активирует режим ожидания изображения для последующей выгрузки на FunPay.
        """
        result = self.bot.send_message(m.chat.id, _("send_img"), reply_markup=presets.CLEAR_STATE_BTN())
        self.set_state(m.chat.id, result.id, m.from_user.id, cb.UPLOAD_IMAGE)

    def act_edit_greetings_text(self, c: CallbackQuery):
        variables = ["v_date", "v_date_text", "v_full_date_text", "v_time", "v_full_time", "v_username",
                     "v_message_text", "v_chat_id", "v_photo"]
        text = f"{_('v_edit_greeting_text')}\n\n{_('v_list')}:\n" + "\n".join(_(i) for i in variables)
        result = self.bot.send_message(c.message.chat.id, text, reply_markup=presets.CLEAR_STATE_BTN())
        self.set_state(c.message.chat.id, result.id, c.from_user.id, cb.EDIT_GREETINGS_TEXT)
        self.bot.answer_callback_query(c.id)

    def edit_greetings_text(self, m: Message):
        self.clear_state(m.chat.id, m.from_user.id, True)
        self.assistant.MAIN_CFG["Greetings"]["greetingsText"] = m.text
        logger.info(_("log_greeting_changed", m.from_user.username, m.from_user.id, m.text))
        self.assistant.save_config(self.assistant.MAIN_CFG, "configs/_main.cfg")
        keyboard = K() \
            .row(B(_("gl_back"), callback_data=f"{cb.CATEGORY}:gr"),
                 B(_("gl_edit"), callback_data=cb.EDIT_GREETINGS_TEXT))
        self.bot.reply_to(m, _("greeting_changed"), reply_markup=keyboard)

    def act_edit_order_confirm_reply_text(self, c: CallbackQuery):
        variables = ["v_date", "v_date_text", "v_full_date_text", "v_time", "v_full_time", "v_username",
                     "v_order_id", "v_order_title", "v_photo"]
        text = f"{_('v_edit_order_confirm_text')}\n\n{_('v_list')}:\n" + "\n".join(_(i) for i in variables)
        result = self.bot.send_message(c.message.chat.id, text, reply_markup=presets.CLEAR_STATE_BTN())
        self.set_state(c.message.chat.id, result.id, c.from_user.id, cb.EDIT_ORDER_CONFIRM_REPLY_TEXT)
        self.bot.answer_callback_query(c.id)

    def edit_order_confirm_reply_text(self, m: Message):
        self.clear_state(m.chat.id, m.from_user.id, True)
        self.assistant.MAIN_CFG["OrderConfirm"]["replyText"] = m.text
        logger.info(_("log_order_confirm_changed", m.from_user.username, m.from_user.id, m.text))
        self.assistant.save_config(self.assistant.MAIN_CFG, "configs/_main.cfg")
        keyboard = K() \
            .row(B(_("gl_back"), callback_data=f"{cb.CATEGORY}:oc"),
                 B(_("gl_edit"), callback_data=cb.EDIT_ORDER_CONFIRM_REPLY_TEXT))
        self.bot.reply_to(m, _("order_confirm_changed"), reply_markup=keyboard)

    def act_edit_review_reminder_text(self, c: CallbackQuery):
        variables = ["v_date", "v_date_text", "v_full_date_text", "v_time", "v_full_time", "v_username",
                     "v_order_id", "v_order_title", "v_photo"]
        text = f"{_('v_edit_review_reminder_text')}\n\n{_('v_list')}:\n" + "\n".join(_(i) for i in variables)
        result = self.bot.send_message(c.message.chat.id, text, reply_markup=presets.CLEAR_STATE_BTN())
        self.set_state(c.message.chat.id, result.id, c.from_user.id, cb.EDIT_REVIEW_REMINDER_TEXT)
        self.bot.answer_callback_query(c.id)

    def edit_review_reminder_text(self, m: Message):
        self.clear_state(m.chat.id, m.from_user.id, True)
        self.assistant.MAIN_CFG["ReviewReminder"]["reminderText"] = m.text
        logger.info(_("log_review_reminder_changed", m.from_user.username, m.from_user.id, m.text))
        self.assistant.save_config(self.assistant.MAIN_CFG, "configs/_main.cfg")
        keyboard = K() \
            .row(B(_("gl_back"), callback_data=f"{cb.CATEGORY}:rm"),
                 B(_("gl_edit"), callback_data=cb.EDIT_REVIEW_REMINDER_TEXT))
        self.bot.reply_to(m, _("review_reminder_changed"), reply_markup=keyboard)

    def act_edit_review_reply_text(self, c: CallbackQuery):
        stars = int(c.data.split(":")[1])
        variables = ["v_date", "v_date_text", "v_full_date_text", "v_time", "v_full_time", "v_username",
                     "v_order_id", "v_order_title"]
        text = f"{_('v_edit_review_reply_text', '⭐'*stars)}\n\n{_('v_list')}:\n" + "\n".join(_(i) for i in variables)
        result = self.bot.send_message(c.message.chat.id, text, reply_markup=presets.CLEAR_STATE_BTN())
        self.set_state(c.message.chat.id, result.id, c.from_user.id, cb.EDIT_REVIEW_REPLY_TEXT, {"stars": stars})
        self.bot.answer_callback_query(c.id)

    def edit_review_reply_text(self, m: Message):
        stars = self.get_state(m.chat.id, m.from_user.id)["data"]["stars"]
        self.clear_state(m.chat.id, m.from_user.id, True)
        self.assistant.MAIN_CFG["ReviewReply"][f"star{stars}ReplyText"] = m.text
        logger.info(_("log_review_reply_changed", m.from_user.username, m.from_user.id, stars, m.text))
        self.assistant.save_config(self.assistant.MAIN_CFG, "configs/_main.cfg")
        keyboard = K() \
            .row(B(_("gl_back"), callback_data=f"{cb.CATEGORY}:rr"),
                 B(_("gl_edit"), callback_data=f"{cb.EDIT_REVIEW_REPLY_TEXT}:{stars}"))
        self.bot.reply_to(m, _("review_reply_changed", '⭐'*stars), reply_markup=keyboard)

    def open_reply_menu(self, c: CallbackQuery):
        """
        Открывает меню ответа на сообщение (callback используется в кнопках "назад").
        """
        split = c.data.split(":")
        node_id, username, again = int(split[1]), split[2], int(split[3])
        extend = True if len(split) > 4 and int(split[4]) else False
        self.bot.edit_message_reply_markup(c.message.chat.id, c.message.id,
                                           reply_markup=kb.reply(node_id, username, bool(again), extend))

    def extend_new_message_notification(self, c: CallbackQuery):
        """
        "Расширяет" уведомление о новом сообщении.
        """
        chat_id, username = c.data.split(":")[1:]
        try:
            chat = self.assistant.account.get_chat(int(chat_id))
        except:
            self.bot.answer_callback_query(c.id)
            self.bot.send_message(c.message.chat.id, _("get_chat_error"))
            return

        text = ""
        if chat.looking_link:
            text += f"<b><i>{_('viewing')}:</i></b>\n<a href=\"{chat.looking_link}\">{chat.looking_text}</a>\n\n"

        messages = chat.messages[-10:]
        last_message_author_id = -1
        for i in messages:
            if i.author_id == last_message_author_id:
                author = ""
            elif i.author_id == self.assistant.account.id:
                author = f"<i><b>🫵 {_('you')}:</b></i> "
            elif i.author_id == 0:
                author = f"<i><b>🔵 {i.author}: </b></i>"
            elif i.author == i.chat_name:
                author = f"<i><b>👤 {i.author}: </b></i>"
            else:
                author = f"<i><b>🆘 {i.author} ({_('support')}): </b></i>"
            msg_text = f"<code>{i.text}</code>" if i.text else f"<a href=\"{i.image_link}\">{_('photo')}</a>"
            text += f"{author}{msg_text}\n\n"
            last_message_author_id = i.author_id

        self.bot.edit_message_text(text, c.message.chat.id, c.message.id,
                                   reply_markup=kb.reply(int(chat_id), username, False, False))

    # Ордер
    def ask_confirm_refund(self, call: CallbackQuery):
        """
        Просит подтвердить возврат денег.
        """
        split = call.data.split(":")
        order_id, node_id, username = split[1], int(split[2]), split[3]
        keyboard = kb.new_order(order_id, username, node_id, confirmation=True)
        self.bot.edit_message_reply_markup(call.message.chat.id, call.message.id, reply_markup=keyboard)
        self.bot.answer_callback_query(call.id)

    def cancel_refund(self, call: CallbackQuery):
        """
        Отменяет возврат.
        """
        split = call.data.split(":")
        order_id, node_id, username = split[1], int(split[2]), split[3]
        keyboard = kb.new_order(order_id, username, node_id)
        self.bot.edit_message_reply_markup(call.message.chat.id, call.message.id, reply_markup=keyboard)
        self.bot.answer_callback_query(call.id)

    def refund(self, c: CallbackQuery):
        """
        Оформляет возврат за заказ.
        """
        split = c.data.split(":")
        order_id, node_id, username = split[1], int(split[2]), split[3]
        new_msg = None
        attempts = 3
        while attempts:
            try:
                self.assistant.account.refund(order_id)
                break
            except:
                if not new_msg:
                    new_msg = self.bot.send_message(c.message.chat.id, _("refund_attempt", order_id, attempts))
                else:
                    self.bot.edit_message_text(_("refund_attempt", order_id, attempts), new_msg.chat.id, new_msg.id)
                attempts -= 1
                time.sleep(1)

        else:
            self.bot.edit_message_text(_("refund_error", order_id), new_msg.chat.id, new_msg.id)

            keyboard = kb.new_order(order_id, username, node_id)
            self.bot.edit_message_reply_markup(c.message.chat.id, c.message.id, reply_markup=keyboard)
            self.bot.answer_callback_query(c.id)
            return

        if not new_msg:
            self.bot.send_message(c.message.chat.id, _("refund_complete", order_id))
        else:
            self.bot.edit_message_text(_("refund_complete", order_id), new_msg.chat.id, new_msg.id)

        keyboard = kb.new_order(order_id, username, node_id, no_refund=True)
        self.bot.edit_message_reply_markup(c.message.chat.id, c.message.id, reply_markup=keyboard)
        self.bot.answer_callback_query(c.id)

    def open_order_menu(self, c: CallbackQuery):
        split = c.data.split(":")
        node_id, username, order_id, no_refund = int(split[1]), split[2], split[3], bool(int(split[4]))
        self.bot.edit_message_reply_markup(c.message.chat.id, c.message.id,
                                           reply_markup=kb.new_order(order_id, username, node_id, no_refund=no_refund))
        self.bot.answer_callback_query(c.id)

    # Панель управления
    def open_cp(self, c: CallbackQuery):
        """
        Открывает основное меню настроек (редактирует сообщение).
        """
        from_photo = self._is_photo_message(c.message)
        self._edit_photo_screen(
            c.message.chat.id,
            c.message.id,
            static_assets.MAIN_MENU_IMAGE,
            _("desc_main"),
            kb.settings_sections(self.assistant),
            from_photo=from_photo,
        )
        self.bot.answer_callback_query(c.id)

    def open_deep_settings(self, c: CallbackQuery):
        """
        Открывает страницу «Глубокие настройки».
        """
        self._edit_text_screen(
            c.message.chat.id,
            c.message.id,
            _("desc_deep"),
            kb.deep_settings_sections(self.assistant),
            from_photo=self._is_photo_message(c.message),
        )
        self.bot.answer_callback_query(c.id)

    def open_analytics_menu(self, c: CallbackQuery):
        """Меню выбора блоков аналитики."""
        self._edit_text_screen(
            c.message.chat.id,
            c.message.id,
            _("desc_analytics"),
            kb.analytics_menu(c.from_user.id),
            from_photo=self._is_photo_message(c.message),
        )
        self.bot.answer_callback_query(c.id)

    def toggle_analytics_section(self, c: CallbackQuery):
        section_id = c.data.split(":")[-1]
        analytics.toggle_user_pref(c.from_user.id, section_id)
        self.bot.edit_message_reply_markup(
            c.message.chat.id,
            c.message.id,
            reply_markup=kb.analytics_menu(c.from_user.id),
        )
        self.bot.answer_callback_query(c.id)

    def run_analytics_report(self, c: CallbackQuery):
        if not analytics.enabled_sections(c.from_user.id):
            self.bot.answer_callback_query(c.id, _("an_select_one"), show_alert=True)
            return

        self.bot.answer_callback_query(c.id)
        wait_msg = self.bot.send_message(c.message.chat.id, _("analytics_loading"))
        try:
            self.assistant.account.get()
            self.assistant.balance = self.assistant.get_balance()
            text = analytics.build_report(self.assistant, c.from_user.id)
        except Exception:
            logger.error("Ошибка сборки аналитики.")
            logger.debug("TRACEBACK", exc_info=True)
            text = _("analytics_error")

        try:
            self.bot.delete_message(wait_msg.chat.id, wait_msg.message_id)
        except Exception:
            pass

        self.bot.send_message(
            c.message.chat.id,
            text,
            reply_markup=kb.analytics_report_actions(),
        )

    def open_cp2(self, c: CallbackQuery):
        """Обратная совместимость со старым callback «Далее» — открывает главное меню."""
        self.open_cp(c)

    def switch_param(self, c: CallbackQuery):
        """
        Переключает переключаемые настройки FPW.
        """
        split = c.data.split(":")
        section, option = split[1], split[2]
        self.assistant.MAIN_CFG[section][option] = str(int(not int(self.assistant.MAIN_CFG[section][option])))
        self.assistant.save_config(self.assistant.MAIN_CFG, "configs/_main.cfg")
        if section == "Telegram" and option == "groupTopicsEnabled":
            if self.assistant.MAIN_CFG["Telegram"].getboolean("groupTopicsEnabled"):
                self.assistant.MAIN_CFG["Telegram"]["groupNotificationsEnabled"] = "1"
                self.assistant.save_config(self.assistant.MAIN_CFG, "configs/_main.cfg")
                self.group_topics.ensure_group_notifications()
                Thread(target=self.group_topics._ensure_system_topic_async, daemon=True).start()

        sections = {
            "FunPay": kb.main_settings,
            "BlockList": kb.blacklist_settings,
            "NewMessageView": kb.new_message_view_settings,
            "Greetings": kb.greeting_settings,
            "OrderConfirm": kb.order_confirm_reply_settings,
            "ReviewReminder": kb.review_reminder_settings,
            "ReviewReply": kb.review_reply_settings,
            "Telegram": kb.group_topics_settings
        }
        self.bot.edit_message_reply_markup(c.message.chat.id, c.message.id,
                                           reply_markup=sections[section](self.assistant))
        logger.info(_("log_param_changed", c.from_user.username, c.from_user.id, option, section, self.assistant.MAIN_CFG[section][option]))
        self.bot.answer_callback_query(c.id)

    def switch_chat_notification(self, c: CallbackQuery):
        split = c.data.split(":")
        notification_type = split[2]
        pm_chat_id = self.primary_notification_chat_id() or int(split[1])

        result = self.toggle_notification(pm_chat_id, notification_type)
        logger.info(_("log_notification_switched", c.from_user.username, c.from_user.id,
                      notification_type, pm_chat_id, result))
        keyboard = kb.announcements_settings if notification_type in [helpers.NotificationTypes.announcement,
                                                                      helpers.NotificationTypes.ad] \
            else kb.notifications_settings
        self.bot.edit_message_reply_markup(c.message.chat.id, c.message.id,
                                           reply_markup=keyboard(self.assistant, pm_chat_id))
        self.bot.answer_callback_query(c.id)

    def toggle_group_notifications(self, c: CallbackQuery):
        """Переключатель «Все уведомления в группу»."""
        if not self.group_topics.is_active():
            self.bot.answer_callback_query(c.id, _("gt_no_group_linked"), show_alert=True)
            return
        tg = self.assistant.MAIN_CFG["Telegram"]
        tg["groupNotificationsEnabled"] = str(int(not tg.getboolean("groupNotificationsEnabled")))
        self.assistant.save_config(self.assistant.MAIN_CFG, "configs/_main.cfg")
        self._migrate_notification_settings()

        pm_chat_id = self.primary_notification_chat_id() or c.message.chat.id
        self.bot.edit_message_reply_markup(
            c.message.chat.id,
            c.message.id,
            reply_markup=kb.notifications_settings(self.assistant, pm_chat_id),
        )
        self.bot.answer_callback_query(c.id)

    def open_settings_section(self, c: CallbackQuery):
        """
        Открывает выбранную категорию настроек.
        """
        #
        section = c.data.split(":")[1]
        pm_chat_id = self.primary_notification_chat_id() or c.message.chat.id
        sections = {
            "main": (_("desc_gs"), kb.main_settings, [self.assistant]),
            "tg": (_("desc_ns"), kb.notifications_settings, [self.assistant, pm_chat_id]),
            "bl": (_("desc_bl"), kb.blacklist_settings, [self.assistant]),
            "ar": (_("desc_ar"), presets.AR_SETTINGS, []),
            "ad": (_("desc_ad"), presets.AD_SETTINGS, []),
            "mv": (_("desc_mv"), kb.new_message_view_settings, [self.assistant]),
            "rr": (_("desc_or"), kb.review_reply_settings, [self.assistant]),
            "gr": (_("desc_gr", helpers.escape(self.assistant.MAIN_CFG['Greetings']['greetingsText'])),
                   kb.greeting_settings, [self.assistant]),
            "oc": (_("desc_oc", helpers.escape(self.assistant.MAIN_CFG['OrderConfirm']['replyText'])),
                   kb.order_confirm_reply_settings, [self.assistant]),
            "rm": (_("desc_rm", helpers.escape(self.assistant.MAIN_CFG['ReviewReminder']['reminderText'])),
                   kb.review_reminder_settings, [self.assistant]),
            "gt": (_("desc_gt", self.group_topics.group_chat_id() or "—"),
                   kb.group_topics_settings, [self.assistant]),
            "sp": (_("desc_support"), kb.support_settings, [self.assistant]),
        }

        curr = sections[section]
        chat_id, message_id = c.message.chat.id, c.message.id
        from_photo = self._is_photo_message(c.message)
        markup = curr[1](*curr[2])

        if section == "sp":
            self._edit_photo_screen(
                chat_id, message_id, static_assets.SUPPORT_IMAGE, curr[0], markup, from_photo=from_photo,
            )
        else:
            self._edit_text_screen(chat_id, message_id, curr[0], markup, from_photo=from_photo)
        self.bot.answer_callback_query(c.id)

    # Прочее
    def cancel_action(self, call: CallbackQuery):
        """
        Обнуляет состояние пользователя по кнопке "Отмена" (cb.CLEAR_STATE).
        """
        result = self.clear_state(call.message.chat.id, call.from_user.id, True)
        if result is None:
            self.bot.answer_callback_query(call.id)

    def param_disabled(self, c: CallbackQuery):
        """
        Отправляет сообщение о том, что параметр отключен в глобальных переключателях.
        """
        self.bot.answer_callback_query(c.id, _("param_disabled"), show_alert=True)

    def send_announcements_kb(self, m: Message):
        """
        Отправляет сообщение с клавиатурой управления уведомлениями о новых объявлениях.
        """
        self.bot.send_message(m.chat.id, _("desc_an"), reply_markup=kb.announcements_settings(self.assistant, m.chat.id))

    def send_review_reply_text(self, c: CallbackQuery):
        stars = int(c.data.split(":")[1])
        text = self.assistant.MAIN_CFG["ReviewReply"][f"star{stars}ReplyText"]
        keyboard = K() \
            .row(B(_("gl_back"), callback_data=f"{cb.CATEGORY}:rr"),
                 B(_("gl_edit"), callback_data=f"{cb.EDIT_REVIEW_REPLY_TEXT}:{stars}"))
        if not text:
            self.bot.send_message(c.message.chat.id, _("review_reply_empty", "⭐"*stars), reply_markup=keyboard)
        else:
            self.bot.send_message(c.message.chat.id, _("review_reply_text", "⭐"*stars,
                                                       self.assistant.MAIN_CFG['ReviewReply'][f'star{stars}ReplyText']),
                                  reply_markup=keyboard)
        self.bot.answer_callback_query(c.id)

    def empty_callback(self, c: CallbackQuery):
        self.bot.answer_callback_query(c.id)

    def open_keyboard(self, m: Message):
        self.bot.send_message(m.chat.id, "Клавиатура появилась!", reply_markup=presets.OLD_KEYBOARD)
    
    def close_keyboard(self, m: Message):
        self.bot.send_message(m.chat.id, "Клавиатура скрыта!", reply_markup=ReplyKeyboardRemove())
    
    def __register_handlers(self):
        """
        Регистрирует хэндлеры всех команд.
        """
        self.mdw_handler(self.setup_chat_notifications, update_types=['message'])
        self.mdw_handler(self.handle_group_topics, update_types=['message'])
        self.msg_handler(
            self.handle_start,
            func=lambda m: m.chat.type == "private" and self._is_command_start(m),
        )
        self.msg_handler(
            self.handle_setup,
            func=lambda m: m.chat.type == "private" and self._setup_active(m.chat.id, m.from_user.id),
        )
        self.msg_handler(
            self.handle_setup_group_id,
            func=lambda m: (
                m.chat.type == "private"
                and self.assistant.awaiting_setup_group_link
                and m.from_user.id in self.authorized_users
                and m.text
                and re.fullmatch(r"-?\d+", m.text.strip().replace(" ", ""))
            ),
        )
        self.msg_handler(
            self.reg_admin,
            func=lambda msg: not self.assistant.setup_mode and msg.from_user.id not in self.authorized_users,
        )
        self.cbq_handler(
            self.ignore_unauthorized_users,
            lambda c: not self.assistant.setup_mode and c.from_user.id not in self.authorized_users,
        )
        self.cbq_handler(
            self.setup_wizard.handle_skip_user_agent,
            lambda c: c.data == cb.SETUP_SKIP_UA and self._setup_active(c.message.chat.id, c.from_user.id),
        )
        self.cbq_handler(
            lambda c: self.setup_wizard.handle_group_topics_choice(c, True),
            lambda c: c.data == cb.SETUP_GROUP_TOPICS_YES,
        )
        self.cbq_handler(
            lambda c: self.setup_wizard.handle_group_topics_choice(c, False),
            lambda c: c.data == cb.SETUP_GROUP_TOPICS_NO,
        )
        self.cbq_handler(self.param_disabled, lambda c: c.data.startswith(cb.PARAM_DISABLED))
        self.msg_handler(self.run_file_handlers, content_types=["photo", "document"], func=lambda m: self.is_file_handler(m))

        self.msg_handler(self.send_settings_menu, commands=["menu"])
        self.cbq_handler(self.update_profile, lambda c: c.data == "update_profile")
        self.cbq_handler(self.update_adv_profile, lambda c: c.data == "update_adv_profile")
        self.msg_handler(self.send_profile, commands=["profile"])
        self.msg_handler(self.send_orders, commands=["old_orders"])
        self.msg_handler(self.golden_key, commands=["golden_key"])
        self.cbq_handler(self.update_profile, lambda c: c.data == cb.UPDATE_PROFILE)
        self.msg_handler(self.act_manual_delivery_test, commands=["test_delivery"])
        self.msg_handler(self.act_upload_image, commands=["upload_img"])
        self.cbq_handler(self.act_set_group_chat_id, lambda c: c.data == cb.EDIT_GROUP_CHAT_ID)
        self.msg_handler(self.set_group_chat_id,
                         func=lambda m: self.check_state(m.chat.id, m.from_user.id, cb.EDIT_GROUP_CHAT_ID))
        self.cbq_handler(self.act_edit_greetings_text, lambda c: c.data == cb.EDIT_GREETINGS_TEXT)
        self.msg_handler(self.edit_greetings_text,
                         func=lambda m: self.check_state(m.chat.id, m.from_user.id, cb.EDIT_GREETINGS_TEXT))
        self.cbq_handler(self.act_edit_order_confirm_reply_text, lambda c: c.data == cb.EDIT_ORDER_CONFIRM_REPLY_TEXT)
        self.msg_handler(self.edit_order_confirm_reply_text,
                         func=lambda m: self.check_state(m.chat.id, m.from_user.id, cb.EDIT_ORDER_CONFIRM_REPLY_TEXT))
        self.cbq_handler(self.act_edit_review_reminder_text, lambda c: c.data == cb.EDIT_REVIEW_REMINDER_TEXT)
        self.msg_handler(self.edit_review_reminder_text,
                         func=lambda m: self.check_state(m.chat.id, m.from_user.id, cb.EDIT_REVIEW_REMINDER_TEXT))
        self.cbq_handler(self.act_edit_review_reply_text, lambda c: c.data.startswith(f"{cb.EDIT_REVIEW_REPLY_TEXT}:"))
        self.msg_handler(self.edit_review_reply_text,
                         func=lambda m: self.check_state(m.chat.id, m.from_user.id, cb.EDIT_REVIEW_REPLY_TEXT))
        self.msg_handler(self.manual_delivery_text,
                         func=lambda m: self.check_state(m.chat.id, m.from_user.id, cb.MANUAL_AD_TEST))
        self.msg_handler(self.act_ban, commands=["ban"])
        self.msg_handler(self.ban, func=lambda m: self.check_state(m.chat.id, m.from_user.id, cb.BAN))
        self.msg_handler(self.act_unban, commands=["unban"])
        self.msg_handler(self.unban, func=lambda m: self.check_state(m.chat.id, m.from_user.id, cb.UNBAN))
        self.msg_handler(self.send_ban_list, commands=["black_list"])
        self.msg_handler(self.send_logs, commands=["logs"])
        self.msg_handler(self.del_logs, commands=["del_logs"])
        self.msg_handler(self.about, commands=["about"])
        self.msg_handler(self.send_system_info, commands=["sys"])
        self.msg_handler(self.restart_assistant, commands=["restart"])
        self.msg_handler(self.ask_power_off, commands=["power_off"])
        self.cbq_handler(self.send_review_reply_text, lambda c: c.data.startswith(f"{cb.SEND_REVIEW_REPLY_TEXT}:"))

        self.msg_handler(self.send_logs, func=lambda m: m.text == _("kb_logs"))
        self.msg_handler(self.send_settings_menu, func=lambda m: m.text == _("kb_menu"))
        self.msg_handler(self.send_system_info, func=lambda m: m.text == _("kb_sys"))
        self.msg_handler(self.restart_assistant, func=lambda m: m.text == _("kb_restart"))
        self.msg_handler(self.close_keyboard, func=lambda m: m.text == _("kb_hide"))
        self.msg_handler(self.ask_power_off, func=lambda m: m.text == _("kb_poweroff"))
        self.msg_handler(self.open_keyboard, commands=["keyboard"])
        self.cbq_handler(self.act_send_funpay_message, lambda c: c.data.startswith(f"{cb.SEND_FP_MESSAGE}:"))
        self.cbq_handler(self.open_reply_menu, lambda c: c.data.startswith(f"{cb.BACK_TO_REPLY_KB}:"))
        self.cbq_handler(self.extend_new_message_notification, lambda c: c.data.startswith(f"{cb.EXTEND_CHAT}:"))
        self.msg_handler(self.send_funpay_message,
                         func=lambda m: self.check_state(m.chat.id, m.from_user.id, cb.SEND_FP_MESSAGE))
        self.cbq_handler(self.ask_confirm_refund, lambda c: c.data.startswith(f"{cb.REQUEST_REFUND}:"))
        self.cbq_handler(self.cancel_refund, lambda c: c.data.startswith(f"{cb.REFUND_CANCELLED}:"))
        self.cbq_handler(self.refund, lambda c: c.data.startswith(f"{cb.REFUND_CONFIRMED}:"))
        self.cbq_handler(self.open_order_menu, lambda c: c.data.startswith(f"{cb.BACK_TO_ORDER_KB}:"))
        self.cbq_handler(self.open_cp, lambda c: c.data == cb.MAIN)
        self.cbq_handler(self.open_menu_profile, lambda c: c.data == cb.MENU_PROFILE)
        self.cbq_handler(self.open_menu_old_orders, lambda c: c.data == cb.MENU_OLD_ORDERS)
        self.cbq_handler(self.open_deep_settings, lambda c: c.data == cb.DEEP_SETTINGS)
        self.cbq_handler(self.open_analytics_menu, lambda c: c.data == cb.ANALYTICS)
        self.cbq_handler(self.toggle_analytics_section, lambda c: c.data.startswith(f"{cb.ANALYTICS_TOGGLE}:"))
        self.cbq_handler(self.run_analytics_report, lambda c: c.data == cb.ANALYTICS_RUN)
        self.cbq_handler(self.open_cp2, lambda c: c.data == cb.MAIN2)
        self.cbq_handler(self.open_settings_section, lambda c: c.data.startswith(f"{cb.CATEGORY}:"))
        self.cbq_handler(self.switch_param, lambda c: c.data.startswith(f"{cb.SWITCH}:"))
        self.cbq_handler(self.switch_chat_notification, lambda c: c.data.startswith(f"{cb.SWITCH_TG_NOTIFICATIONS}:"))
        self.cbq_handler(self.toggle_group_notifications, lambda c: c.data.startswith(f"{cb.TOGGLE_GROUP_NOTIFICATIONS}:"))
        self.cbq_handler(self.power_off, lambda c: c.data.startswith(f"{cb.SHUT_DOWN}:"))
        self.cbq_handler(self.cancel_power_off, lambda c: c.data == cb.CANCEL_SHUTTING_DOWN)
        self.cbq_handler(self.cancel_action, lambda c: c.data == cb.CLEAR_STATE)
        self.cbq_handler(self.empty_callback, lambda c: c.data == cb.EMPTY)

    def send_private_notification(self, text: str | None,
                                  notification_type: str = helpers.NotificationTypes.other) -> None:
        """Отправляет уведомление только в личные чаты (ID > 0)."""
        for chat_id in self.notification_settings:
            try:
                if int(chat_id) < 0:
                    continue
            except ValueError:
                continue
            if not self.is_notification_enabled(chat_id, notification_type):
                continue
            try:
                self.bot.send_message(chat_id, text, parse_mode="HTML", disable_web_page_preview=True)
            except Exception:
                logger.error(_("log_tg_notification_error", chat_id))
                logger.debug("TRACEBACK", exc_info=True)

    def _send_group_notification(self, text: str | None, keyboard, notification_type: str,
                                 photo: bytes | None, pin: bool, kwargs: dict) -> None:
        """Все уведомления в группу — в личку ничего не уходит."""
        n = helpers.NotificationTypes
        if not self.is_notification_enabled_globally(notification_type):
            return

        if notification_type in (n.review, n.order_confirmed):
            if not self.group_topics.try_route_notification(text, keyboard, notification_type, photo):
                logger.error(
                    "Не удалось отправить уведомление «%s» в системный топик группы.",
                    notification_type,
                )
            return

        if notification_type in (n.new_message, n.bot_start):
            return

        gid = self.group_topics.group_chat_id()
        if not gid:
            return
        try:
            if photo:
                msg = self.bot.send_photo(gid, photo, text, **kwargs)
            else:
                msg = self.bot.send_message(gid, text, **kwargs)
            if pin:
                self.bot.pin_chat_message(gid, msg.message_id)
        except Exception:
            logger.error(_("log_tg_notification_error", gid))
            logger.debug("TRACEBACK", exc_info=True)

    def send_notification(self, text: str | None, keyboard=None,
                          notification_type: str = helpers.NotificationTypes.other, photo: bytes | None = None,
                          pin: bool = False):
        """
        Отправляет сообщение во все чаты для уведомлений из self.notification_settings.

        :param text: текст уведомления.
        :param keyboard: экземпляр клавиатуры.
        :param notification_type: тип уведомления.
        :param photo: фотография (если нужна).
        :param pin: закреплять ли сообщение.
        """
        kwargs = {}
        if keyboard is not None:
            kwargs["reply_markup"] = keyboard

        if self.group_notifications_enabled():
            self._send_group_notification(text, keyboard, notification_type, photo, pin, kwargs)
            return

        for chat_id in self.notification_settings:
            if self._is_group_chat_key(chat_id):
                continue
            if not self.is_notification_enabled(chat_id, notification_type):
                continue

            try:
                if photo:
                    msg = self.bot.send_photo(chat_id, photo, text, **kwargs)
                else:
                    msg = self.bot.send_message(chat_id, text, **kwargs)

                if notification_type == helpers.NotificationTypes.bot_start:
                    self.init_messages.append((msg.chat.id, msg.id))

                if pin:
                    self.bot.pin_chat_message(msg.chat.id, msg.id)
            except Exception:
                logger.error(_("log_tg_notification_error", chat_id))
                logger.debug("TRACEBACK", exc_info=True)

    def add_command_to_menu(self, command: str, help_text: str) -> None:
        """
        Добавляет команду в список команд (в кнопке menu).

        :param command: текст команды.

        :param help_text: текст справки.
        """
        self.commands[command] = help_text

    def setup_commands(self):
        """
        Устанавливает меню команд.
        """
        commands = [BotCommand(f"/{i}", self.commands[i]) for i in self.commands]
        self.bot.set_my_commands(commands)

    def init(self):
        self.__register_handlers()
        logger.info(_("log_tg_initialized"))

    def run(self):
        """
        Запускает поллинг.
        """
        if not self.assistant.setup_mode:
            self.send_notification(_("bot_started"), notification_type=helpers.NotificationTypes.bot_start)
        try:
            self.bot.delete_webhook(drop_pending_updates=True)
            logger.info(_("log_tg_started", self.bot.user.username))
            self.bot.infinity_polling(logger_level=logging.DEBUG, allowed_updates=["message", "callback_query"])
        except:
            logger.error(_("log_tg_update_error"))
            logger.debug("TRACEBACK", exc_info=True)

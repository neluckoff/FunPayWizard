"""
Работа с Telegram-группой (форум) и топиками для чатов FunPay.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import logging
import re
from threading import Lock, Thread

import telebot.apihelper as tg_api

from telebot.types import Message, ForumTopic, InlineKeyboardMarkup as K, InlineKeyboardButton as B

from app.bot import helpers, keyboards
from app.constants import translate as _

if TYPE_CHECKING:
    from app.bot.client import TGBot

logger = logging.getLogger("TGBot.group_topics")

CACHE_PATH = "storage/cache/group_topics.json"
# В Telegram заголовок топика без эмодзи; звезда — иконка темы (icon_custom_emoji_id).
SYSTEM_TOPIC_NAME = "Отзывы и подтверждения заказов"
SYSTEM_TOPIC_ICON_COLOR = 16766590  # запасной цвет, если emoji-иконка недоступна
SYSTEM_TOPIC_ICON_EMOJIS = ("⭐", "🌟", "★", "⭐️")
TOPIC_NAME_MAX_LEN = 128

class GroupTopicsManager:
    @staticmethod
    def _is_system_topic_name(name: str | None) -> bool:
        if not name:
            return False
        stripped = name.strip()
        if stripped == SYSTEM_TOPIC_NAME:
            return True
        normalized = stripped.lstrip("⭐🌟★⭐️ ").strip()
        return normalized == SYSTEM_TOPIC_NAME

    def __init__(self, tg: "TGBot"):
        self.tg = tg
        self._system_topic_lock = Lock()
        self._data = helpers.load_json_cache(CACHE_PATH, {
            "system_topic_id": None,
            "buyer_topics": {},
            "thread_by_id": {},
        })
        self._sync_system_topic_id_from_config()

    @property
    def assistant(self):
        return self.tg.assistant

    def _save(self) -> None:
        helpers.save_json_cache(CACHE_PATH, self._data)

    def _sync_system_topic_id_from_config(self) -> None:
        if self._data.get("system_topic_id"):
            return
        raw = self.assistant.MAIN_CFG["Telegram"].get("systemTopicId", "").strip()
        if not raw:
            return
        try:
            self._data["system_topic_id"] = int(raw)
            self._save()
        except ValueError:
            pass

    def _bind_system_topic(self, thread_id: int) -> None:
        self._data["system_topic_id"] = thread_id
        self._save()
        self.assistant.MAIN_CFG.set("Telegram", "systemTopicId", str(thread_id))
        self.assistant.save_config(self.assistant.MAIN_CFG, "configs/_main.cfg")

    def _clear_system_topic_binding(self) -> None:
        self._data["system_topic_id"] = None
        self._data.pop("pending_pin_thread_id", None)
        self._save()
        if self.assistant.MAIN_CFG.has_option("Telegram", "systemTopicId"):
            self.assistant.MAIN_CFG.set("Telegram", "systemTopicId", "")
            self.assistant.save_config(self.assistant.MAIN_CFG, "configs/_main.cfg")

    @staticmethod
    def _is_topic_missing_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(
            token in msg
            for token in ("thread not found", "topic not found", "message thread not found", "forum topic not found")
        )

    def _get_forum_topic_name(self, chat_id: int, thread_id: int) -> str | None:
        try:
            result = tg_api._make_request(
                self.tg.bot.token,
                "getForumTopic",
                {"chat_id": chat_id, "message_thread_id": thread_id},
                method="post",
            )
            return result.get("name")
        except Exception:
            return None

    def _system_topic_exists(self, chat_id: int, thread_id: int) -> bool:
        try:
            self.tg.bot.send_chat_action(chat_id, "typing", message_thread_id=thread_id)
            return True
        except Exception as exc:
            if self._is_topic_missing_error(exc):
                return False
            name = self._get_forum_topic_name(chat_id, thread_id)
            return self._is_system_topic_name(name)

    def _find_existing_system_topic(self, chat_id: int) -> int | None:
        candidates: list[int] = []
        for source in (
            self._data.get("system_topic_id"),
            self.assistant.MAIN_CFG["Telegram"].get("systemTopicId", "").strip(),
        ):
            if not source:
                continue
            try:
                candidates.append(int(source))
            except (TypeError, ValueError):
                continue

        for raw_tid in self._data.get("thread_by_id", {}):
            try:
                candidates.append(int(raw_tid))
            except (TypeError, ValueError):
                continue

        seen: set[int] = set()
        for tid in candidates:
            if tid in seen:
                continue
            seen.add(tid)
            if self._is_system_topic_name(self._get_forum_topic_name(chat_id, tid)):
                return tid

        for tid in range(2, 51):
            if tid in seen:
                continue
            if self._is_system_topic_name(self._get_forum_topic_name(chat_id, tid)):
                return tid
        return None

    def is_enabled(self) -> bool:
        return self.assistant.MAIN_CFG["Telegram"].getboolean("groupTopicsEnabled")

    def group_chat_id(self) -> int | None:
        raw = self.assistant.MAIN_CFG["Telegram"].get("groupChatId", "").strip()
        if raw:
            try:
                return int(raw)
            except ValueError:
                pass
        cached = self._data.get("group_chat_id")
        return int(cached) if cached else None

    def is_active(self) -> bool:
        return self.is_enabled() and self.group_chat_id() is not None

    def set_enabled(self, enabled: bool) -> None:
        self.assistant.MAIN_CFG["Telegram"]["groupTopicsEnabled"] = "1" if enabled else "0"
        self.assistant.save_config(self.assistant.MAIN_CFG, "configs/_main.cfg")
        if enabled:
            self.ensure_group_notifications()
            Thread(target=self._ensure_system_topic_async, daemon=True).start()

    def _ensure_system_topic_async(self) -> None:
        try:
            self.ensure_system_topic()
        except Exception:
            logger.warning("Не удалось подготовить системный топик в группе.")
            logger.debug("TRACEBACK", exc_info=True)

    def _system_topic_needed(self) -> bool:
        if not self.tg.group_notifications_enabled():
            return False
        n = helpers.NotificationTypes
        return (self.tg.is_notification_enabled_globally(n.review) or
                self.tg.is_notification_enabled_globally(n.order_confirmed))

    def ensure_group_notifications(self) -> None:
        """Удаляет устаревшие настройки уведомлений для ID группы."""
        self.tg._migrate_notification_settings()

    def is_system_notification_enabled(self, notification_type: str) -> bool:
        """Отзывы/подтверждения в системный топик — те же правила, что и для ЛС."""
        if not self.tg.group_notifications_enabled():
            return False
        return self.tg.is_notification_enabled_globally(notification_type)

    def _get_star_icon_emoji_id(self) -> str | None:
        cached = self._data.get("system_topic_icon_emoji_id")
        if cached:
            return str(cached)

        try:
            stickers = self.tg.bot.get_forum_topic_icon_stickers()
        except Exception:
            logger.debug("get_forum_topic_icon_stickers недоступен.", exc_info=True)
            return None

        for emoji in SYSTEM_TOPIC_ICON_EMOJIS:
            for sticker in stickers:
                if getattr(sticker, "emoji", None) == emoji:
                    emoji_id = getattr(sticker, "custom_emoji_id", None)
                    if emoji_id:
                        self._data["system_topic_icon_emoji_id"] = str(emoji_id)
                        self._save()
                        return str(emoji_id)

        for sticker in stickers:
            emoji_id = getattr(sticker, "custom_emoji_id", None)
            sticker_emoji = getattr(sticker, "emoji", "") or ""
            if emoji_id and any(mark in sticker_emoji for mark in ("⭐", "🌟", "★")):
                self._data["system_topic_icon_emoji_id"] = str(emoji_id)
                self._save()
                return str(emoji_id)

        return None

    def _update_system_topic_icon(self, chat_id: int, thread_id: int) -> None:
        emoji_id = self._get_star_icon_emoji_id()
        try:
            if emoji_id:
                self.tg.bot.edit_forum_topic(chat_id, thread_id, SYSTEM_TOPIC_NAME, emoji_id)
            else:
                self.tg.bot.edit_forum_topic(chat_id, thread_id, SYSTEM_TOPIC_NAME)
            logger.debug("Иконка системного топика обновлена (emoji_id=%s).", emoji_id)
        except Exception:
            logger.warning("Не удалось обновить иконку системного топика.")
            logger.debug("TRACEBACK", exc_info=True)

    def _pin_chat_message(self, chat_id: int, message_id: int, message_thread_id: int | None = None) -> bool:
        params = {
            "chat_id": chat_id,
            "message_id": message_id,
            "disable_notification": True,
        }
        if message_thread_id is not None:
            params["message_thread_id"] = message_thread_id
        try:
            tg_api._make_request(self.tg.bot.token, "pinChatMessage", params, method="post")
            return True
        except Exception:
            try:
                self.tg.bot.pin_chat_message(chat_id, message_id, disable_notification=True)
                return True
            except Exception:
                logger.debug("pinChatMessage failed", exc_info=True)
                return False

    def on_forum_topic_created(self, m: Message) -> None:
        """Привязывает системный топик и закрепляет его в списке тем."""
        created = getattr(m, "forum_topic_created", None)
        if not created or not self.is_active() or m.chat.id != self.group_chat_id():
            return
        if not self._is_system_topic_name(created.name):
            return

        thread_id = m.message_thread_id
        if not self._data.get("system_topic_id"):
            self._bind_system_topic(thread_id)
            logger.info(
                "Привязан существующий системный топик «%s» (ID %s).", SYSTEM_TOPIC_NAME, thread_id,
            )

        if not self._data.get("pending_pin_thread_id"):
            return
        if self._pin_chat_message(m.chat.id, m.message_id):
            self._data.pop("pending_pin_thread_id", None)
            self._save()
            logger.info("Системный топик «%s» закреплён в списке тем.", SYSTEM_TOPIC_NAME)

    def _pin_intro_in_topic(self, chat_id: int, thread_id: int) -> None:
        try:
            intro = self.tg.bot.send_message(
                chat_id,
                _("gt_system_topic_intro"),
                message_thread_id=thread_id,
                disable_notification=True,
            )
        except Exception:
            logger.warning("Не удалось отправить приветствие в системный топик.")
            logger.debug("TRACEBACK", exc_info=True)
            return
        if not self._pin_chat_message(chat_id, intro.message_id, thread_id):
            logger.warning("Не удалось закрепить приветствие внутри системного топика.")

    def _finalize_system_topic(self, chat_id: int, thread_id: int) -> None:
        self._data["pending_pin_thread_id"] = thread_id
        self._save()
        self._pin_intro_in_topic(chat_id, thread_id)

    def _create_system_topic(self, chat_id: int) -> None:
        create_kwargs = {"icon_color": SYSTEM_TOPIC_ICON_COLOR}
        star_icon = self._get_star_icon_emoji_id()
        if star_icon:
            create_kwargs["icon_custom_emoji_id"] = star_icon
        topic = self.tg.bot.create_forum_topic(chat_id, SYSTEM_TOPIC_NAME, **create_kwargs)
        thread_id = topic.message_thread_id
        self._bind_system_topic(thread_id)
        self._data["pending_pin_thread_id"] = thread_id
        self._save()
        logger.info("Создан системный топик «%s» (ID %s).", SYSTEM_TOPIC_NAME, thread_id)
        self._finalize_system_topic(chat_id, thread_id)

    def ensure_system_topic(self) -> None:
        if not self.is_active():
            return
        chat_id = self.group_chat_id()
        if not chat_id or not self._system_topic_needed():
            return

        self._sync_system_topic_id_from_config()

        thread_id = self._data.get("system_topic_id")
        if thread_id and self._system_topic_exists(chat_id, thread_id):
            self._bind_system_topic(thread_id)
            self._update_system_topic_icon(chat_id, thread_id)
            return

        if thread_id and not self._system_topic_exists(chat_id, thread_id):
            logger.warning("Сохранённый системный топик (ID %s) не найден — ищу существующий.", thread_id)
            self._clear_system_topic_binding()

        with self._system_topic_lock:
            self._sync_system_topic_id_from_config()
            thread_id = self._data.get("system_topic_id")
            if thread_id and self._system_topic_exists(chat_id, thread_id):
                self._bind_system_topic(thread_id)
                self._update_system_topic_icon(chat_id, thread_id)
                return

            existing = self._find_existing_system_topic(chat_id)
            if existing:
                self._bind_system_topic(existing)
                logger.info(
                    "Найден существующий системный топик «%s» (ID %s), новый не создаю.",
                    SYSTEM_TOPIC_NAME,
                    existing,
                )
                self._update_system_topic_icon(chat_id, existing)
                return

            try:
                self._data["pending_pin_thread_id"] = True
                self._save()
                self._create_system_topic(chat_id)
            except Exception:
                logger.error("Не удалось создать системный топик в группе.")
                logger.debug("TRACEBACK", exc_info=True)

    @staticmethod
    def normalize_group_chat_id(raw: str) -> int | None:
        s = raw.strip().replace(" ", "")
        if not s or not re.fullmatch(r"-?\d+", s):
            return None
        chat_id = int(s)
        if chat_id > 0:
            chat_id = int(f"-100{chat_id}")
        return chat_id

    def link_group_by_id(self, raw: str) -> tuple[bool, str]:
        chat_id = self.normalize_group_chat_id(raw)
        if chat_id is None:
            return False, _("gt_id_invalid")

        try:
            chat = self.tg.bot.get_chat(chat_id)
        except Exception:
            logger.debug("get_chat failed for %s", chat_id, exc_info=True)
            return False, _("gt_chat_not_found")

        if chat.type not in ("supergroup", "group"):
            return False, _("gt_not_a_group")

        is_forum = getattr(chat, "is_forum", False)
        return self.link_group(chat_id, is_forum)

    def link_group(self, chat_id: int, is_forum: bool) -> tuple[bool, str]:
        if not is_forum:
            return False, _("gt_forum_required")

        old_id = self.group_chat_id()
        if old_id and old_id != chat_id:
            self._data = {
                "group_chat_id": chat_id,
                "system_topic_id": None,
                "buyer_topics": {},
                "thread_by_id": {},
            }
            self._clear_system_topic_binding()

        self.assistant.MAIN_CFG.set("Telegram", "groupChatId", str(chat_id))
        self.assistant.save_config(self.assistant.MAIN_CFG, "configs/_main.cfg")
        self._data["group_chat_id"] = chat_id
        if old_id is not None and old_id != chat_id:
            self._clear_system_topic_binding()
        self._save()

        self.assistant.MAIN_CFG.set("Telegram", "groupNotificationsEnabled", "1")
        self.assistant.save_config(self.assistant.MAIN_CFG, "configs/_main.cfg")
        self.ensure_group_notifications()
        Thread(target=self._ensure_system_topic_async, daemon=True).start()
        self.assistant.complete_setup_after_group_link()
        return True, _("gt_linked", chat_id)

    def try_link_from_message(self, m: Message) -> bool:
        if not self.is_enabled():
            return False
        if m.chat.type not in ("supergroup", "group"):
            return False
        if m.from_user.id not in self.tg.authorized_users:
            return False
        if m.from_user.is_bot:
            return False
        if self.group_chat_id() == m.chat.id:
            return False

        is_forum = getattr(m.chat, "is_forum", False)
        ok, text = self.link_group(m.chat.id, is_forum)
        if ok:
            self.tg.bot.send_message(m.chat.id, text)
        else:
            self.tg.bot.send_message(m.from_user.id, text)
        return ok

    def is_buyer_topic(self, thread_id: int | None) -> bool:
        if not thread_id:
            return False
        system_id = self._data.get("system_topic_id")
        if system_id and thread_id == system_id:
            return False
        return str(thread_id) in self._data.get("thread_by_id", {})

    def _topic_title(self, username: str) -> str:
        name = f"👤 {username}"
        if len(name) > TOPIC_NAME_MAX_LEN:
            return name[:TOPIC_NAME_MAX_LEN]
        return name

    def get_buyer_username(self, fp_chat_id: int) -> str | None:
        buyer = self._data.get("buyer_topics", {}).get(str(fp_chat_id))
        return buyer.get("username") if buyer else None

    def refresh_all_template_panels(self) -> None:
        if not self.is_active():
            return
        gid = self.group_chat_id()
        if not gid:
            return
        for key, buyer in self._data.get("buyer_topics", {}).items():
            msg_id = buyer.get("templates_msg_id")
            thread_id = buyer.get("thread_id")
            username = buyer.get("username")
            if not msg_id or not thread_id or not username:
                continue
            try:
                self.tg.bot.edit_message_reply_markup(
                    gid,
                    msg_id,
                    reply_markup=keyboards.buyer_topic_templates(
                        self.assistant, int(key), username, 0,
                    ),
                    message_thread_id=thread_id,
                )
            except Exception:
                logger.debug("Не удалось обновить клавиатуру шаблонов в топике %s.", username, exc_info=True)

    def _ensure_buyer_topic_pin(self, fp_chat_id: int, username: str, thread_id: int) -> None:
        """Закрепляет в топике короткую панель с кнопкой «Шаблоны»."""
        key = str(fp_chat_id)
        buyer = self._data.setdefault("buyer_topics", {}).setdefault(key, {
            "thread_id": thread_id,
            "username": username,
        })
        buyer["thread_id"] = thread_id
        buyer["username"] = username
        gid = self.group_chat_id()
        if not gid:
            return

        text = _("gt_buyer_topic_pin", helpers.escape(username), fp_chat_id)
        markup = keyboards.buyer_topic_bar(self.assistant, fp_chat_id)
        pinned_id = buyer.get("pinned_msg_id")

        if pinned_id:
            try:
                self.tg.bot.edit_message_text(
                    text,
                    gid,
                    pinned_id,
                    message_thread_id=thread_id,
                    reply_markup=markup,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                return
            except Exception:
                logger.debug("Не удалось обновить закреплённую панель в топике %s.", username, exc_info=True)

        try:
            msg = self.tg.bot.send_message(
                gid,
                text,
                message_thread_id=thread_id,
                reply_markup=markup,
                parse_mode="HTML",
                disable_web_page_preview=True,
                disable_notification=True,
            )
            buyer["pinned_msg_id"] = msg.message_id
            self._save()
            if not self._pin_chat_message(gid, msg.message_id, thread_id):
                logger.warning("Не удалось закрепить панель в топике %s.", username)
        except Exception:
            logger.warning("Не удалось отправить панель в топик %s.", username)
            logger.debug("TRACEBACK", exc_info=True)

    def show_templates_picker(self, fp_chat_id: int, username: str, thread_id: int) -> None:
        """Отправляет (или обновляет) сообщение со списком шаблонов по кнопке «Шаблоны»."""
        key = str(fp_chat_id)
        buyer = self._data.setdefault("buyer_topics", {}).setdefault(key, {
            "thread_id": thread_id,
            "username": username,
        })
        markup = keyboards.buyer_topic_templates(self.assistant, fp_chat_id, username, 0)
        gid = self.group_chat_id()
        if not gid:
            return

        picker_id = buyer.get("templates_msg_id")
        if picker_id:
            try:
                self.tg.bot.edit_message_text(
                    _("gt_buyer_templates"),
                    gid,
                    picker_id,
                    message_thread_id=thread_id,
                    reply_markup=markup,
                    parse_mode="HTML",
                )
                return
            except Exception:
                logger.debug("Не удалось обновить список шаблонов — отправлю новый.", exc_info=True)

        try:
            msg = self.tg.bot.send_message(
                gid,
                _("gt_buyer_templates"),
                message_thread_id=thread_id,
                reply_markup=markup,
                parse_mode="HTML",
                disable_notification=True,
            )
            buyer["templates_msg_id"] = msg.message_id
            self._save()
        except Exception:
            logger.warning("Не удалось отправить список шаблонов в топик %s.", username)
            logger.debug("TRACEBACK", exc_info=True)

    def _get_or_create_buyer_topic(self, fp_chat_id: int, username: str) -> int | None:
        key = str(fp_chat_id)
        existing = self._data.get("buyer_topics", {}).get(key)
        if existing:
            thread_id = existing["thread_id"]
            if not existing.get("pinned_msg_id"):
                self._ensure_buyer_topic_pin(fp_chat_id, username, thread_id)
            return thread_id

        gid = self.group_chat_id()
        if not gid:
            return None

        try:
            topic: ForumTopic = self.tg.bot.create_forum_topic(gid, self._topic_title(username))
            thread_id = topic.message_thread_id
        except Exception:
            logger.error("Не удалось создать топик для покупателя %s.", username)
            logger.debug("TRACEBACK", exc_info=True)
            return None

        self._data.setdefault("buyer_topics", {})[key] = {
            "thread_id": thread_id,
            "username": username,
        }
        self._data.setdefault("thread_by_id", {})[str(thread_id)] = key
        self._save()
        logger.info("Создан топик для %s (FunPay chat %s, thread %s).", username, fp_chat_id, thread_id)
        self._ensure_buyer_topic_pin(fp_chat_id, username, thread_id)
        return thread_id

    @staticmethod
    def _stack_has_buyer_command(c, events: list) -> bool:
        for event in events:
            msg = event.message
            if msg.author_id in (0, c.account.id):
                continue
            text = (msg.text or "").strip().lower()
            if text in c.AR_CFG.sections():
                return True
            if text.startswith("!автовыдача"):
                return True
        return False

    @staticmethod
    def forum_topic_link(group_chat_id: int, thread_id: int) -> str:
        raw = str(group_chat_id)
        if raw.startswith("-100"):
            internal = raw[4:]
        else:
            internal = raw.lstrip("-")
        return f"https://t.me/c/{internal}/{thread_id}"

    def open_buyer_topic_for_reply(self, fp_chat_id: int, username: str, admin_user_id: int) -> bool:
        """
        Создаёт топик покупателя при необходимости и отправляет админу ссылку на топик.
        """
        if not self.is_active():
            return False

        thread_id = self._get_or_create_buyer_topic(fp_chat_id, username)
        if not thread_id:
            return False

        gid = self.group_chat_id()
        if not gid:
            return False

        self._ensure_buyer_topic_pin(fp_chat_id, username, thread_id)

        link = self.forum_topic_link(gid, thread_id)
        markup = K().add(B(_("gt_open_topic_btn"), url=link))
        try:
            self.tg.bot.send_message(
                admin_user_id,
                _("gt_topic_opened", helpers.escape(username)),
                reply_markup=markup,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return True
        except Exception:
            logger.error("Не удалось отправить ссылку на топик администратору %s.", admin_user_id)
            logger.debug("TRACEBACK", exc_info=True)
            return False

    def relay_new_message(self, c, fp_chat_id: int, chat_name: str, text: str,
                          events: list) -> bool:
        if not self.is_active():
            return False
        if not self.tg.group_notifications_enabled():
            return False
        if not self.tg.is_notification_enabled_globally(helpers.NotificationTypes.new_message):
            return False
        if not events:
            return False
        if self._stack_has_buyer_command(c, events):
            return False

        has_buyer = any(
            e.message.author_id not in (0, c.account.id) for e in events
        )
        if not has_buyer:
            return False

        thread_id = self._get_or_create_buyer_topic(fp_chat_id, chat_name)
        if not thread_id:
            return False

        header = f"<b>💬 {helpers.escape(chat_name)}</b> · <a href=\"https://funpay.com/chat/?node={fp_chat_id}\">чат</a>\n\n"
        try:
            self.tg.bot.send_message(
                self.group_chat_id(),
                header + text,
                message_thread_id=thread_id,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return True
        except Exception:
            logger.error("Не удалось отправить сообщение в топик покупателя %s.", chat_name)
            logger.debug("TRACEBACK", exc_info=True)
            return False

    def send_system_notification(self, text: str, keyboard=None) -> bool:
        if not self.is_active():
            return False
        self.ensure_system_topic()
        thread_id = self._data.get("system_topic_id")
        if not thread_id:
            return False

        kwargs = {"message_thread_id": thread_id, "parse_mode": "HTML", "disable_web_page_preview": True}
        if keyboard is not None:
            kwargs["reply_markup"] = keyboard
        try:
            self.tg.bot.send_message(self.group_chat_id(), text, **kwargs)
            return True
        except Exception:
            logger.error("Не удалось отправить уведомление в системный топик.")
            logger.debug("TRACEBACK", exc_info=True)
            return False

    def try_route_notification(self, text: str | None, keyboard, notification_type: str,
                               photo: bytes | None = None) -> bool:
        if not self.is_active() or photo:
            return False

        n = helpers.NotificationTypes
        if notification_type not in (n.review, n.order_confirmed):
            return False

        if not self.is_system_notification_enabled(notification_type):
            return False

        return self.send_system_notification(text, keyboard)

    def handle_group_reply(self, m: Message) -> None:
        if not self.is_active():
            return
        if m.chat.id != self.group_chat_id():
            return
        if not m.message_thread_id or not self.is_buyer_topic(m.message_thread_id):
            return
        if m.from_user.is_bot:
            return
        if m.from_user.id not in self.tg.authorized_users:
            return

        fp_key = self._data["thread_by_id"].get(str(m.message_thread_id))
        if not fp_key:
            return

        buyer = self._data["buyer_topics"].get(fp_key)
        if not buyer:
            return

        fp_chat_id = int(fp_key)
        username = buyer["username"]

        def work():
            try:
                if m.content_type == "photo":
                    file_info = self.tg.bot.get_file(m.photo[-1].file_id)
                    file = self.tg.bot.download_file(file_info.file_path)
                    image_id = self.assistant.account.upload_image(file)
                    self.assistant.account.send_message(fp_chat_id, None, username, image_id)
                else:
                    text = (m.text or m.caption or "").strip()
                    if not text or text.startswith("/"):
                        return
                    text = text.replace("$username", username)
                    result = self.assistant.send_message(fp_chat_id, text, username)
                    if not result:
                        self.tg.bot.reply_to(m, _("gt_send_failed"))
                        return
                self.tg.bot.reply_to(m, _("gt_sent"))
            except Exception:
                logger.error("Ошибка отправки ответа из топика на FunPay.")
                logger.debug("TRACEBACK", exc_info=True)
                try:
                    self.tg.bot.reply_to(m, _("gt_send_failed"))
                except Exception:
                    pass

        Thread(target=work, daemon=True).start()

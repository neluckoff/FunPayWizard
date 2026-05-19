"""
Работа с Telegram-группой (форум) и топиками для чатов FunPay.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
import copy
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
CACHE_VERSION = 2
# В Telegram заголовок топика без эмодзи; звезда — иконка темы (icon_custom_emoji_id).
SYSTEM_TOPIC_NAME = "Отзывы и подтверждения заказов"
DEFAULT_GROUP_TOPICS_CACHE = {
    "version": CACHE_VERSION,
    "group_chat_id": None,
    "topics": {
        "system": None,
        "buyers": {},
    },
    "thread_by_id": {},
    "group_status_msg_id": None,
    "system_topic_icon_emoji_id": None,
    "pending_pin_thread_id": None,
}
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
        if normalized == SYSTEM_TOPIC_NAME:
            return True
        lower = normalized.lower()
        return "отзыв" in lower and "подтвержд" in lower

    def __init__(self, tg: "TGBot"):
        self.tg = tg
        self._system_topic_lock = Lock()
        self._buyer_topics_lock = Lock()
        self._startup_status_lock = Lock()
        self._data = helpers.load_json_cache(
            CACHE_PATH, copy.deepcopy(DEFAULT_GROUP_TOPICS_CACHE),
        )
        self._migrate_cache_data()
        self.ensure_group_mode_config()

    @property
    def assistant(self):
        return self.tg.assistant

    def _save(self) -> None:
        self._data["version"] = CACHE_VERSION
        helpers.save_json_cache(CACHE_PATH, self._data)

    def _topics_root(self) -> dict:
        return self._data.setdefault("topics", {"system": None, "buyers": {}})

    def _buyers(self) -> dict:
        return self._topics_root().setdefault("buyers", {})

    def _system_thread_id(self) -> int | None:
        """ID системного топика — только из storage/cache/group_topics.json."""
        system = self._topics_root().get("system")
        if isinstance(system, dict) and system.get("thread_id") is not None:
            try:
                return int(system["thread_id"])
            except (TypeError, ValueError):
                pass
        legacy = self._data.get("system_topic_id")
        if legacy is not None:
            try:
                return int(legacy)
            except (TypeError, ValueError):
                pass
        return None

    def _migrate_cache_data(self) -> None:
        """Перенос старых полей и однократный импорт systemTopicId из _main.cfg в storage."""
        changed = False
        topics = self._topics_root()
        topics.setdefault("buyers", {})

        legacy_buyers = self._data.pop("buyer_topics", None)
        if legacy_buyers:
            topics["buyers"].update(legacy_buyers)
            changed = True

        legacy_sys = self._data.pop("system_topic_id", None)
        if legacy_sys and not topics.get("system"):
            topics["system"] = {
                "thread_id": int(legacy_sys),
                "name": SYSTEM_TOPIC_NAME,
            }
            changed = True

        if not topics.get("system"):
            cfg_raw = self.assistant.MAIN_CFG["Telegram"].get("systemTopicId", "").strip()
            if cfg_raw:
                try:
                    topics["system"] = {
                        "thread_id": int(cfg_raw),
                        "name": SYSTEM_TOPIC_NAME,
                    }
                    changed = True
                    logger.info(
                        "Импортирован systemTopicId=%s из конфига в %s.",
                        cfg_raw, CACHE_PATH,
                    )
                except ValueError:
                    pass

        if self._data.get("version") != CACHE_VERSION:
            self._data["version"] = CACHE_VERSION
            changed = True

        if changed:
            self._save()

    def _bind_system_topic(self, thread_id: int) -> None:
        """Сохраняет ID системного топика в storage (единственный источник правды)."""
        name = SYSTEM_TOPIC_NAME
        gid = self.group_chat_id()
        if gid:
            got = self._get_forum_topic_name(gid, thread_id)
            if got:
                name = got
        self._topics_root()["system"] = {
            "thread_id": int(thread_id),
            "name": name,
        }
        self._data.pop("system_topic_id", None)
        self._save()
        logger.info("Системный топик записан в storage: thread_id=%s.", thread_id)

    def _clear_system_topic_binding(self) -> None:
        self._topics_root()["system"] = None
        self._data.pop("system_topic_id", None)
        self._data.pop("pending_pin_thread_id", None)
        self._save()

    @staticmethod
    def _is_topic_missing_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(
            token in msg
            for token in ("thread not found", "topic not found", "message thread not found", "forum topic not found")
        )

    @staticmethod
    def _is_message_missing_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(
            token in msg
            for token in ("message to edit not found", "message not found", "message_id_invalid", "message can't be found")
        )

    def _get_forum_topic_name(self, chat_id: int, thread_id: int) -> str | None:
        try:
            result = tg_api._make_request(
                self.tg.bot.token,
                "getForumTopic",
                {"chat_id": chat_id, "message_thread_id": thread_id},
                method="post",
            )
            if isinstance(result, dict):
                return result.get("name")
        except Exception:
            logger.debug("getForumTopic failed for thread %s", thread_id, exc_info=True)
        return None

    def _forum_topic_accessible(self, chat_id: int, thread_id: int) -> bool:
        """Топик существует (без проверки названия — для топиков покупателей)."""
        if self._get_forum_topic_name(chat_id, thread_id) is not None:
            return True
        try:
            self.tg.bot.send_chat_action(chat_id, "typing", message_thread_id=thread_id)
            return True
        except Exception as exc:
            return not self._is_topic_missing_error(exc)

    @staticmethod
    def _is_topic_name_taken_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(
            token in msg
            for token in ("already", "exists", "occupied", "duplicate", "same name", "not unique")
        )

    def _scan_system_topic_by_name(self, chat_id: int) -> int | None:
        """Ищет системный топик по заголовку (2…200)."""
        for tid in range(2, 501):
            name = self._get_forum_topic_name(chat_id, tid)
            if self._is_system_topic_name(name):
                return tid
        return None

    def _resolve_system_topic_id(self, chat_id: int) -> int | None:
        """Сначала storage, затем поиск по имени в группе (без сброса storage)."""
        stored = self._system_thread_id()
        if stored:
            return stored
        return self._scan_system_topic_by_name(chat_id)

    def _find_existing_system_topic(self, chat_id: int) -> int | None:
        return self._resolve_system_topic_id(chat_id)

    def ensure_system_topic_if_missing(self) -> None:
        """Создаёт системный топик только если в storage ещё нет ID."""
        if self._system_thread_id():
            return
        self.ensure_system_topic(force=True)

    def ensure_group_mode_config(self) -> None:
        """Группа с топиками всегда включена; уведомления — только в группу."""
        tg = self.assistant.MAIN_CFG["Telegram"]
        changed = False
        if not tg.getboolean("groupTopicsEnabled"):
            tg["groupTopicsEnabled"] = "1"
            changed = True
        if not tg.getboolean("groupNotificationsEnabled"):
            tg["groupNotificationsEnabled"] = "1"
            changed = True
        if changed:
            self.assistant.save_config(self.assistant.MAIN_CFG, "configs/_main.cfg")

    def is_enabled(self) -> bool:
        return True

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
        return self.group_chat_id() is not None

    def set_enabled(self, enabled: bool = True) -> None:
        self.ensure_group_mode_config()
        if not enabled:
            return
        self.ensure_group_notifications()
        Thread(target=self._ensure_system_topic_if_missing_async, daemon=True).start()

    def _ensure_system_topic_if_missing_async(self) -> None:
        try:
            self.ensure_system_topic_if_missing()
        except Exception:
            logger.warning("Не удалось подготовить системный топик в группе.")
            logger.debug("TRACEBACK", exc_info=True)

    def _system_topic_needed(self) -> bool:
        if not self.is_active():
            return False
        n = helpers.NotificationTypes
        return (self.tg.is_notification_enabled_globally(n.review) or
                self.tg.is_notification_enabled_globally(n.order_confirmed))

    def ensure_group_notifications(self) -> None:
        """Удаляет устаревшие настройки уведомлений для ID группы."""
        self.tg._migrate_notification_settings()

    def is_system_notification_enabled(self, notification_type: str) -> bool:
        if not self.is_active():
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
        name = self._get_forum_topic_name(chat_id, thread_id)
        if name is not None and not self._is_system_topic_name(name):
            return

        emoji_id = self._get_star_icon_emoji_id()
        try:
            if emoji_id:
                self.tg.bot.edit_forum_topic(chat_id, thread_id, SYSTEM_TOPIC_NAME, emoji_id)
            elif name != SYSTEM_TOPIC_NAME:
                self.tg.bot.edit_forum_topic(chat_id, thread_id, SYSTEM_TOPIC_NAME)
            logger.debug("Иконка системного топика обновлена (emoji_id=%s).", emoji_id)
        except Exception as exc:
            if "not modified" in str(exc).lower():
                return
            logger.debug("Не удалось обновить иконку системного топика: %s", exc, exc_info=True)

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
            if message_thread_id is None:
                try:
                    self.tg.bot.pin_chat_message(chat_id, message_id, disable_notification=True)
                    return True
                except Exception:
                    pass
            logger.debug("pinChatMessage failed (thread_id=%s).", message_thread_id, exc_info=True)
            return False

    def on_forum_topic_created(self, m: Message) -> None:
        """Привязывает системный топик и закрепляет его в списке тем."""
        created = getattr(m, "forum_topic_created", None)
        if not created or not self.is_active() or m.chat.id != self.group_chat_id():
            return
        if not self._is_system_topic_name(created.name):
            return

        thread_id = m.message_thread_id
        if not self._system_thread_id():
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

    def _create_system_topic(self, chat_id: int) -> int | None:
        star_icon = self._get_star_icon_emoji_id()
        create_attempts: list[dict] = []
        if star_icon:
            create_attempts.append({
                "icon_color": SYSTEM_TOPIC_ICON_COLOR,
                "icon_custom_emoji_id": star_icon,
            })
        create_attempts.append({"icon_color": SYSTEM_TOPIC_ICON_COLOR})
        create_attempts.append({})

        last_error: Exception | None = None
        for create_kwargs in create_attempts:
            try:
                topic: ForumTopic = self.tg.bot.create_forum_topic(
                    chat_id, SYSTEM_TOPIC_NAME, **create_kwargs,
                )
                thread_id = topic.message_thread_id
                self._bind_system_topic(thread_id)
                self._data["pending_pin_thread_id"] = thread_id
                self._save()
                logger.info("Создан системный топик «%s» (ID %s).", SYSTEM_TOPIC_NAME, thread_id)
                self._finalize_system_topic(chat_id, thread_id)
                return thread_id
            except Exception as exc:
                last_error = exc
                if self._is_topic_name_taken_error(exc):
                    found = self._scan_system_topic_by_name(chat_id)
                    if found:
                        self._bind_system_topic(found)
                        logger.info(
                            "Системный топик уже есть (ID %s), привязал без создания.",
                            found,
                        )
                        self._update_system_topic_icon(chat_id, found)
                        return found
                logger.debug(
                    "create_forum_topic не удался (%s): %s",
                    create_kwargs or "default",
                    exc,
                    exc_info=True,
                )

        if last_error:
            logger.error(
                "Не удалось создать системный топик «%s» в группе %s: %s",
                SYSTEM_TOPIC_NAME, chat_id, last_error,
            )
        return None

    def ensure_system_topic(self, force: bool = False) -> None:
        if not self.is_active():
            return
        chat_id = self.group_chat_id()
        if not chat_id or (not force and not self._system_topic_needed()):
            return

        with self._system_topic_lock:
            stored = self._system_thread_id()
            if stored:
                logger.debug("Системный топик из storage: thread_id=%s.", stored)
                if force:
                    self._update_system_topic_icon(chat_id, stored)
                return

            found = self._scan_system_topic_by_name(chat_id)
            if found:
                self._bind_system_topic(found)
                self._update_system_topic_icon(chat_id, found)
                return

            logger.info(
                "В %s нет ID системного топика — создаю «%s» один раз.",
                CACHE_PATH, SYSTEM_TOPIC_NAME,
            )
            self._data["pending_pin_thread_id"] = True
            self._save()
            self._create_system_topic(chat_id)

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
        cached_gid = self._data.get("group_chat_id")
        if old_id and old_id != chat_id:
            self._data = copy.deepcopy(DEFAULT_GROUP_TOPICS_CACHE)
            self._data["group_chat_id"] = chat_id
            self._save()
        elif cached_gid and cached_gid != chat_id:
            self._data = copy.deepcopy(DEFAULT_GROUP_TOPICS_CACHE)
            self._data["group_chat_id"] = chat_id
            self._save()
        else:
            self._data["group_chat_id"] = chat_id
            self._save()

        self.assistant.MAIN_CFG.set("Telegram", "groupChatId", str(chat_id))
        self.assistant.save_config(self.assistant.MAIN_CFG, "configs/_main.cfg")

        self.assistant.MAIN_CFG.set("Telegram", "groupNotificationsEnabled", "1")
        self.assistant.save_config(self.assistant.MAIN_CFG, "configs/_main.cfg")
        self.ensure_group_notifications()
        Thread(target=self._ensure_system_topic_if_missing_async, daemon=True).start()
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
        system_id = self._system_thread_id()
        if system_id and thread_id == system_id:
            return False
        return str(thread_id) in self._data.get("thread_by_id", {})

    def _topic_title(self, username: str) -> str:
        name = f"👤 {username}"
        if len(name) > TOPIC_NAME_MAX_LEN:
            return name[:TOPIC_NAME_MAX_LEN]
        return name

    def _is_buyer_topic_title(self, name: str | None, username: str) -> bool:
        if not name or not username:
            return False
        expected = self._topic_title(username)
        if name == expected:
            return True
        return name.startswith("👤 ") and username in name

    def _register_buyer_topic(self, fp_chat_id: int, username: str, thread_id: int) -> None:
        key = str(fp_chat_id)
        old = self._buyers().get(key, {})
        self._buyers()[key] = {
            "thread_id": thread_id,
            "username": username,
            "pinned_msg_id": old.get("pinned_msg_id"),
            "templates_msg_id": old.get("templates_msg_id"),
        }
        self._data.setdefault("thread_by_id", {})[str(thread_id)] = key
        self._save()

    def _find_buyer_topic_by_username(self, username: str) -> tuple[int, int] | None:
        """Возвращает (fp_chat_id, thread_id) по имени покупателя."""
        gid = self.group_chat_id()
        if not gid:
            return None

        for key, buyer in self._buyers().items():
            if buyer.get("username") != username:
                continue
            thread_id = buyer.get("thread_id")
            if not thread_id:
                continue
            try:
                return int(key), int(thread_id)
            except (TypeError, ValueError):
                return None, int(thread_id)

        for tid in range(2, 501):
            topic_name = self._get_forum_topic_name(gid, tid)
            if topic_name and self._is_buyer_topic_title(topic_name, username):
                for key, buyer in self._buyers().items():
                    if buyer.get("thread_id") == tid:
                        try:
                            return int(key), tid
                        except (TypeError, ValueError):
                            break
                return None, tid
        return None

    def get_buyer_username(self, fp_chat_id: int) -> str | None:
        buyer = self._buyers().get(str(fp_chat_id))
        return buyer.get("username") if buyer else None

    def refresh_all_template_panels(self) -> None:
        if not self.is_active():
            return
        gid = self.group_chat_id()
        if not gid:
            return
        for key, buyer in self._buyers().items():
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
        """Один раз отправляет и закрепляет панель «Шаблоны» в топике покупателя."""
        gid = self.group_chat_id()
        if not gid or gid > 0:
            logger.error("Панель топика: некорректный group_chat_id=%s.", gid)
            return

        text = _("gt_buyer_topic_pin", helpers.escape(username), fp_chat_id)
        markup = keyboards.buyer_topic_bar(self.assistant, fp_chat_id)
        key = str(fp_chat_id)

        with self._buyer_topics_lock:
            buyer = self._buyers().setdefault(key, {
                "thread_id": thread_id,
                "username": username,
            })
            buyer["thread_id"] = thread_id
            buyer["username"] = username
            if buyer.get("pinned_msg_id"):
                return

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
            except Exception:
                logger.warning("Не удалось отправить панель в топик %s.", username)
                logger.debug("TRACEBACK", exc_info=True)
                return

        if buyer.get("pinned_msg_id"):
            if not self._pin_chat_message(gid, buyer["pinned_msg_id"], thread_id):
                logger.warning("Не удалось закрепить панель в топике %s.", username)
            else:
                logger.debug(
                    "Панель закреплена в топике %s (msg %s).",
                    username, buyer["pinned_msg_id"],
                )

    def show_templates_picker(self, fp_chat_id: int, username: str, thread_id: int) -> None:
        """Отправляет (или обновляет) сообщение со списком шаблонов по кнопке «Шаблоны»."""
        key = str(fp_chat_id)
        buyer = self._buyers().setdefault(key, {
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

    def dismiss_templates_picker(self, fp_chat_id: int, message_id: int) -> None:
        """Удаляет сообщение с выбором шаблона и сбрасывает его ID в кэше."""
        gid = self.group_chat_id()
        if gid:
            try:
                self.tg.bot.delete_message(gid, message_id)
            except Exception:
                logger.debug("Не удалось удалить сообщение с шаблонами.", exc_info=True)

        key = str(fp_chat_id)
        buyer = self._buyers().get(key)
        if buyer and buyer.get("templates_msg_id") == message_id:
            buyer.pop("templates_msg_id", None)
            self._save()

    def _get_or_create_buyer_topic(self, fp_chat_id: int, username: str) -> int | None:
        gid = self.group_chat_id()
        if not gid:
            return None

        thread_id: int | None = None
        need_pin = False
        with self._buyer_topics_lock:
            key = str(fp_chat_id)
            existing = self._buyers().get(key)
            if existing and existing.get("thread_id"):
                thread_id = int(existing["thread_id"])
                existing["username"] = username
                need_pin = not existing.get("pinned_msg_id")
                self._save()
            else:
                found = self._find_buyer_topic_by_username(username)
                if found:
                    found_fp, thread_id = found
                    if found_fp is not None and found_fp != fp_chat_id:
                        logger.info(
                            "Найден топик покупателя %s (thread %s), привязываю к чату %s.",
                            username, thread_id, fp_chat_id,
                        )
                    self._register_buyer_topic(fp_chat_id, username, thread_id)
                    need_pin = not self._buyers().get(key, {}).get("pinned_msg_id")
                else:
                    try:
                        topic: ForumTopic = self.tg.bot.create_forum_topic(
                            gid, self._topic_title(username),
                        )
                        thread_id = topic.message_thread_id
                    except Exception:
                        logger.error("Не удалось создать топик для покупателя %s.", username)
                        logger.debug("TRACEBACK", exc_info=True)
                        return None

                    self._register_buyer_topic(fp_chat_id, username, thread_id)
                    need_pin = True
                    logger.info(
                        "Создан топик для %s (FunPay chat %s, thread %s).",
                        username, fp_chat_id, thread_id,
                    )

        if thread_id and need_pin:
            self._ensure_buyer_topic_pin(fp_chat_id, username, thread_id)
        return thread_id

    @staticmethod
    def _stack_has_buyer_command(c, events: list) -> bool:
        """True только если все сообщения покупателя в пачке — команды автовыдачи."""
        buyer_events = [
            ev for ev in events
            if ev.message.author_id not in (0, c.account.id) and not ev.message.by_bot
        ]
        if not buyer_events:
            return False
        for event in buyer_events:
            text = (event.message.text or "").strip().lower()
            if text not in c.AR_CFG.sections() and not text.startswith("!автовыдача"):
                return False
        return True

    @staticmethod
    def _format_buyer_message_plain(event) -> str:
        """Только текст покупателя, без префиксов «Ты / 👤»."""
        msg = event.message
        if msg.text:
            return helpers.escape(msg.text)
        link = msg.image_link or str(msg)
        return f'<a href="{helpers.escape(link)}">{_("photo")}</a>'

    @staticmethod
    def _is_buyer_command(c, event) -> bool:
        text = (event.message.text or "").strip().lower()
        return text in c.AR_CFG.sections() or text.startswith("!автовыдача")

    @staticmethod
    def forum_topic_link(group_chat_id: int, thread_id: int) -> str:
        raw = str(group_chat_id)
        if raw.startswith("-100"):
            internal = raw[4:]
        else:
            internal = raw.lstrip("-")
        return f"https://t.me/c/{internal}/{thread_id}"

    def ensure_buyer_topic_link(self, fp_chat_id: int, username: str) -> str | None:
        """Создаёт/находит топик и возвращает ссылку t.me/c/… для кнопки «Ответить»."""
        return self.open_buyer_topic_for_reply(fp_chat_id, username)

    def open_buyer_topic_for_reply(self, fp_chat_id: int, username: str,
                                  *, ping_text: str | None = None) -> str | None:
        """
        Создаёт/находит топик покупателя в группе.
        Возвращает ссылку на топик. Опционально шлёт пинг-сообщение в топик.
        """
        if not self.is_active():
            return None

        thread_id = self._get_or_create_buyer_topic(fp_chat_id, username)
        if not thread_id:
            return None

        gid = self.group_chat_id()
        if not gid:
            return None

        if ping_text:
            try:
                self.tg.bot.send_message(
                    gid, ping_text,
                    message_thread_id=thread_id,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            except Exception:
                logger.error("Не удалось отправить пинг в топик покупателя %s.", username)
                logger.debug("TRACEBACK", exc_info=True)

        return self.forum_topic_link(gid, thread_id)

    def routes_messages_to_group(self) -> bool:
        """Переписка с покупателями идёт только в группу."""
        return self.is_active()

    def relay_new_message(self, c, fp_chat_id: int, chat_name: str, buyer_events: list) -> bool:
        if not self.is_active():
            return False
        if not self.tg.group_notifications_enabled():
            return False
        if not self.tg.is_notification_enabled_globally(helpers.NotificationTypes.new_message):
            return False
        if not buyer_events:
            return False
        if self._stack_has_buyer_command(c, buyer_events):
            return False

        payloads: list[str] = []
        for ev in buyer_events:
            if self._is_buyer_command(c, ev):
                continue
            body = self._format_buyer_message_plain(ev).strip()
            if body:
                payloads.append(body)
        if not payloads:
            return False

        thread_id = self._get_or_create_buyer_topic(fp_chat_id, chat_name)
        if not thread_id:
            logger.error("Не удалось получить топик покупателя %s (chat %s).", chat_name, fp_chat_id)
            return False

        header = (
            f"<b>💬 {helpers.escape(chat_name)}</b> · "
            f"<a href=\"https://funpay.com/chat/?node={fp_chat_id}\">чат</a>\n\n"
        )
        gid = self.group_chat_id()
        sent_any = False
        for index, body in enumerate(payloads):
            payload = (header + body) if index == 0 else body
            for attempt in range(2):
                try:
                    self.tg.bot.send_message(
                        gid,
                        payload,
                        message_thread_id=thread_id,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                    sent_any = True
                    break
                except Exception:
                    if attempt == 0:
                        key = str(fp_chat_id)
                        buyer = self._buyers().get(key)
                        if buyer and int(buyer.get("thread_id", 0)) == thread_id:
                            self._buyers().pop(key, None)
                            self._data.get("thread_by_id", {}).pop(str(thread_id), None)
                            self._save()
                        found = self._find_buyer_topic_by_username(chat_name)
                        if found:
                            _, thread_id = found
                            self._register_buyer_topic(fp_chat_id, chat_name, thread_id)
                            logger.warning(
                                "Повторная отправка в топик %s для %s (chat %s).",
                                thread_id, chat_name, fp_chat_id,
                            )
                            continue
                        thread_id = self._get_or_create_buyer_topic(fp_chat_id, chat_name)
                        if thread_id:
                            continue
                    logger.error(
                        "Не удалось отправить сообщение в топик покупателя %s.", chat_name,
                    )
                    logger.debug("TRACEBACK", exc_info=True)
                    break
        return sent_any

    def notify_startup_status(self, text: str, *, reset_message: bool = False) -> bool:
        """
        Статус запуска в General группы: сначала «TG запущен», затем правка на «FPW готов».
        reset_message=True — новое сообщение в чат (этап старта TG), иначе правка того же msg.
        """
        if not self.is_active():
            return False
        if not self.tg.is_notification_enabled_globally(helpers.NotificationTypes.bot_start):
            return False
        gid = self.group_chat_id()
        if not gid:
            return False

        with self._startup_status_lock:
            if reset_message:
                self._data["group_status_msg_id"] = None
                self._save()

            msg_id = self._data.get("group_status_msg_id")
            if msg_id:
                try:
                    self.tg.bot.edit_message_text(
                        text, gid, int(msg_id),
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                    return True
                except Exception:
                    logger.debug(
                        "Не удалось обновить статус в группе (msg_id=%s), отправлю новое.",
                        msg_id, exc_info=True,
                    )
                    self._data["group_status_msg_id"] = None
                    self._save()

            try:
                msg = self.tg.bot.send_message(
                    gid, text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                self._data["group_status_msg_id"] = msg.message_id
                self._save()
                return True
            except Exception:
                logger.error("Не удалось отправить статус запуска в группу.")
                logger.debug("TRACEBACK", exc_info=True)
                return False

    def notify_fpw_initialized(self, text: str) -> None:
        """См. notify_startup_status."""
        self.notify_startup_status(text)

    def send_system_notification(self, text: str, keyboard=None) -> bool:
        if not self.is_active():
            return False
        gid = self.group_chat_id()
        if not gid:
            return False

        kwargs = {"parse_mode": "HTML", "disable_web_page_preview": True}
        if keyboard is not None:
            kwargs["reply_markup"] = keyboard

        for attempt in range(2):
            thread_id = self._system_thread_id()
            if not thread_id:
                with self._system_topic_lock:
                    if not self._system_thread_id():
                        self.ensure_system_topic(force=True)
                thread_id = self._system_thread_id()

            if not thread_id:
                logger.error(
                    "Нет ID системного топика в %s (группа %s). Создайте топик вручную или проверьте права бота.",
                    CACHE_PATH, gid,
                )
                return False

            try:
                self.tg.bot.send_message(gid, text, message_thread_id=thread_id, **kwargs)
                return True
            except Exception as exc:
                logger.error(
                    "Не удалось отправить в системный топик thread %s: %s",
                    thread_id, exc,
                )
                logger.debug("TRACEBACK", exc_info=True)
                if attempt == 0 and self._is_topic_missing_error(exc):
                    found = self._scan_system_topic_by_name(gid)
                    if found:
                        self._bind_system_topic(found)
                        continue
                    with self._system_topic_lock:
                        self._clear_system_topic_binding()
                        self._create_system_topic(gid)
                    continue
                return False
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

        buyer = self._buyers().get(fp_key)
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

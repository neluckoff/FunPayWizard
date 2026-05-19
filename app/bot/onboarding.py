"""
Первичная настройка через Telegram-бот.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from telebot.types import Message, CallbackQuery, InlineKeyboardMarkup as K, InlineKeyboardButton as B

import logging

from app.bot import callbacks as cb, helpers, static_assets
from app.constants import translate as _
from app.setup import is_setup_required

logger = logging.getLogger("TGBot")

if TYPE_CHECKING:
    from app.bot.client import TGBot


def _skip_ua_kb() -> K:
    return K().add(B(_("setup_skip_ua"), callback_data=cb.SETUP_SKIP_UA))


class SetupWizard:
    SETUP_STATES = frozenset({cb.SETUP_GOLDEN_KEY, cb.SETUP_USER_AGENT, cb.SETUP_SECRET_KEY})

    def __init__(self, tg: "TGBot"):
        self.tg = tg

    def start(self, m: Message) -> None:
        """Начинает или перезапускает мастер настройки."""
        if m.chat.type != "private":
            return
        self.tg.clear_state(m.chat.id, m.from_user.id)
        self._begin(m)

    def handle_message(self, m: Message) -> None:
        if m.chat.type != "private":
            return

        cmd = (m.text or "").strip().split()[0].split("@")[0] if m.text else ""
        if cmd == "/start":
            self.start(m)
            return

        state = self.tg.get_state(m.chat.id, m.from_user.id)
        if state is None:
            if is_setup_required(self.tg.assistant.MAIN_CFG):
                self._begin(m)
            return

        step = state["state"]
        if step == cb.SETUP_GOLDEN_KEY:
            self._on_golden_key(m)
        elif step == cb.SETUP_USER_AGENT:
            self._on_user_agent(m, skip=False)
        elif step == cb.SETUP_SECRET_KEY:
            self._on_secret_key(m)

    def handle_skip_user_agent(self, c: CallbackQuery) -> None:
        self.tg.bot.answer_callback_query(c.id)
        fake = type("Msg", (), {"chat": c.message.chat, "from_user": c.from_user, "text": ""})()
        self._on_user_agent(fake, skip=True)

    def _begin(self, m: Message) -> None:
        cfg = self.tg.assistant.MAIN_CFG
        golden = cfg["FunPay"]["golden_key"].strip()

        if len(golden) != 32:
            welcome = self.tg._send_photo_screen(
                m.chat.id, static_assets.PREVIEW_IMAGE, _("setup_welcome"),
            )
            state_mid = welcome.message_id if welcome else m.message_id
            self.tg.set_state(m.chat.id, state_mid, m.from_user.id, cb.SETUP_GOLDEN_KEY)
            return

        msg = self.tg.bot.send_message(
            m.chat.id, _("setup_user_agent_prompt"), reply_markup=_skip_ua_kb())
        self.tg.set_state(m.chat.id, msg.message_id, m.from_user.id, cb.SETUP_USER_AGENT)

    def _on_golden_key(self, m: Message) -> None:
        key = (m.text or "").strip()
        if len(key) != 32:
            self.tg.bot.send_message(m.chat.id, _("setup_golden_key_invalid"))
            return

        self.tg.assistant.MAIN_CFG.set("FunPay", "golden_key", key)
        self.tg.assistant.save_config(self.tg.assistant.MAIN_CFG, "configs/_main.cfg")
        self.tg.clear_state(m.chat.id, m.from_user.id)

        msg = self.tg.bot.send_message(
            m.chat.id, _("setup_user_agent_prompt"), reply_markup=_skip_ua_kb())
        self.tg.set_state(m.chat.id, msg.message_id, m.from_user.id, cb.SETUP_USER_AGENT)

    def _on_user_agent(self, m: Message, skip: bool) -> None:
        if not skip:
            ua = (getattr(m, "text", None) or "").strip()
            if ua:
                self.tg.assistant.MAIN_CFG.set("FunPay", "user_agent", ua)
                self.tg.assistant.save_config(self.tg.assistant.MAIN_CFG, "configs/_main.cfg")

        self.tg.clear_state(m.chat.id, m.from_user.id)
        msg = self.tg.bot.send_message(m.chat.id, _("setup_secret_key_prompt"))
        self.tg.set_state(m.chat.id, msg.message_id, m.from_user.id, cb.SETUP_SECRET_KEY)

    def _on_secret_key(self, m: Message) -> None:
        password = (m.text or "").strip()
        if len(password) < 4:
            self.tg.bot.send_message(m.chat.id, _("setup_secret_key_invalid"))
            return

        self.tg.assistant.MAIN_CFG.set("Telegram", "secretKey", password)
        self.tg.assistant.save_config(self.tg.assistant.MAIN_CFG, "configs/_main.cfg")

        user_id = m.from_user.id
        if user_id not in self.tg.authorized_users:
            self.tg.authorized_users.append(user_id)
            helpers.save_authorized_users(self.tg.authorized_users)

        chat_id = str(m.chat.id)
        if chat_id not in self.tg.notification_settings:
            self.tg.notification_settings[chat_id] = {
                helpers.NotificationTypes.ad: 1,
                helpers.NotificationTypes.announcement: 1,
            }
            helpers.save_notification_settings(self.tg.notification_settings)

        self.tg.clear_state(m.chat.id, m.from_user.id, del_msg=False)
        self.tg.group_topics.ensure_group_mode_config()
        self.tg.assistant.awaiting_setup_group_link = True
        self.tg.assistant.setup_notify_chat_id = m.chat.id
        self.tg.bot.send_message(m.chat.id, _("setup_group_link_prompt"))
        self.tg.bot.send_message(m.chat.id, _("setup_gt_instructions"))
        logger.info(
            "Ожидание привязки группы (пользователь %s, ID: %s).",
            m.from_user.username, m.from_user.id,
        )

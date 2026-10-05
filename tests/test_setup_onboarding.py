import unittest
from types import SimpleNamespace

from app.bot.client import TGBot
from app.bot.onboarding import SetupWizard
from app.setup import DEFAULT_CONFIG, create_config_obj, is_group_link_pending


def setup_config(*, golden=True, secret=True, group=False):
    cfg = create_config_obj(DEFAULT_CONFIG)
    cfg["FunPay"]["golden_key"] = "g" * 32 if golden else ""
    cfg["Telegram"]["secretKey"] = "secret" if secret else ""
    cfg["Telegram"]["groupChatId"] = "-1001234567890" if group else ""
    return cfg


class FakeBot:
    def __init__(self):
        self.messages = []

    def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text, kwargs))
        return SimpleNamespace(message_id=len(self.messages))


class SetupStateTests(unittest.TestCase):
    def test_group_link_pending_only_after_previous_steps(self):
        self.assertFalse(is_group_link_pending(setup_config(golden=False)))
        self.assertFalse(is_group_link_pending(setup_config(secret=False)))
        self.assertTrue(is_group_link_pending(setup_config()))
        self.assertFalse(is_group_link_pending(setup_config(group=True)))

    def test_wizard_resumes_at_group_step_after_restart(self):
        assistant = SimpleNamespace(
            MAIN_CFG=setup_config(),
            awaiting_setup_group_link=False,
            setup_notify_chat_id=None,
        )
        bot = FakeBot()
        ensured = []
        tg = SimpleNamespace(
            assistant=assistant,
            bot=bot,
            group_topics=SimpleNamespace(
                ensure_group_mode_config=lambda: ensured.append(True),
            ),
            clear_state=lambda *args, **kwargs: None,
            set_state=lambda *args, **kwargs: self.fail("wizard returned to an earlier step"),
        )
        message = SimpleNamespace(
            message_id=1,
            chat=SimpleNamespace(id=100, type="private"),
            from_user=SimpleNamespace(id=42, username="admin"),
        )

        SetupWizard(tg).start(message)

        self.assertTrue(assistant.awaiting_setup_group_link)
        self.assertEqual(assistant.setup_notify_chat_id, 100)
        self.assertEqual(ensured, [True])
        self.assertEqual(len(bot.messages), 2)


class SetupRoutingTests(unittest.TestCase):
    def make_tg(self, cfg=None):
        tg = object.__new__(TGBot)
        tg.assistant = SimpleNamespace(
            MAIN_CFG=cfg or setup_config(),
            awaiting_setup_group_link=False,
            setup_mode=True,
        )
        tg.authorized_users = [42]
        tg.get_state = lambda *args: None
        return tg

    def test_general_wizard_does_not_intercept_group_id(self):
        tg = self.make_tg()

        self.assertTrue(tg._group_link_setup_active())
        self.assertFalse(tg._setup_active(chat_id=100, user_id=42))

    def test_group_message_can_finish_last_setup_step(self):
        tg = self.make_tg()
        linked = []
        tg.group_topics = SimpleNamespace(
            try_link_from_message=lambda message: linked.append(message) or True,
        )
        message = SimpleNamespace(
            content_type="text",
            chat=SimpleNamespace(type="supergroup"),
            from_user=SimpleNamespace(id=42, is_bot=False),
            message_thread_id=None,
        )

        tg.handle_group_topics(None, message)

        self.assertEqual(linked, [message])

    def test_private_group_id_is_processed_after_restart(self):
        tg = self.make_tg()
        tg.bot = FakeBot()
        linked = []
        tg.group_topics = SimpleNamespace(
            link_group_by_id=lambda raw: (linked.append(raw) or True, "linked"),
        )
        message = SimpleNamespace(
            text="-1001234567890",
            chat=SimpleNamespace(id=100, type="private"),
            from_user=SimpleNamespace(id=42),
        )

        tg.handle_setup_group_id(message)

        self.assertEqual(linked, ["-1001234567890"])
        self.assertEqual(tg.bot.messages[0][1], "linked")

    def test_group_message_is_ignored_before_credentials_are_ready(self):
        tg = self.make_tg(setup_config(secret=False))
        linked = []
        tg.group_topics = SimpleNamespace(
            try_link_from_message=lambda message: linked.append(message) or True,
        )
        message = SimpleNamespace(
            content_type="text",
            chat=SimpleNamespace(type="supergroup"),
            from_user=SimpleNamespace(id=42, is_bot=False),
        )

        tg.handle_group_topics(None, message)

        self.assertEqual(linked, [])


if __name__ == "__main__":
    unittest.main()

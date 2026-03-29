import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeAlias
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, MessageEntityType, ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import GetMe, SendMessage
from aiogram.types import Chat, Message, MessageEntity, Update, User


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bot"

if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

# Tests should not depend on a developer's local .env contents.
os.environ["DEBUG"] = "True"
os.environ["PROJECT_NAME"] = "test_project"
os.environ["TOKEN_BOT"] = "123456:TESTTOKEN"
os.environ["MONGO_URL"] = "mongodb://localhost:27017"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ADMIN_IDS"] = "[101, 202]"
os.environ["BASE_WEBHOOK_URL"] = "https://example.com"


def _build_message(
    *,
    text=None,
    user_id=42,
    username="tester",
    is_bot=False,
    chat_id=None,
    chat_type=ChatType.PRIVATE,
    message_id=1,
    entities=None,
):
    chat_id = user_id if chat_id is None else chat_id
    return Message(
        message_id=message_id,
        date=datetime(2026, 3, 29, 12, 0, tzinfo=UTC),
        chat=Chat(id=chat_id, type=chat_type),
        from_user=User(
            id=user_id,
            is_bot=is_bot,
            first_name="Test User",
            username=username,
        ),
        text=text,
        entities=entities,
    )


SupportedTelegramMethod: TypeAlias = GetMe | SendMessage


@dataclass
class BotAppFixture:
    bot: Bot
    dp: Dispatcher
    storage: MemoryStorage
    telegram_methods: list[SupportedTelegramMethod]


@dataclass
class MiddlewareCollectionDouble:
    insert_one: AsyncMock


@pytest.fixture
def command_update_factory():
    def factory(command, *, payload="", update_id=1, **message_kwargs):
        command_text = f"/{command}"
        text = command_text if not payload else f"{command_text} {payload}"
        entities = [
            MessageEntity(
                type=MessageEntityType.BOT_COMMAND,
                offset=0,
                length=len(command_text),
            )
        ]
        return Update(
            update_id=update_id,
            message=_build_message(
                text=text,
                entities=entities,
                **message_kwargs,
            ),
        )

    return factory


@pytest.fixture
async def bot_app(monkeypatch):
    import importlib
    import loader
    import services.middleware as middleware

    importlib.import_module("handlers")

    storage = MemoryStorage()
    telegram_methods: list[SupportedTelegramMethod] = []
    original_storage = loader.dp.fsm.storage

    async def fake_bot_call(
        self: Bot,
        method: Any,
        _request_timeout: int | None = None,
    ) -> Any:
        if isinstance(method, GetMe):
            telegram_methods.append(method)
            return User(
                id=self.id,
                is_bot=True,
                first_name="Test Bot",
                username="test_bot",
            )

        if isinstance(method, SendMessage):
            telegram_methods.append(method)
            return Message(
                message_id=len(telegram_methods),
                date=datetime.now(UTC),
                chat=Chat(id=method.chat_id, type=ChatType.PRIVATE),
                from_user=User(
                    id=self.id,
                    is_bot=True,
                    first_name="Test Bot",
                    username="test_bot",
                ),
                text=method.text,
            )

        raise AssertionError(
            f"Unexpected Telegram method in test: {type(method).__name__}"
        )

    bot = Bot(
        token=os.environ["TOKEN_BOT"],
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    loader.dp.fsm.storage = storage
    monkeypatch.setattr(Bot, "__call__", fake_bot_call)
    monkeypatch.setattr(
        middleware,
        "_collection",
        MiddlewareCollectionDouble(insert_one=AsyncMock()),
    )

    try:
        yield BotAppFixture(
            bot=bot,
            dp=loader.dp,
            storage=storage,
            telegram_methods=telegram_methods,
        )
    finally:
        loader.dp.fsm.storage = original_storage
        await storage.close()
        await bot.session.close()


@pytest.fixture
def fsm_state_for_user(bot_app):
    def factory(*, user_id, chat_id=None):
        chat_id = user_id if chat_id is None else chat_id
        return FSMContext(
            storage=bot_app.storage,
            key=StorageKey(
                bot_id=bot_app.bot.id,
                chat_id=chat_id,
                user_id=user_id,
            ),
        )

    return factory

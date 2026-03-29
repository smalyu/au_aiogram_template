from datetime import UTC, datetime
from dataclasses import dataclass
from unittest.mock import AsyncMock, Mock, call

from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update, User
from aiogram.types.error_event import ErrorEvent

import handlers.end as end_handler
import handlers.error as error_handler
import handlers.main as main_handler


@dataclass
class BotDouble:
    send_message: AsyncMock


def build_incoming_message(*, text, user_id=42, username="tester", is_bot=False):
    return Message(
        message_id=1,
        date=datetime(2026, 3, 29, 12, 0, tzinfo=UTC),
        chat=Chat(id=user_id, type=ChatType.PRIVATE),
        from_user=User(
            id=user_id,
            is_bot=is_bot,
            first_name="Test User",
            username=username,
        ),
        text=text,
    )


async def test_start_initializes_context_and_logs_first_entry(
    bot_app, command_update_factory, fsm_state_for_user, monkeypatch
):
    log_event = AsyncMock()
    monkeypatch.setattr(main_handler, "log_event", log_event)

    await bot_app.dp.feed_update(
        bot_app.bot,
        command_update_factory(
            "start",
            payload="campaign",
            update_id=1,
            user_id=77,
            username="tester",
        ),
    )

    state = await fsm_state_for_user(user_id=77).get_data()
    send_requests = [
        method for method in bot_app.telegram_methods if isinstance(method, SendMessage)
    ]

    assert state["start_text"] == "campaign"
    assert state["chat_id"] == 77
    assert state["username"] == "tester"
    assert datetime.fromisoformat(state["start_timestamp"])
    assert len(send_requests) == 1
    assert send_requests[0].chat_id == 77
    log_event.assert_awaited_once_with(
        user_id=77,
        event="start",
        start_text="campaign",
        username="tester",
    )


async def test_repeated_start_keeps_first_attribution_and_logs_new_entry(
    bot_app, command_update_factory, fsm_state_for_user, monkeypatch
):
    log_event = AsyncMock()
    monkeypatch.setattr(main_handler, "log_event", log_event)

    await bot_app.dp.feed_update(
        bot_app.bot,
        command_update_factory(
            "start",
            payload="campaign",
            update_id=1,
            user_id=77,
            username="tester",
        ),
    )
    initial_state = await fsm_state_for_user(user_id=77).get_data()

    await bot_app.dp.feed_update(
        bot_app.bot,
        command_update_factory(
            "start",
            payload="second-campaign",
            update_id=2,
            user_id=77,
            username="tester",
            message_id=2,
        ),
    )

    repeated_state = await fsm_state_for_user(user_id=77).get_data()
    send_requests = [
        method for method in bot_app.telegram_methods if isinstance(method, SendMessage)
    ]

    assert repeated_state["start_text"] == "campaign"
    assert repeated_state["start_timestamp"] == initial_state["start_timestamp"]
    assert repeated_state["chat_id"] == initial_state["chat_id"]
    assert repeated_state["username"] == initial_state["username"]
    assert [request.chat_id for request in send_requests] == [77, 77]
    assert log_event.await_args_list == [
        call(
            user_id=77,
            event="start",
            start_text="campaign",
            username="tester",
        ),
        call(
            user_id=77,
            event="start",
            start_text="",
            username="tester",
        ),
    ]


async def test_unexpected_message_continues_notifying_remaining_admins_after_failure(
    monkeypatch,
):
    send_message = AsyncMock(side_effect=[RuntimeError("boom"), None, None])
    forward = AsyncMock()
    log_event = AsyncMock()
    message = build_incoming_message(text="hello", user_id=55, username="tester")

    monkeypatch.setattr(end_handler, "ADMIN_IDS", [11, 22, 33])
    monkeypatch.setattr(
        end_handler,
        "bot",
        BotDouble(send_message=send_message),
    )
    monkeypatch.setattr(end_handler, "log_event", log_event)
    monkeypatch.setattr(Message, "forward", forward)

    await end_handler.unexpected_message(message)

    assert [
        await_call.kwargs["chat_id"] for await_call in send_message.await_args_list
    ] == [
        11,
        22,
        33,
    ]
    assert [await_call.kwargs["chat_id"] for await_call in forward.await_args_list] == [
        22,
        33,
    ]
    log_event.assert_awaited_once_with(
        user_id=55,
        event="unexpected_message",
        has_text=True,
    )


async def test_unexpected_message_ignores_bot_authored_input(monkeypatch):
    send_message = AsyncMock()
    forward = AsyncMock()
    log_event = AsyncMock()
    message = build_incoming_message(
        text="hello",
        user_id=55,
        username="tester",
        is_bot=True,
    )

    monkeypatch.setattr(
        end_handler,
        "bot",
        BotDouble(send_message=send_message),
    )
    monkeypatch.setattr(end_handler, "log_event", log_event)
    monkeypatch.setattr(Message, "forward", forward)

    await end_handler.unexpected_message(message)

    send_message.assert_not_awaited()
    forward.assert_not_awaited()
    log_event.assert_not_awaited()


async def test_errors_handler_skips_stale_callback_errors(monkeypatch):
    send_message = AsyncMock()
    logger_exception = Mock()
    logger_error = Mock()

    monkeypatch.setattr(
        error_handler,
        "bot",
        BotDouble(send_message=send_message),
    )
    monkeypatch.setattr(error_handler.logger, "exception", logger_exception)
    monkeypatch.setattr(error_handler.logger, "error", logger_error)

    event = ErrorEvent(
        update=Update(update_id=1),
        exception=TelegramBadRequest(
            method=SendMessage(chat_id=1, text="ignored"),
            message="query is too old and response timeout expired or query id is invalid",
        ),
    )

    await error_handler.errors_handler(event)

    send_message.assert_not_awaited()
    logger_exception.assert_not_called()
    logger_error.assert_not_called()


async def test_errors_handler_sends_exact_logged_error_to_admins_when_user_dm_fails(
    monkeypatch,
):
    send_message = AsyncMock(side_effect=[RuntimeError("dm failed"), None, None])
    logger_exception = Mock()
    logger_error = Mock()

    monkeypatch.setattr(error_handler, "ADMIN_IDS", [101, 202])
    monkeypatch.setattr(
        error_handler,
        "bot",
        BotDouble(send_message=send_message),
    )
    monkeypatch.setattr(error_handler.logger, "exception", logger_exception)
    monkeypatch.setattr(error_handler.logger, "error", logger_error)

    event = ErrorEvent(
        update=Update(update_id=1, message=build_incoming_message(text="hello")),
        exception=RuntimeError("boom"),
    )

    await error_handler.errors_handler(event)

    logged_error = logger_exception.call_args.args[0]

    assert send_message.await_args_list[0].args == (42, error_handler.messages.error)
    assert send_message.await_args_list[1].args == (101, logged_error)
    assert send_message.await_args_list[2].args == (202, logged_error)
    logger_exception.assert_called_once()
    logger_error.assert_called_once()

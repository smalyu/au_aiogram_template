from datetime import UTC, datetime, timedelta
from dataclasses import dataclass
from unittest.mock import AsyncMock, Mock

import services.tasks as tasks


@dataclass
class BotDouble:
    send_message: AsyncMock


@dataclass
class ScheduledTaskDouble:
    schedule_by_time: AsyncMock


class FrozenDateTime:
    current = datetime(2026, 3, 29, 10, 0, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):
        assert tz is UTC
        return cls.current


async def test_notify_admins_task_continues_after_single_delivery_failure(monkeypatch):
    send_message = AsyncMock(side_effect=[RuntimeError("boom"), None, None])
    logger_exception = Mock()

    monkeypatch.setattr(tasks, "ADMIN_IDS", [11, 22, 33])
    monkeypatch.setattr(tasks, "bot", BotDouble(send_message=send_message))
    monkeypatch.setattr(tasks.logger, "exception", logger_exception)

    await tasks.notify_admins_task("system alert")

    delivered_admin_ids = [
        await_call.args[0] if await_call.args else await_call.kwargs["chat_id"]
        for await_call in send_message.await_args_list
    ]

    assert delivered_admin_ids == [11, 22, 33]
    assert all(
        (await_call.args[1] if len(await_call.args) > 1 else await_call.kwargs["text"])
        == "system alert"
        for await_call in send_message.await_args_list
    )
    logger_exception.assert_called_once()


async def test_send_text_message_task_sends_message_to_requested_chat(monkeypatch):
    send_message = AsyncMock()

    monkeypatch.setattr(tasks, "bot", BotDouble(send_message=send_message))

    await tasks.send_text_message_task(chat_id=7, text="hello")

    send_message.assert_awaited_once_with(7, "hello")


async def test_send_text_message_task_logs_delivery_failures(monkeypatch):
    send_message = AsyncMock(side_effect=RuntimeError("boom"))
    logger_exception = Mock()

    monkeypatch.setattr(tasks, "bot", BotDouble(send_message=send_message))
    monkeypatch.setattr(tasks.logger, "exception", logger_exception)

    await tasks.send_text_message_task(chat_id=7, text="hello")

    send_message.assert_awaited_once_with(7, "hello")
    logger_exception.assert_called_once()


async def test_schedule_text_message_uses_eta_and_redis_schedule_source(monkeypatch):
    schedule_by_time = AsyncMock()
    redis_source = object()

    monkeypatch.setattr(tasks, "datetime", FrozenDateTime)
    monkeypatch.setattr(tasks, "redis_source", redis_source)
    monkeypatch.setattr(
        tasks,
        "send_text_message_task",
        ScheduledTaskDouble(schedule_by_time=schedule_by_time),
    )

    await tasks.schedule_text_message(
        chat_id=7,
        text="hello",
        delay=timedelta(minutes=15),
    )

    schedule_by_time.assert_awaited_once_with(
        redis_source,
        datetime(2026, 3, 29, 10, 15, tzinfo=UTC),
        chat_id=7,
        text="hello",
    )

from unittest.mock import AsyncMock

from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import Chat, ChatMemberUpdated, User
from aiogram.types.chat_member_banned import ChatMemberBanned
from aiogram.types.chat_member_member import ChatMemberMember
from datetime import datetime

import handlers.chat_member as chat_member


def make_chat_member_update(
    chat_type: ChatType, status: ChatMemberStatus, chat_id: int
):
    user = User(id=chat_id, is_bot=False, first_name="Test User")
    old_chat_member = ChatMemberMember(user=user)
    if status == ChatMemberStatus.KICKED:
        new_chat_member = ChatMemberBanned(user=user, until_date=datetime(2026, 3, 29))
    else:
        new_chat_member = ChatMemberMember(user=user)

    return ChatMemberUpdated(
        chat=Chat(id=chat_id, type=chat_type),
        from_user=User(id=999, is_bot=False, first_name="Admin"),
        date=datetime(2026, 3, 29),
        old_chat_member=old_chat_member,
        new_chat_member=new_chat_member,
    )


async def test_private_kicked_member_marks_user_blocked(monkeypatch):
    mark_user_blocked = AsyncMock()
    clear_user_blocked = AsyncMock()
    log_event = AsyncMock()

    monkeypatch.setattr(chat_member, "mark_user_blocked", mark_user_blocked)
    monkeypatch.setattr(chat_member, "clear_user_blocked", clear_user_blocked)
    monkeypatch.setattr(chat_member, "log_event", log_event)

    await chat_member.handle_bot_block(
        make_chat_member_update(ChatType.PRIVATE, ChatMemberStatus.KICKED, 77)
    )

    mark_user_blocked.assert_awaited_once_with(77)
    clear_user_blocked.assert_not_awaited()
    log_event.assert_awaited_once_with(77, "bot_blocked")


async def test_private_member_status_clears_blocked_flag(monkeypatch):
    mark_user_blocked = AsyncMock()
    clear_user_blocked = AsyncMock()
    log_event = AsyncMock()

    monkeypatch.setattr(chat_member, "mark_user_blocked", mark_user_blocked)
    monkeypatch.setattr(chat_member, "clear_user_blocked", clear_user_blocked)
    monkeypatch.setattr(chat_member, "log_event", log_event)

    await chat_member.handle_bot_block(
        make_chat_member_update(ChatType.PRIVATE, ChatMemberStatus.MEMBER, 77)
    )

    clear_user_blocked.assert_awaited_once_with(77)
    mark_user_blocked.assert_not_awaited()
    log_event.assert_awaited_once_with(77, "bot_unblocked")


async def test_non_private_chat_member_update_is_ignored(monkeypatch):
    mark_user_blocked = AsyncMock()
    clear_user_blocked = AsyncMock()
    log_event = AsyncMock()

    monkeypatch.setattr(chat_member, "mark_user_blocked", mark_user_blocked)
    monkeypatch.setattr(chat_member, "clear_user_blocked", clear_user_blocked)
    monkeypatch.setattr(chat_member, "log_event", log_event)

    await chat_member.handle_bot_block(
        make_chat_member_update(ChatType.GROUP, ChatMemberStatus.KICKED, 77)
    )

    mark_user_blocked.assert_not_awaited()
    clear_user_blocked.assert_not_awaited()
    log_event.assert_not_awaited()

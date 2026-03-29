from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

import services.user_status as user_status


class FrozenDateTime:
    current = datetime(2026, 3, 29, 12, 0, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):
        assert tz is UTC
        return cls.current


class FindOneRecorder:
    def __init__(self, *, document=None, error=None):
        self.document = document
        self.error = error
        self.calls = []

    async def find_one(self, filter_, projection=None):
        self.calls.append(
            {
                "filter": filter_,
                "projection": projection,
            }
        )
        if self.error is not None:
            raise self.error
        return self.document


class UpdateRecorder:
    def __init__(self):
        self.calls = []

    async def update_one(self, filter_, update, upsert=False):
        self.calls.append(
            {
                "filter": filter_,
                "update": update,
                "upsert": upsert,
            }
        )


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        (None, False),
        ({"is_blocked": False}, False),
        ({"is_blocked": True}, True),
        ({"is_blocked": 1}, True),
    ],
)
async def test_is_user_blocked_returns_expected_persisted_status(
    monkeypatch, document, expected
):
    collection = FindOneRecorder(document=document)

    monkeypatch.setattr(user_status, "_collection", collection)

    assert await user_status.is_user_blocked(42) is expected
    assert collection.calls[0]["filter"] == {"user_id": 42}


async def test_is_user_blocked_returns_false_when_storage_read_fails(monkeypatch):
    logger_exception = Mock()
    collection = FindOneRecorder(error=RuntimeError("storage unavailable"))

    monkeypatch.setattr(user_status, "_collection", collection)
    monkeypatch.setattr(user_status.logger, "exception", logger_exception)

    assert await user_status.is_user_blocked(42) is False
    logger_exception.assert_called_once()


@pytest.mark.parametrize(
    ("method_name", "expected_flag"),
    [
        ("mark_user_blocked", True),
        ("clear_user_blocked", False),
    ],
)
async def test_block_state_updates_are_upserted_with_current_timestamps(
    monkeypatch, method_name, expected_flag
):
    collection = UpdateRecorder()

    monkeypatch.setattr(user_status, "_collection", collection)
    monkeypatch.setattr(user_status, "datetime", FrozenDateTime)

    await getattr(user_status, method_name)(99)

    update_request = collection.calls[0]

    assert update_request["filter"] == {"user_id": 99}
    assert update_request["upsert"] is True
    assert update_request["update"]["$set"]["is_blocked"] is expected_flag
    assert update_request["update"]["$set"]["updated_at"] == datetime(
        2026,
        3,
        29,
        12,
        0,
        tzinfo=UTC,
    )
    assert update_request["update"]["$setOnInsert"]["created_at"] == datetime(
        2026,
        3,
        29,
        12,
        0,
        tzinfo=UTC,
    )

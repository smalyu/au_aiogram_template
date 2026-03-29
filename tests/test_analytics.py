from datetime import UTC, datetime
from unittest.mock import Mock

from pymongo.asynchronous.collection import AsyncCollection

import services.analytics as analytics


class FrozenDateTime:
    current = datetime(2026, 3, 29, 10, 0, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):
        assert tz is UTC
        return cls.current


class AsyncCursor:
    def __init__(self, docs):
        self._iterator = iter(docs)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class RecordingAnalyticsCollection:
    def __init__(self, *, insert_error=None, find_docs=None, aggregate_docs=None):
        self.insert_error = insert_error
        self.find_docs = find_docs or []
        self.aggregate_docs = aggregate_docs or []
        self.insert_calls = []
        self.find_calls = []
        self.aggregate_calls = []

    async def insert_one(self, document):
        self.insert_calls.append(document)
        if self.insert_error is not None:
            raise self.insert_error

    def find(self, filter_, *, sort, projection):
        self.find_calls.append(
            {
                "filter": filter_,
                "sort": sort,
                "projection": projection,
            }
        )
        return AsyncCursor(self.find_docs)

    async def aggregate(self, pipeline, *, allowDiskUse):
        self.aggregate_calls.append(
            {
                "pipeline": pipeline,
                "allow_disk_use": allowDiskUse,
            }
        )
        return AsyncCursor(self.aggregate_docs)


async def test_log_event_saves_timestamped_event_payload(monkeypatch):
    collection = RecordingAnalyticsCollection()

    monkeypatch.setattr(analytics, "_collection", collection)
    monkeypatch.setattr(analytics, "datetime", FrozenDateTime)

    await analytics.log_event(42, "start", source="campaign")

    assert collection.insert_calls == [
        {
            "user_id": 42,
            "timestamp": datetime(2026, 3, 29, 10, 0, tzinfo=UTC),
            "event": "start",
            "data": {"source": "campaign"},
        }
    ]


async def test_log_event_swallows_storage_failures_and_logs_them(monkeypatch):
    collection = RecordingAnalyticsCollection(insert_error=RuntimeError("storage down"))
    logger_exception = Mock()

    monkeypatch.setattr(analytics, "_collection", collection)
    monkeypatch.setattr(analytics, "datetime", FrozenDateTime)
    monkeypatch.setattr(analytics.logger, "exception", logger_exception)

    await analytics.log_event(42, "start", source="campaign")

    assert len(collection.insert_calls) == 1
    logger_exception.assert_called_once()


async def test_get_events_returns_chronological_normalized_history(monkeypatch):
    collection = RecordingAnalyticsCollection(
        find_docs=[
            {
                "timestamp": datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
                "event": "start",
                "data": {"source": "campaign"},
            },
            {
                "timestamp": datetime(2026, 3, 1, 12, 5, tzinfo=UTC),
                "event": "unexpected_message",
                "data": None,
            },
        ]
    )

    monkeypatch.setattr(analytics, "_collection", collection)

    events = await analytics.get_events(42)

    assert events == [
        {
            "timestamp": "2026-03-01T12:00:00+00:00",
            "event": "start",
            "data": {"source": "campaign"},
        },
        {
            "timestamp": "2026-03-01T12:05:00+00:00",
            "event": "unexpected_message",
            "data": {},
        },
    ]
    assert collection.find_calls[0]["filter"] == {"user_id": 42}


async def test_iter_user_ids_skips_invalid_values_and_normalizes_numbers(monkeypatch):
    collection = RecordingAnalyticsCollection(
        aggregate_docs=[
            {"_id": 10},
            {"_id": "20"},
            {"_id": None},
            {"_id": "not-a-number"},
        ]
    )

    monkeypatch.setattr(analytics, "_collection", collection)

    user_ids = [user_id async for user_id in analytics.iter_user_ids()]

    assert user_ids == [10, 20]


async def test_iter_user_events_skips_users_without_event_history(monkeypatch):
    source_collection = Mock(spec=AsyncCollection)

    async def fake_iter_user_ids(*, collection=None):
        assert collection is not None
        for user_id in (1, 2, 3):
            yield user_id

    async def fake_get_events(user_id, *, collection=None):
        assert collection is not None
        return {
            1: [{"event": "start"}],
            2: [],
            3: [{"event": "bot_blocked"}],
        }[user_id]

    monkeypatch.setattr(analytics, "iter_user_ids", fake_iter_user_ids)
    monkeypatch.setattr(analytics, "get_events", fake_get_events)

    results = [
        item async for item in analytics.iter_user_events(collection=source_collection)
    ]

    assert results == [
        (1, [{"event": "start"}]),
        (3, [{"event": "bot_blocked"}]),
    ]

"""Reference-day checks that do not need LangGraph or a file server."""

from datetime import date, datetime, timezone

import pytest

import ship_agent.runtime.dates as dates


def test_default_reference_day_is_utc(monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz):
            return datetime(2026, 10, 13, 23, 30, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(dates, "datetime", FrozenDatetime)
    assert dates.resolve_reference_date(None, "file_server") == date(2026, 10, 13)
    assert dates.data_timezone("file_server") == "UTC"


def test_explicit_reference_date_is_preserved_for_both_sources():
    anchor = date(2026, 10, 13)
    assert dates.resolve_reference_date(anchor, "file_server") == anchor
    assert dates.resolve_reference_date(anchor, "mock") == anchor
    assert dates.data_timezone("mock") == "Asia/Ho_Chi_Minh"


def test_unknown_source_is_rejected_even_with_an_explicit_date():
    with pytest.raises(ValueError, match="data_source"):
        dates.resolve_reference_date(date(2026, 10, 13), "unknown")

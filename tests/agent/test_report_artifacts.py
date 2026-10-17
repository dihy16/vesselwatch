"""Verify the standalone report data, empty states, and HTML escaping."""

from datetime import date, timedelta
from html.parser import HTMLParser

import pytest

from file_server.carrier_reports import daily_carrier_report
from ship_agent.report_artifacts import render_carrier_artifact


class DailyRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.current = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr" and attrs.get("class") in {"zero", "positive"}:
            self.current = {}
        if self.current is not None:
            if tag == "th":
                self.cell = "date"
            elif tag == "td" and attrs.get("class") == "count":
                self.cell = "count"

    def handle_data(self, data):
        if self.current is not None and self.cell:
            self.current[self.cell] = self.current.get(self.cell, "") + data

    def handle_endtag(self, tag):
        if tag in {"th", "td"}:
            self.cell = None
        if tag == "tr" and self.current is not None:
            self.rows.append(self.current)
            self.current = None


@pytest.mark.parametrize("days,positive", [(1, False), (3, True), (366, True)])
def test_artifact_contains_every_day_and_exact_counts_without_external_assets(days, positive):
    first = date(2026, 1, 1)
    last = first + timedelta(days=days - 1)
    report = daily_carrier_report([
        {"observation_id": "one", "observed_date": first.isoformat(),
         "classification": "aircraft_carrier" if positive else "not_aircraft_carrier"},
    ], first, last)
    html = render_carrier_artifact({**report, "is_mock": False})
    parser = DailyRows()
    parser.feed(html)
    assert parser.rows == [
        {"date": row["date"], "count": str(row["possible_aircraft_carrier_count"])}
        for row in report["daily_stats"]
    ]
    assert html.startswith("<!DOCTYPE html>") and html.endswith("</html>")
    assert "không phải số tàu duy nhất" in html
    assert "Không có lượt dự đoán" in html if not positive else "width:100.00%" in html
    for external in ("<script", "<iframe", "src=", "href=", "url(", "nan%", "inf%"):
        assert external not in html


def test_artifact_marks_mock_data_and_escapes_text():
    from ship_agent.tools import create_tools

    tool = create_tools(date(2026, 10, 14), data_source="mock")[2]
    report = tool.invoke({"observed_from": "2026-10-12", "observed_to": "2026-10-14"})
    report["observed_from"] = '<script>alert("test")</script>'
    html = render_carrier_artifact(report)
    assert "DỮ LIỆU GIẢ LẬP" in html
    assert "&lt;script&gt;" in html and "<script>" not in html
    assert "example.com" not in html and "None" not in html

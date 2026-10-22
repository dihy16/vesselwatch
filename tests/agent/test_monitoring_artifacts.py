"""Source-derived HTML includes scope, monthly rates and honest, escaped review evidence."""

from copy import deepcopy
from html.parser import HTMLParser

import pytest

from file_server.media.carrier_references import load_reference_library
from ship_agent.workflows.carrier_investigation import run_carrier_investigation
from ship_agent.artifacts.monitoring_artifacts import render_monitoring_artifact
from tests.agent.test_false_carrier_evidence import visual
from tests.file_server.test_carrier_references import reference_folder
from tests.integration.test_monitoring_client import payload


def report_packet(tmp_path, *, fail=False):
    data = payload()
    library = load_reference_library(reference_folder(tmp_path))
    def load():
        if fail:
            raise ValueError("private-error-body")
        return library
    review, _ = run_carrier_investigation(data, load_library=load,
                                         create_reviewer=lambda: lambda row, refs: visual(row, refs))
    return {**data, "review": review, "output_format": "html"}


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.text = []
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
    def handle_data(self, value):
        self.text.append(value)


def test_html_has_all_labels_calendar_months_rates_and_two_evidence_priorities(tmp_path):
    packet = report_packet(tmp_path)
    before = deepcopy(packet)
    html = render_monitoring_artifact(packet)
    assert packet == before
    for text in ("2025-01", "2025-02", "2024-12", "31/31", "28/28", "Lượt/ngày",
                 "Chưa có nhãn", "Ưu tiên 1", "Ưu tiên 2", "Chưa đọc ảnh", "Thống kê từng ngày"):
        assert text in html
    assert packet["review"]["flags"][1]["reference_revision"] not in html  # No hidden image payload.
    assert packet["review"]["flags"][1]["visual_review"]["reference_evidence"][0]["reference_id"] in html
    parser = Elements()
    parser.feed(html)
    assert not {tag for tag, attrs in parser.tags} & {"script", "iframe"}
    assert len([tag for tag, attrs in parser.tags if tag == "img"]) == 2


def test_text_and_image_urls_are_escaped_and_no_executable_schemes(tmp_path):
    packet = report_packet(tmp_path)
    packet["area_name"] = '<script>alert("region")</script>'
    packet["review"]["flags"][0]["observation"]["ship_id"] = 'x" onerror="alert(1)<script>bad</script>'
    packet["review"]["flags"][0]["image_url"] = "javascript:alert(1)"
    html = render_monitoring_artifact(packet)
    parser = Elements()
    parser.feed(html)
    assert not any(tag == "script" or "onerror" in attrs for tag, attrs in parser.tags)
    assert "javascript:" not in html and "&lt;script&gt;" in html


def test_review_failure_keeps_statistics_dimension_flags_and_coverage_notice(tmp_path):
    html = render_monitoring_artifact(report_packet(tmp_path, fail=True))
    assert "2025-02" in html and "Ưu tiên 1" in html
    assert "Chưa xử lý hết ứng viên" in html and "reference_review_unavailable" in html
    assert "private-error-body" not in html and "Ưu tiên 2 ·" not in html

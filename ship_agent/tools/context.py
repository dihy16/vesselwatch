"""One source snapshot shared across tool factories and direct chat pixels."""

from dataclasses import dataclass
from datetime import date

from ship_agent.runtime.dates import DataSource


@dataclass
class ToolContext:
    anchor: date
    data_source: DataSource
    observations: list[dict]
    metadata: dict
    demo_snapshot: dict | None = None

    @property
    def is_mock(self):
        return self.data_source == "mock"

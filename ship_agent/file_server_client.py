"""Read every page of UTC observations from the local file server."""

from datetime import date, datetime, timedelta
from typing import Literal
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

from file_server.carrier_reports import daily_carrier_report
from file_server.loader import Observation
from . import config

PAGE_SIZE = 100
REQUEST_TIMEOUT = 30.0


class FileServerError(RuntimeError):
    """The file server could not supply a complete, valid observation result."""


class ObservationPage(BaseModel):
    model_config = ConfigDict(strict=True)
    is_mock: Literal[False]
    timezone: Literal["UTC"]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    observations: list[Observation]


def load_observations(
    observed_from: date | None = None,
    observed_to: date | None = None,
    *,
    base_url: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> list[dict]:
    """Fetch all rows before the caller applies filters or result pagination."""
    params: dict[str, int | str] = {"limit": PAGE_SIZE}
    if observed_from is not None:
        params["observed_from"] = observed_from.isoformat()
    if observed_to is not None:
        params["observed_to"] = observed_to.isoformat()
    observations = []
    seen_ids = set()
    expected_total = None
    try:
        with httpx.Client(
            base_url=(base_url or config.FILE_SERVER_URL).rstrip("/") + "/",
            timeout=REQUEST_TIMEOUT, transport=transport, trust_env=False,
        ) as client:
            while True:
                offset = len(observations)
                response = client.get("observations", params={**params, "offset": offset})
                response.raise_for_status()
                page = ObservationPage.model_validate(response.json())
                if page.offset != offset or page.limit != PAGE_SIZE:
                    raise ValueError("Unexpected page offset or limit.")
                if expected_total is None:
                    expected_total = page.total
                if page.total != expected_total:
                    raise ValueError("Observation total changed between pages.")
                if len(page.observations) > min(PAGE_SIZE, expected_total - offset):
                    raise ValueError("Page exceeds the reported total or limit.")
                if not page.observations and offset < expected_total:
                    raise ValueError("Missing observations before the reported total.")
                for observation in page.observations:
                    day = date.fromisoformat(observation.observed_date)
                    if observation.observed_date != day.isoformat():
                        raise ValueError("Observation date must use YYYY-MM-DD.")
                    captured = datetime.fromisoformat(observation.observed_at.replace("Z", "+00:00"))
                    if (captured.tzinfo is None or captured.utcoffset() != timedelta(0)
                            or captured.date() != day):
                        raise ValueError("Observation date/time must agree in UTC.")
                    if ((observed_from and day < observed_from)
                            or (observed_to and day > observed_to)):
                        raise ValueError("Observation is outside the requested date range.")
                    if not observation.observation_id or observation.observation_id in seen_ids:
                        raise ValueError("Missing or repeated observation ID.")
                    seen_ids.add(observation.observation_id)
                    observations.append(observation.model_dump())
                if len(observations) == expected_total:
                    return observations
    except httpx.TimeoutException as exc:
        raise FileServerError("Hết thời gian chờ file server (30 giây mỗi request).") from exc
    except httpx.HTTPStatusError as exc:
        raise FileServerError(f"File server trả HTTP {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise FileServerError("Không kết nối hoặc đọc được file server; kiểm tra server và FILE_SERVER_URL.") from exc
    except ValueError as exc:
        raise FileServerError("File server trả dữ liệu không hợp lệ hoặc thiếu trang.") from exc


class DailyCarrierStat(BaseModel):
    model_config = ConfigDict(strict=True)
    date: str
    possible_aircraft_carrier_count: int = Field(ge=0)


class DailyCarrierReport(BaseModel):
    model_config = ConfigDict(strict=True)
    is_mock: Literal[False]
    timezone: Literal["UTC"]
    count_unit: Literal["detections"]
    classification: Literal["aircraft_carrier"]
    observed_from: str
    observed_to: str
    total_detections: int = Field(ge=0)
    report_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    daily_stats: list[DailyCarrierStat]
    chart_url: str
    coverage: dict


def load_daily_carrier_report(
    observed_from: date, observed_to: date, *, base_url: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict:
    """Retrieve authoritative counts and a chart URL from the same server snapshot."""
    try:
        with httpx.Client(
            base_url=(base_url or config.FILE_SERVER_URL).rstrip("/") + "/",
            timeout=REQUEST_TIMEOUT, transport=transport, trust_env=False,
        ) as client:
            response = client.get("reports/daily-carriers", params={
                "observed_from": observed_from.isoformat(),
                "observed_to": observed_to.isoformat(),
            })
            response.raise_for_status()
            report = DailyCarrierReport.model_validate(response.json()).model_dump()
        expected_days = daily_carrier_report([], observed_from, observed_to)["daily_stats"]
        if (report["observed_from"] != observed_from.isoformat()
                or report["observed_to"] != observed_to.isoformat()
                or [s["date"] for s in report["daily_stats"]] != [s["date"] for s in expected_days]
                or sum(s["possible_aircraft_carrier_count"] for s in report["daily_stats"])
                != report["total_detections"]):
            raise ValueError("Report dates or total do not agree.")
        url = urlsplit(report["chart_url"])
        query = parse_qs(url.query)
        if (url.scheme not in {"http", "https"} or not url.hostname
                or url.username or url.password or url.fragment
                or not url.path.endswith("/charts/daily-carriers.png")
                or query != {"observed_from": [report["observed_from"]],
                             "observed_to": [report["observed_to"]],
                             "report_id": [report["report_id"]]}):
            raise ValueError("Invalid report chart URL.")
        return report
    except httpx.TimeoutException as exc:
        raise FileServerError("Hết thời gian chờ báo cáo từ file server.") from exc
    except httpx.HTTPStatusError as exc:
        raise FileServerError(f"File server trả HTTP {exc.response.status_code} khi tạo báo cáo.") from exc
    except httpx.HTTPError as exc:
        raise FileServerError("Không truy vấn được báo cáo từ file server.") from exc
    except ValueError as exc:
        raise FileServerError("File server trả báo cáo hoặc URL chart không hợp lệ.") from exc

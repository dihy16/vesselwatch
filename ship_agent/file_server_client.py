"""Read every page of UTC observations from the local file server."""

from datetime import date, datetime, timedelta
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

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

"""Observation payloads shared by API responses and clients."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Position(BaseModel):
    latitude: float | None = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(ge=-180, le=180, allow_inf_nan=False)

    @model_validator(mode="after")
    def paired_coordinates(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Both coordinates must be present or unavailable.")
        return self

class ImageInfo(BaseModel):
    image_id: str
    url: str
    mime_type: str
    caption: str

class Observation(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    observation_id: str
    ship_id: str
    ship_url: str
    observed_date: str
    observed_at: str
    length_m: float | None = Field(gt=0)
    width_m: float | None = Field(gt=0)
    position: Position
    classification: Literal["aircraft_carrier", "not_aircraft_carrier", "unknown"]
    confidence: float | None = Field(ge=0, le=1)
    images: list[ImageInfo]


class ObservationPage(BaseModel):
    is_mock: bool = False
    timezone: str = "UTC"
    total: int
    limit: int
    offset: int
    observations: list[Observation]

"""Map-confirmation request contract."""

from pydantic import BaseModel, ConfigDict

from file_server.schemas.geometry import UserPolygon


class AreaConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    polygon: UserPolygon

"""Validated generic and reference-based visual review contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReviewImageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observation_id: str = Field(min_length=1, description="observation_id chính xác từ search_ships hoặc query_ships_in_area.")
    use_carrier_references: bool = Field(default=False,
        description="True để đối chiếu một observation bất kỳ với toàn bộ bộ mẫu và tổng hợp bằng chứng (BR 13).")
    comparison_observation_id: str | None = Field(default=None, min_length=1,
        description="ID observation thứ hai của cặp khác nhãn, kích thước tương đồng (BR 15); cần use_carrier_references=true.")
    similarity_tolerance_pct: float = Field(default=10, ge=0, le=100,
        description="Sai lệch tối đa CẢ dài và rộng cho cặp, cùng quy tắc câu 12; mặc định 10%.")

    @model_validator(mode="after")
    def reference_pair_mode(self):
        if self.comparison_observation_id is not None:
            if not self.use_carrier_references:
                raise ValueError("So sánh cặp cần use_carrier_references=true.")
            if self.observation_id == self.comparison_observation_id:
                raise ValueError("Cần hai observation_id khác nhau.")
        return self

class VisualReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_quality: Literal["sufficient", "limited", "insufficient"]
    visible_features: list[str] = Field(max_length=10)
    limitations: list[str] = Field(max_length=10)
    assessment: Literal["aircraft_carrier", "not_aircraft_carrier", "unknown"]
    reasoning: str = Field(min_length=1, max_length=3000)

class ReferenceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    similarities: list[str] = Field(default_factory=list, max_length=10)
    differences: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def has_comparison(self):
        if not any(text.strip() for text in self.similarities + self.differences):
            raise ValueError("A reference citation needs an observed similarity or difference.")
        return self

class CarrierReferenceReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_quality: Literal["sufficient", "limited", "insufficient"]
    assessment: Literal["aircraft_carrier", "not_aircraft_carrier", "unknown"]
    visible_features: list[str] = Field(max_length=10)
    reference_evidence: list[ReferenceEvidence] = Field(max_length=100)
    limitations: list[str] = Field(max_length=10)
    reasoning: str = Field(min_length=1, max_length=3000)

    @model_validator(mode="after")
    def grounded_positive(self):
        if (self.image_quality == "sufficient" and self.assessment == "aircraft_carrier"
                and (not any(feature.strip() for feature in self.visible_features)
                     or not any(any(text.strip() for text in item.similarities) for item in self.reference_evidence))):
            raise ValueError("A positive reference match needs visible features and cited similarities.")
        return self

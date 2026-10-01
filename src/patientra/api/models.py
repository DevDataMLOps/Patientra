"""Explicit response contracts; no patient-level fields are accepted."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Dimension = Literal[
    "hospital", "sex", "age_band", "diagnosis_group", "discharge_status",
    "prior_completed_admission_band", "length_of_stay_band", "discharge_year",
    "discharge_month",
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Overall(Contract):
    eligible_admissions: int = Field(ge=11)
    readmitted_admissions: int = Field(ge=11)
    not_readmitted_admissions: int = Field(ge=11)
    readmission_rate_pct: float = Field(ge=0, le=100)
    wilson_95_lower_pct: float = Field(ge=0, le=100)
    wilson_95_upper_pct: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def reconcile(self):
        if self.eligible_admissions != self.readmitted_admissions + self.not_readmitted_admissions:
            raise ValueError("Invalid aggregate reconciliation")
        rate = 100 * self.readmitted_admissions / self.eligible_admissions
        if abs(rate - self.readmission_rate_pct) > 0.00501:
            raise ValueError("Invalid aggregate rate")
        if not self.wilson_95_lower_pct <= self.readmission_rate_pct <= self.wilson_95_upper_pct:
            raise ValueError("Invalid aggregate interval")
        return self


class Breakdown(Overall):
    dimension: Dimension
    category: str = Field(min_length=1, max_length=128)


class BreakdownPage(Contract):
    items: list[Breakdown]
    total: int = Field(ge=0)
    limit: int
    offset: int


class PipelineStatus(Contract):
    release_status: Literal["PASS"]
    freshness_at_publication: Literal["FRESH", "STALE"]
    current_freshness: Literal["FRESH", "STALE"]
    published_at_utc: datetime
    source_run_at_utc: datetime
    current_source_age_seconds: int = Field(ge=0)
    validation_checks_passed: Literal[13]
    analytics_sha256: str
    breakdown_sha256: str
    gate_sha256: str


class DataQuality(Contract):
    gold_rows: int = Field(ge=0)
    eligible_rows: int = Field(ge=0)
    excluded_rows: int = Field(ge=0)
    breakdown_rows: int = Field(ge=0)
    released_breakdown_rows: int = Field(ge=0)
    suppressed_rows: int = Field(ge=0)
    minimum_cell_size: int = Field(ge=11)
    validation_checks_passed: Literal[13]
    row_reconciliation: Literal["PASS"] = "PASS"
    suppression_integrity: Literal["PASS"] = "PASS"
    identity_resolution: Literal["not_assessed", "reviews_unresolved", "reviews_completed"] = "not_assessed"
    unresolved_identity_reviews: int | None = Field(default=None, ge=0)
    unique_master_patients: int | None = Field(default=None, ge=0)
    clinical_accuracy: Literal["not_assessed"] = "not_assessed"


class ReleaseBundle(Contract):
    contract: Literal["phase8-approved-aggregates-v1"] = "phase8-approved-aggregates-v1"
    overall: Overall
    breakdowns: list[Breakdown] = Field(max_length=10000)
    status: PipelineStatus
    quality: DataQuality

    @model_validator(mode="after")
    def reconcile(self):
        quality = self.quality
        if (quality.gold_rows != quality.eligible_rows + quality.excluded_rows
                or quality.eligible_rows != self.overall.eligible_admissions
                or quality.released_breakdown_rows != len(self.breakdowns)
                or quality.breakdown_rows != quality.released_breakdown_rows + quality.suppressed_rows):
            raise ValueError("Invalid bundle reconciliation")
        rows = [self.overall, *self.breakdowns]
        if any(min(row.eligible_admissions, row.readmitted_admissions,
                   row.not_readmitted_admissions) < quality.minimum_cell_size for row in rows):
            raise ValueError("Invalid bundle disclosure threshold")
        keys = [(row.dimension, row.category) for row in self.breakdowns]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate released aggregate")
        pending = quality.unresolved_identity_reviews
        if quality.identity_resolution == "not_assessed":
            if pending is not None or quality.unique_master_patients is not None:
                raise ValueError("Unassessed identity metadata")
        elif (pending is None or quality.unique_master_patients is None
              or (quality.identity_resolution == "reviews_unresolved" and pending == 0)
              or (quality.identity_resolution == "reviews_completed" and pending != 0)):
            raise ValueError("Invalid identity review metadata")
        return self

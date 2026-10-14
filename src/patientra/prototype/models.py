"""Explicit aggregate-only prototype contract; unknown fields fail closed."""
from datetime import datetime
from typing import Literal
from pydantic import Field, model_validator
from patientra.api.models import Contract


class StageCounts(Contract):
    patients: int = Field(ge=0)
    admissions: int = Field(ge=0)
    lab_results: int = Field(ge=0)


class Check(Contract):
    check: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    status: Literal["PASS"]


class Metrics(Contract):
    roc_auc: float = Field(ge=0, le=1)
    average_precision: float = Field(ge=0, le=1)
    brier_score: float = Field(ge=0, le=1)
    balanced_accuracy_at_0_5: float = Field(ge=0, le=1)
    log_loss: float = Field(ge=0)


class Split(Contract):
    cutoff_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    label_embargo_days: Literal[30]
    shared_master_patients: Literal[0]
    train_admissions: int = Field(ge=22)
    test_admissions: int = Field(ge=22)
    train_readmissions: int = Field(ge=11)
    test_readmissions: int = Field(ge=11)
    pending_identity_excluded_admissions: int = Field(ge=0)

    @model_validator(mode="after")
    def classes_supported(self):
        if min(self.train_admissions - self.train_readmissions,
               self.test_admissions - self.test_readmissions) < 11:
            raise ValueError("Each outcome class requires at least 11 admissions")
        return self


class MLDemonstration(Contract):
    release_status: Literal["DEMONSTRATION_ONLY"]
    clinical_accuracy: Literal["NOT_ASSESSED"]
    model_artifact_exported: Literal[False]
    individual_predictions_exported: Literal[False]
    split: Split
    logistic_regression: Metrics
    training_prevalence_baseline: Metrics
    technical_checks: list[Check] = Field(min_length=8, max_length=8)


class DemoEvidence(Contract):
    contract: Literal["patientra-synthetic-prototype-v1"]
    data_mode: Literal["SYNTHETIC_ONLY"]
    run_id: str = Field(pattern=r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    created_at_utc: datetime
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bronze: StageCounts
    silver: StageCounts
    quarantine: StageCounts
    gold_rows: int = Field(ge=0)
    master_patients: int = Field(ge=0)
    unresolved_identity_reviews: int = Field(ge=0)
    validation_checks: list[Check] = Field(min_length=13, max_length=13)
    ml: MLDemonstration

    @model_validator(mode="after")
    def reconcile(self):
        for dataset in ("patients", "admissions", "lab_results"):
            if getattr(self.bronze, dataset) != getattr(self.silver, dataset) + getattr(self.quarantine, dataset):
                raise ValueError("Bronze/Silver/quarantine counts do not reconcile")
        if self.gold_rows != self.silver.admissions:
            raise ValueError("Gold grain does not reconcile")
        for checks in (self.validation_checks, self.ml.technical_checks):
            if len({check.check for check in checks}) != len(checks):
                raise ValueError("Duplicate checks")
        return self

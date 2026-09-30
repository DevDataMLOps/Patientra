import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from patientra.ingestion.ingest import LINEAGE_COLUMNS
from patientra.matching import IdentityError, resolve_identities
from patientra.matching.identity import REVIEW_DECISION_FIELDS
from patientra.transformations.silver import PATIENT_COLUMNS


KEY = b"phase-3-test-key-that-is-at-least-32-bytes"
FIXED_TIME = datetime(2026, 1, 15, 12, 30, tzinfo=timezone.utc)


def _patient(
    patient_id: str,
    source: str,
    first: str,
    last: str,
    dob: str,
    sex: str,
    phone: str,
    state: str,
    row_number: int,
) -> dict[str, str]:
    return {
        "patient_id": patient_id,
        "source_system": source,
        "first_name": first,
        "last_name": last,
        "date_of_birth": dob,
        "sex": sex,
        "phone": phone,
        "state": state,
        "_source_system": "Lakeside Health Network",
        "_source_file": "patients.csv",
        "_source_row_number": str(row_number),
        "_source_sha256": "a" * 64,
        "_ingested_at_utc": "2026-01-01T00:00:00Z",
        "_ingestion_run_id": "00000000-0000-4000-8000-000000000001",
    }


def _write_patients(path: Path, rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=[*PATIENT_COLUMNS, *LINEAGE_COLUMNS], lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


def _read(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _base_rows() -> list[dict[str, str]]:
    return [
        _patient(
            "LG-000001", "LG", "SYNTHETIC Alice", "Smith", "1980-01-02", "F",
            "08012345678", "AA", 2,
        ),
        _patient(
            "RS00001", "RS", "SYNTHETIC Alicia", "Smith", "1980-01-02", "F",
            "+2348012345678", "AA", 3,
        ),
        _patient(
            "LG-000002", "LG", "SYNTHETIC Bob", "Jones", "1990-05-10", "M",
            "08022222222", "BB", 4,
        ),
        _patient(
            "RS00002", "RS", "SYNTHETIC Bob", "Jones", "1990-08-20", "M",
            "08033333333", "BB", 5,
        ),
        _patient(
            "LG-000003", "LG", "SYNTHETIC Carol", "Lee", "1975-03-04", "F",
            "08044444444", "CC", 6,
        ),
    ]


def test_auto_match_review_queue_master_and_privacy(tmp_path: Path) -> None:
    source = _write_patients(tmp_path / "patients.silver.csv", _base_rows())
    result = resolve_identities(
        source,
        tmp_path / "matching",
        KEY,
        run_id="00000000-0000-4000-8000-000000000099",
        created_at=FIXED_TIME,
    )

    assert result.input_patients == 5
    assert result.auto_matches == 1
    assert result.review_candidates == 1
    assert result.review_status_counts == {"PENDING": 1}
    assert result.unique_master_patients == 4
    assert result.linked_source_rows == 2
    assert result.review_pending_source_rows == 2

    master = _read(result.patient_master_path)
    auto_rows = [row for row in master if row["link_status"] == "AUTO_MATCHED"]
    assert len(auto_rows) == 2
    assert len({row["master_patient_id"] for row in auto_rows}) == 1
    queue = _read(result.review_queue_path)
    assert queue[0]["review_status"] == "PENDING"
    assert "PHONE_DIFFERS" in queue[0]["conflict_codes"]
    assert "BIRTH_YEAR_EXACT" in queue[0]["evidence_codes"]

    aggregate = Path(result.audit_path).read_text(encoding="utf-8")
    for marker in (
        "LG-000001", "RS00001", "SYNTHETIC Alice", "08012345678"
    ):
        assert marker not in aggregate

    repeated = resolve_identities(
        source,
        tmp_path / "matching-repeat",
        KEY,
        run_id="00000000-0000-4000-8000-000000000100",
        created_at=FIXED_TIME,
    )
    assert _read(result.patient_master_path) == _read(repeated.patient_master_path)


def test_human_acceptance_updates_master_with_provenance(tmp_path: Path) -> None:
    source = _write_patients(tmp_path / "patients.silver.csv", _base_rows())
    initial = resolve_identities(source, tmp_path / "initial", KEY)
    review_case_id = _read(initial.review_queue_path)[0]["review_case_id"]
    decisions = tmp_path / "review_decisions.csv"
    with decisions.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=REVIEW_DECISION_FIELDS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerow(
            {
                "review_case_id": review_case_id,
                "decision": "ACCEPT",
                "reviewer_id": "SYNTHETIC-REVIEWER",
                "reviewed_at_utc": "2026-01-15T13:00:00Z",
                "review_notes": "Synthetic test decision",
            }
        )

    result = resolve_identities(
        source,
        tmp_path / "accepted",
        KEY,
        review_decisions=decisions,
    )

    assert result.human_accepted_matches == 1
    assert result.unique_master_patients == 3
    assert result.review_status_counts == {"ACCEPTED": 1}
    master = _read(result.patient_master_path)
    assert len([row for row in master if row["link_status"] == "HUMAN_MATCHED"]) == 2
    decisions_output = _read(result.match_decisions_path)
    human = [row for row in decisions_output if row["decision_source"] == "HUMAN_REVIEW"]
    assert human[0]["reviewer_id"] == "SYNTHETIC-REVIEWER"


def test_nonunique_phone_is_not_automatically_merged(tmp_path: Path) -> None:
    rows = [
        _patient("LG-000001", "LG", "SYNTHETIC A", "Same", "1980-01-01", "F", "08012345678", "AA", 2),
        _patient("LG-000002", "LG", "SYNTHETIC B", "Same", "1980-01-01", "F", "08012345678", "AA", 3),
        _patient("RS00001", "RS", "SYNTHETIC A", "Same", "1980-01-01", "F", "+2348012345678", "AA", 4),
    ]
    source = _write_patients(tmp_path / "patients.silver.csv", rows)
    result = resolve_identities(source, tmp_path / "matching", KEY)

    assert result.auto_matches == 0
    assert result.review_candidates == 2
    assert result.unique_master_patients == 3
    assert all(
        "PHONE_NOT_UNIQUE" in row["conflict_codes"]
        for row in _read(result.review_queue_path)
    )


def test_conflicting_human_acceptances_fail_one_to_one_constraint(tmp_path: Path) -> None:
    rows = [
        _patient("LG-000001", "LG", "SYNTHETIC A", "Same", "1980-01-01", "F", "08011111111", "AA", 2),
        _patient("RS00001", "RS", "SYNTHETIC A", "Same", "1980-02-01", "F", "08022222222", "AA", 3),
        _patient("RS00002", "RS", "SYNTHETIC A", "Same", "1980-03-01", "F", "08033333333", "AA", 4),
    ]
    source = _write_patients(tmp_path / "patients.silver.csv", rows)
    initial = resolve_identities(source, tmp_path / "initial", KEY)
    cases = _read(initial.review_queue_path)
    decisions = tmp_path / "review_decisions.csv"
    with decisions.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=REVIEW_DECISION_FIELDS, lineterminator="\n"
        )
        writer.writeheader()
        for index, case in enumerate(cases, start=1):
            writer.writerow(
                {
                    "review_case_id": case["review_case_id"],
                    "decision": "ACCEPT",
                    "reviewer_id": f"SYNTHETIC-REVIEWER-{index}",
                    "reviewed_at_utc": "2026-01-15T13:00:00Z",
                    "review_notes": "Synthetic test decision",
                }
            )

    with pytest.raises(IdentityError, match="one-to-one"):
        resolve_identities(
            source,
            tmp_path / "conflict",
            KEY,
            review_decisions=decisions,
        )


def test_short_key_and_schema_drift_fail_closed(tmp_path: Path) -> None:
    source = _write_patients(tmp_path / "patients.silver.csv", _base_rows())
    with pytest.raises(IdentityError, match="32 bytes"):
        resolve_identities(source, tmp_path / "short-key", b"short")

    text = source.read_text(encoding="utf-8")
    source.write_text(text.replace("patient_id,", "unexpected,patient_id,", 1), encoding="utf-8")
    with pytest.raises(IdentityError, match="schema drift"):
        resolve_identities(source, tmp_path / "schema", KEY)

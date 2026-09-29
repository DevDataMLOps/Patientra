import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from patientra.ingestion import IngestionError, ingest_csv
from patientra.ingestion.ingest import LINEAGE_COLUMNS


FIXTURES = Path(__file__).parent / "fixtures"
FIXED_TIME = datetime(2026, 1, 15, 12, 30, tzinfo=timezone.utc)
FIXED_RUN_ID = "00000000-0000-4000-8000-000000000001"


def read_csv(path: str | Path) -> list[list[str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def test_preserves_raw_strings_and_adds_lineage(tmp_path: Path) -> None:
    source = FIXTURES / "lakeside" / "patients.csv"
    result = ingest_csv(
        source,
        "Lakeside General Hospital",
        tmp_path / "bronze",
        tmp_path / "quarantine",
        run_id=FIXED_RUN_ID,
        ingested_at=FIXED_TIME,
    )

    rows = read_csv(result.bronze_path)
    assert rows[0] == ["patient_id", "date_of_birth", "sex", "full_name", *LINEAGE_COLUMNS]
    assert rows[1][:4] == ["000123", "03/04/26", "F", "SYNTHETIC Alice Example"]
    assert rows[2][:4] == ["R-009", "1990-12-31", "1", "SYNTHETIC Bob Example"]
    assert rows[1][-6:] == [
        "Lakeside General Hospital",
        "patients.csv",
        "2",
        result.source_sha256,
        "2026-01-15T12:30:00Z",
        FIXED_RUN_ID,
    ]
    assert result.accepted_rows == 2
    assert result.quarantined_rows == 0
    assert result.quarantine_path is None
    assert result.source_column_count == 4
    assert result.sensitive_column_count_detected == 2
    manifest_text = Path(result.manifest_path).read_text(encoding="utf-8")
    assert "patient_id" not in manifest_text
    assert "full_name" not in manifest_text


def test_quarantines_rows_with_wrong_field_counts(tmp_path: Path) -> None:
    result = ingest_csv(
        FIXTURES / "riverside" / "laboratory_results_malformed.csv",
        "Riverside Specialist Hospital",
        tmp_path / "bronze",
        tmp_path / "quarantine",
        run_id=FIXED_RUN_ID,
        ingested_at=FIXED_TIME,
    )

    assert result.accepted_rows == 1
    assert result.quarantined_rows == 2
    quarantine_rows = read_csv(result.quarantine_path)
    assert quarantine_rows[1][-1] == "too_few_fields"
    assert quarantine_rows[2][-1] == "too_many_fields"
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["accepted_rows"] == 1
    assert manifest["quarantined_rows"] == 2


def test_rejects_reserved_metadata_column(tmp_path: Path) -> None:
    source = tmp_path / "reserved.csv"
    source.write_text("patient_id,_source_file\n001,x.csv\n", encoding="utf-8")

    with pytest.raises(IngestionError, match="reserved"):
        ingest_csv(source, "Lakeside", tmp_path / "bronze", tmp_path / "quarantine")


def test_rejects_duplicate_headers_without_leaving_outputs(tmp_path: Path) -> None:
    source = tmp_path / "duplicate.csv"
    source.write_text("id,id\n1,2\n", encoding="utf-8")

    with pytest.raises(IngestionError, match="duplicate"):
        ingest_csv(source, "Lakeside", tmp_path / "bronze", tmp_path / "quarantine")
    assert not list((tmp_path / "bronze").rglob("*.csv")) if (tmp_path / "bronze").exists() else True


def test_refuses_to_overwrite_existing_outputs(tmp_path: Path) -> None:
    source = FIXTURES / "lakeside" / "patients.csv"
    ingest_csv(source, "Lakeside", tmp_path / "bronze", tmp_path / "quarantine")

    with pytest.raises(IngestionError, match="already exists"):
        ingest_csv(source, "Lakeside", tmp_path / "bronze", tmp_path / "quarantine")


def test_errors_and_logs_do_not_contain_bad_row_values(tmp_path: Path, caplog) -> None:
    source = tmp_path / "bad.csv"
    secret_marker = "SYNTHETIC-SECRET-MARKER"
    source.write_bytes(b"id,name\n1," + secret_marker.encode() + b"\xff\n")

    with pytest.raises(IngestionError) as error:
        ingest_csv(source, "Lakeside", tmp_path / "bronze", tmp_path / "quarantine")
    assert secret_marker not in str(error.value)
    assert secret_marker not in caplog.text


def test_configurable_delimiter_and_quoted_content(tmp_path: Path) -> None:
    source = tmp_path / "quoted.csv"
    source.write_bytes(
        b'id;note\n"0007";"SYNTHETIC value; with delimiter and\nnewline"\n'
    )

    result = ingest_csv(
        source,
        "Riverside",
        tmp_path / "bronze",
        tmp_path / "quarantine",
        delimiter=";",
    )

    rows = read_csv(result.bronze_path)
    assert rows[1][:2] == ["0007", "SYNTHETIC value; with delimiter and\nnewline"]


def test_unterminated_quote_fails_without_partial_outputs(tmp_path: Path) -> None:
    source = tmp_path / "unterminated.csv"
    source.write_text('id,note\n1,"SYNTHETIC unterminated\n', encoding="utf-8")

    with pytest.raises(IngestionError, match="no row values"):
        ingest_csv(source, "Lakeside", tmp_path / "bronze", tmp_path / "quarantine")

    bronze_files = (
        list((tmp_path / "bronze").rglob("*"))
        if (tmp_path / "bronze").exists()
        else []
    )
    quarantine_files = (
        list((tmp_path / "quarantine").rglob("*"))
        if (tmp_path / "quarantine").exists()
        else []
    )
    assert not [path for path in bronze_files + quarantine_files if path.is_file()]

"""Generic, privacy-conscious CSV-to-Bronze ingestion.

Bronze deliberately does not clean or reinterpret source values. All source cells are
read and written as strings. Structural problems are quarantined for later review.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

LOGGER = logging.getLogger("patientra.ingestion")

LINEAGE_COLUMNS = (
    "_source_system",
    "_source_file",
    "_source_row_number",
    "_source_sha256",
    "_ingested_at_utc",
    "_ingestion_run_id",
)
QUARANTINE_REASON_COLUMN = "_quarantine_reason"
SUPPORTED_DELIMITERS = {",", ";", "\t", "|"}
SENSITIVE_NAME_TOKENS = {
    "address",
    "dob",
    "email",
    "first_name",
    "full_name",
    "last_name",
    "medical_record_number",
    "mrn",
    "name",
    "national_id",
    "patient_id",
    "phone",
    "postcode",
    "social_security_number",
    "ssn",
}


class IngestionError(RuntimeError):
    """Raised when a file cannot safely satisfy the Bronze contract."""


@dataclass(frozen=True)
class IngestionResult:
    """Metadata-only result. It intentionally contains no patient values."""

    source_system: str
    source_file: str
    source_sha256: str
    ingestion_run_id: str
    ingested_at_utc: str
    accepted_rows: int
    quarantined_rows: int
    source_column_count: int
    source_schema_sha256: str
    sensitive_column_count_detected: int
    bronze_path: str
    quarantine_path: str | None
    manifest_path: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _schema_sha256(headers: Sequence[str]) -> str:
    """Hash the ordered header without copying possible bad-header values to metadata."""
    serialized = json.dumps(list(headers), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    if not slug:
        raise IngestionError("Source system must contain at least one letter or digit.")
    return slug


def _sensitive_columns(headers: Sequence[str]) -> tuple[str, ...]:
    found: list[str] = []
    for header in headers:
        normalized = re.sub(r"[^a-z0-9]+", "_", header.strip().lower()).strip("_")
        if normalized in SENSITIVE_NAME_TOKENS:
            found.append(header)
    return tuple(found)


def _validate_header(header: Sequence[str]) -> tuple[str, ...]:
    if not header:
        raise IngestionError("The CSV is empty or has no header row.")
    if any(column == "" for column in header):
        raise IngestionError("The CSV header contains an empty column name.")
    if len(set(header)) != len(header):
        raise IngestionError("The CSV header contains duplicate column names.")
    reserved = set(LINEAGE_COLUMNS) | {QUARANTINE_REASON_COLUMN}
    collisions = sorted(reserved.intersection(header))
    if collisions:
        raise IngestionError(
            "The source header uses reserved PATIENTRA metadata column name(s): "
            + ", ".join(collisions)
        )
    return tuple(header)


def _atomic_csv_writer(target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        prefix=".tmp-",
        suffix=".tmp",
        dir=target.parent,
        delete=False,
    )
    return handle, Path(handle.name)


def _restrict_permissions(path: Path) -> None:
    """Best-effort owner-only permissions on platforms that support chmod semantics."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        LOGGER.warning("Could not tighten permissions for an output file.")


def _write_json_atomic(target: Path, payload: dict[str, object]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=".tmp-",
        suffix=".tmp",
        dir=target.parent,
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.replace(target)
        _restrict_permissions(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def ingest_csv(
    input_path: str | Path,
    source_system: str,
    bronze_dir: str | Path,
    quarantine_dir: str | Path,
    *,
    delimiter: str = ",",
    encoding: str = "utf-8-sig",
    overwrite: bool = False,
    run_id: str | None = None,
    ingested_at: datetime | None = None,
) -> IngestionResult:
    """Ingest one CSV without transforming its cell values.

    Rows whose field count differs from the header are written to a restricted local
    quarantine file. No source values are emitted through logs, exceptions, manifests,
    or the returned result.
    """
    source = Path(input_path).expanduser().resolve()
    if not source.is_file():
        raise IngestionError("Input must be an existing regular file.")
    if source.suffix.lower() != ".csv":
        raise IngestionError("Input must use the .csv extension.")
    if delimiter not in SUPPORTED_DELIMITERS or len(delimiter) != 1:
        raise IngestionError("Delimiter must be one of comma, semicolon, tab, or pipe.")

    source_slug = _safe_slug(source_system)
    file_slug = _safe_slug(source.stem)
    bronze_root = Path(bronze_dir).expanduser().resolve()
    quarantine_root = Path(quarantine_dir).expanduser().resolve()
    bronze_path = bronze_root / source_slug / f"{file_slug}.bronze.csv"
    quarantine_path = quarantine_root / source_slug / f"{file_slug}.quarantine.csv"
    manifest_path = bronze_root / source_slug / f"{file_slug}.manifest.json"

    planned = (bronze_path, quarantine_path, manifest_path)
    if not overwrite and any(path.exists() for path in planned):
        raise IngestionError("An output already exists; use overwrite=True intentionally.")

    timestamp = (ingested_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    ingested_at_utc = timestamp.isoformat().replace("+00:00", "Z")
    ingestion_run_id = run_id or str(uuid.uuid4())
    source_hash = _sha256(source)

    bronze_handle = quarantine_handle = None
    bronze_temp = quarantine_temp = None
    accepted_rows = quarantined_rows = 0

    try:
        with source.open("r", encoding=encoding, newline="") as input_handle:
            reader = csv.reader(input_handle, delimiter=delimiter, strict=True)
            try:
                header = _validate_header(next(reader))
            except StopIteration as exc:
                raise IngestionError("The CSV is empty or has no header row.") from exc
            except (UnicodeError, csv.Error) as exc:
                raise IngestionError("The CSV header could not be decoded or parsed.") from exc

            bronze_handle, bronze_temp = _atomic_csv_writer(bronze_path)
            quarantine_handle, quarantine_temp = _atomic_csv_writer(quarantine_path)
            bronze_writer = csv.writer(bronze_handle, lineterminator="\n")
            quarantine_writer = csv.writer(quarantine_handle, lineterminator="\n")
            bronze_writer.writerow([*header, *LINEAGE_COLUMNS])
            quarantine_writer.writerow([*header, *LINEAGE_COLUMNS, QUARANTINE_REASON_COLUMN])

            try:
                for row_number, row in enumerate(reader, start=2):
                    lineage = [
                        source_system,
                        source.name,
                        str(row_number),
                        source_hash,
                        ingested_at_utc,
                        ingestion_run_id,
                    ]
                    if len(row) == len(header):
                        bronze_writer.writerow([*row, *lineage])
                        accepted_rows += 1
                    else:
                        padded = list(row[: len(header)])
                        padded.extend([""] * (len(header) - len(padded)))
                        reason = (
                            "too_many_fields"
                            if len(row) > len(header)
                            else "too_few_fields"
                        )
                        quarantine_writer.writerow([*padded, *lineage, reason])
                        quarantined_rows += 1
            except (UnicodeError, csv.Error) as exc:
                raise IngestionError(
                    "The CSV body could not be decoded or parsed; no row values were logged."
                ) from exc

        bronze_handle.close()
        quarantine_handle.close()
        bronze_temp.replace(bronze_path)
        _restrict_permissions(bronze_path)
        bronze_temp = None

        if quarantined_rows:
            quarantine_temp.replace(quarantine_path)
            _restrict_permissions(quarantine_path)
        else:
            quarantine_temp.unlink(missing_ok=True)
            if overwrite:
                quarantine_path.unlink(missing_ok=True)
            quarantine_path_for_result: Path | None = None
        quarantine_temp = None
        if quarantined_rows:
            quarantine_path_for_result = quarantine_path

        detected = _sensitive_columns(header)
        result = IngestionResult(
            source_system=source_system,
            source_file=source.name,
            source_sha256=source_hash,
            ingestion_run_id=ingestion_run_id,
            ingested_at_utc=ingested_at_utc,
            accepted_rows=accepted_rows,
            quarantined_rows=quarantined_rows,
            source_column_count=len(header),
            source_schema_sha256=_schema_sha256(header),
            sensitive_column_count_detected=len(detected),
            bronze_path=str(bronze_path),
            quarantine_path=(
                str(quarantine_path_for_result) if quarantine_path_for_result else None
            ),
            manifest_path=str(manifest_path),
        )
        _write_json_atomic(manifest_path, asdict(result))
        LOGGER.info(
            "Ingestion completed: accepted=%d quarantined=%d sensitive_columns=%d",
            accepted_rows,
            quarantined_rows,
            len(detected),
        )
        return result
    except IngestionError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise IngestionError(
            "Ingestion failed due to an I/O, encoding, or CSV parsing error; no row values were logged."
        ) from exc
    finally:
        for handle in (bronze_handle, quarantine_handle):
            if handle is not None and not handle.closed:
                handle.close()
        for temporary in (bronze_temp, quarantine_temp):
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preserve a source CSV in PATIENTRA's Bronze layer."
    )
    parser.add_argument("input_path", type=Path)
    parser.add_argument("--source-system", required=True)
    parser.add_argument("--bronze-dir", type=Path, default=Path("data/bronze"))
    parser.add_argument("--quarantine-dir", type=Path, default=Path("data/quarantine"))
    parser.add_argument("--delimiter", default=",")
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        result = ingest_csv(
            args.input_path,
            args.source_system,
            args.bronze_dir,
            args.quarantine_dir,
            delimiter=args.delimiter,
            encoding=args.encoding,
            overwrite=args.overwrite,
        )
    except IngestionError as exc:
        LOGGER.error("%s", exc)
        return 2
    print(json.dumps(asdict(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

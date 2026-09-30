"""Metadata-only CSV profiling.

Profiles intentionally contain no cell values, samples, minima, or maxima. This makes
them useful for reconciliation without turning logs or reports into a PHI side channel.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable


class ProfilingError(RuntimeError):
    """Raised when a CSV cannot be safely profiled."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def profile_csv(path: str | Path, *, encoding: str = "utf-8-sig") -> dict[str, object]:
    """Return aggregate schema statistics without returning any source values."""
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".csv":
        raise ProfilingError("Input must be an existing .csv file.")

    try:
        with source.open("r", encoding=encoding, newline="") as handle:
            reader = csv.reader(handle, strict=True)
            try:
                header = next(reader)
            except StopIteration as exc:
                raise ProfilingError("The CSV is empty or has no header row.") from exc
            if not header or any(not name for name in header) or len(set(header)) != len(header):
                raise ProfilingError("The CSV header is empty, duplicated, or incomplete.")

            missing = [0] * len(header)
            distinct = [set() for _ in header]
            seen_rows: set[tuple[str, ...]] = set()
            rows = malformed = duplicate_rows = 0
            for row in reader:
                rows += 1
                if len(row) != len(header):
                    malformed += 1
                    continue
                signature = tuple(row)
                if signature in seen_rows:
                    duplicate_rows += 1
                else:
                    seen_rows.add(signature)
                for index, value in enumerate(row):
                    if value.strip() == "":
                        missing[index] += 1
                    else:
                        distinct[index].add(value)
    except ProfilingError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ProfilingError(
            "The CSV could not be read; no source values were included in the error."
        ) from exc

    return {
        "profile_version": "1.0",
        "source_file": source.name,
        "source_sha256": _sha256(source),
        "row_count": rows,
        "column_count": len(header),
        "malformed_row_count": malformed,
        "exact_duplicate_row_count": duplicate_rows,
        "columns": [
            {
                "name": name,
                "missing_count": missing[index],
                "non_missing_distinct_count": len(distinct[index]),
            }
            for index, name in enumerate(header)
        ],
    }


def _write_json(path: Path, payload: object, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise ProfilingError("Profile output exists; use --overwrite intentionally.")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".tmp-",
        suffix=".tmp", delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.replace(path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a metadata-only CSV profile.")
    parser.add_argument("inputs", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = {"files": [profile_csv(path) for path in args.inputs]}
        _write_json(args.output.resolve(), payload, overwrite=args.overwrite)
    except ProfilingError as exc:
        parser.error(str(exc))
    print(json.dumps({"profile_path": str(args.output.resolve()), "file_count": len(args.inputs)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

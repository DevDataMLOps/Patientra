"""Read and verify the exact approved snapshot without modifying its file."""
import hashlib
import hmac
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from patientra.api.models import Breakdown, DataQuality, Overall, PipelineStatus
from patientra.serving.store import DIMENSIONS, FIELDS, METRICS

MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
STATUS_FIELDS = (
    "release_status", "freshness_status", "published_at_utc", "source_run_at_utc",
    "source_age_seconds", "gold_rows", "eligible_rows", "excluded_rows",
    "breakdown_rows", "suppressed_rows", "validation_checks_passed",
    "minimum_cell_size", "analytics_sha256", "breakdown_sha256", "gate_sha256",
)


class SnapshotUnavailable(RuntimeError):
    """The configured aggregate snapshot cannot be served safely."""


@dataclass(frozen=True)
class Snapshot:
    overall: Overall
    breakdowns: tuple[Breakdown, ...]
    status: PipelineStatus
    quality: DataQuality


def _check(condition):
    if not condition:
        raise SnapshotUnavailable("Approved snapshot unavailable")


def _timestamp(value):
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _check(moment.utcoffset() is not None)
    return moment.astimezone(timezone.utc)


def read_snapshot(database: Path, expected_sha256: str, *, now=None) -> Snapshot:
    """Hash and deserialize the same bounded bytes, avoiding file-replacement races."""
    try:
        with database.open("rb") as stream:
            content = stream.read(MAX_SNAPSHOT_BYTES + 1)
        _check(len(content) <= MAX_SNAPSHOT_BYTES)
        _check(hmac.compare_digest(hashlib.sha256(content).hexdigest(), expected_sha256))
        # Deserialization never opens the on-disk database for writing. Each request
        # gets its own connection and one immutable set of source bytes.
        conn = sqlite3.connect(":memory:")
        try:
            conn.deserialize(content)
            conn.execute("PRAGMA query_only = ON")
            conn.execute("PRAGMA trusted_schema = OFF")
            conn.row_factory = sqlite3.Row
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            _check(tables == {"overall", "breakdowns", "pipeline_status"})
            for table, fields in (("overall", METRICS), ("breakdowns", FIELDS),
                                  ("pipeline_status", STATUS_FIELDS)):
                # Names are fixed constants, never request input.
                columns = tuple(r[1] for r in conn.execute(f"PRAGMA table_info({table})"))
                _check(columns == fields)
            overall_rows = conn.execute(f"SELECT {','.join(METRICS)} FROM overall").fetchmany(2)
            status_rows = conn.execute(f"SELECT {','.join(STATUS_FIELDS)} FROM pipeline_status").fetchmany(2)
            _check(len(overall_rows) == len(status_rows) == 1)
            overall = Overall.model_validate(dict(overall_rows[0]))
            status = dict(status_rows[0])
            _check(status["release_status"] == "PASS"
                   and type(status["validation_checks_passed"]) is int
                   and status["validation_checks_passed"] == 13)
            for key in ("source_age_seconds", "gold_rows", "eligible_rows", "excluded_rows",
                        "breakdown_rows", "suppressed_rows", "minimum_cell_size"):
                _check(type(status[key]) is int and status[key] >= 0)
            minimum = status["minimum_cell_size"]
            _check(minimum >= 11)
            _check(all(getattr(overall, key) >= minimum for key in METRICS[:3]))
            _check(status["gold_rows"] == status["eligible_rows"] + status["excluded_rows"])
            _check(status["eligible_rows"] == overall.eligible_admissions)
            for key in ("analytics_sha256", "breakdown_sha256", "gate_sha256"):
                _check(isinstance(status[key], str) and re.fullmatch(r"[0-9a-f]{64}", status[key]))
            released, suppressed = [], 0
            count = 0
            for item in conn.execute(f"SELECT {','.join(FIELDS)} FROM breakdowns ORDER BY dimension, category"):
                count += 1
                _check(count <= 10000)
                row = dict(item)
                _check(row["dimension"] in DIMENSIONS)
                _check(isinstance(row["category"], str) and 1 <= len(row["category"]) <= 128)
                reason = row.pop("suppression_reason")
                _check(reason in ("", "primary_small_cell", "complementary_suppression"))
                if reason:
                    _check(all(row[key] is None for key in METRICS))
                    suppressed += 1
                else:
                    item = Breakdown.model_validate(row)
                    _check(all(getattr(item, key) >= minimum for key in METRICS[:3]))
                    released.append(item)
            _check(count == status["breakdown_rows"] and suppressed == status["suppressed_rows"])
        finally:
            conn.close()
        run_at, published = _timestamp(status["source_run_at_utc"]), _timestamp(status["published_at_utc"])
        moment = now or datetime.now(timezone.utc)
        _check(moment.utcoffset() is not None)
        _check(run_at <= published and published <= moment)
        publication_age = int((published - run_at).total_seconds())
        _check(status["source_age_seconds"] == publication_age)
        _check(status["freshness_status"] == ("FRESH" if publication_age <= 86400 else "STALE"))
        current_age = int((moment - run_at).total_seconds())
        pipeline = PipelineStatus(
            release_status="PASS", freshness_at_publication=status["freshness_status"],
            current_freshness="FRESH" if current_age <= 86400 else "STALE",
            published_at_utc=published, source_run_at_utc=run_at,
            current_source_age_seconds=current_age, validation_checks_passed=13,
            **{key: status[key] for key in ("analytics_sha256", "breakdown_sha256", "gate_sha256")},
        )
        quality = DataQuality(
            **{key: status[key] for key in ("gold_rows", "eligible_rows", "excluded_rows",
                                          "breakdown_rows", "suppressed_rows", "minimum_cell_size")},
            released_breakdown_rows=len(released), validation_checks_passed=13,
        )
        return Snapshot(overall, tuple(released), pipeline, quality)
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise SnapshotUnavailable("Approved snapshot unavailable") from exc

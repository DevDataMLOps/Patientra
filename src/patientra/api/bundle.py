"""Export and serve approved aggregate JSON; never upload SQLite or protected rows."""
import argparse
import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from patientra.api.models import ReleaseBundle
from patientra.api.snapshot import MAX_SNAPSHOT_BYTES, Snapshot, SnapshotUnavailable, read_snapshot


def read_bundle(path: Path, expected_sha256: str, *, now=None) -> Snapshot:
    try:
        with path.open("rb") as stream:
            content = stream.read(MAX_SNAPSHOT_BYTES + 1)
        if (len(content) > MAX_SNAPSHOT_BYTES
                or not hmac.compare_digest(hashlib.sha256(content).hexdigest(), expected_sha256)):
            raise SnapshotUnavailable("Approved release unavailable")
        bundle = ReleaseBundle.model_validate_json(content)
        status = bundle.status
        moment = now or datetime.now(timezone.utc)
        run_at, published = status.source_run_at_utc, status.published_at_utc
        if (run_at.utcoffset() is None or published.utcoffset() is None
                or moment.utcoffset() is None or not run_at <= published <= moment):
            raise SnapshotUnavailable("Approved release unavailable")
        publication_age = int((published - run_at).total_seconds())
        if status.freshness_at_publication != ("FRESH" if publication_age <= 86400 else "STALE"):
            raise SnapshotUnavailable("Approved release unavailable")
        for digest in (status.analytics_sha256, status.breakdown_sha256, status.gate_sha256):
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise SnapshotUnavailable("Approved release unavailable")
        age = int((moment - run_at).total_seconds())
        status = status.model_copy(update={"current_source_age_seconds": age,
                                          "current_freshness": "FRESH" if age <= 86400 else "STALE"})
        rows = tuple(sorted(bundle.breakdowns, key=lambda row: (row.dimension, row.category)))
        return Snapshot(bundle.overall, rows, status, bundle.quality)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise SnapshotUnavailable("Approved release unavailable") from exc


def export_bundle(database, output, *, identity_audit=None, patient_master=None, gold_audit=None,
                  gold=None, validation=None):
    """Read a locally validated snapshot; emit only unsuppressed, typed aggregates."""
    database, output = Path(database), Path(output)
    if output.exists():
        raise ValueError("Refusing an existing bundle; create a new versioned release")
    snapshot = read_snapshot(database, hashlib.sha256(database.read_bytes()).hexdigest())
    quality = snapshot.quality
    supplied = (identity_audit, patient_master, gold_audit, gold, validation)
    if any(supplied) and not all(supplied):
        raise ValueError("Identity metadata requires the complete local release lineage")
    if all(supplied):
        identity = json.loads(Path(identity_audit).read_text(encoding="utf-8"))
        gold_metadata = json.loads(Path(gold_audit).read_text(encoding="utf-8"))
        gate = json.loads(Path(validation).read_text(encoding="utf-8"))
        if (identity.get("rule_version") != "phase3-identity-v1"
                or identity.get("one_to_one_constraint_passed") is not True
                or Path(identity.get("patient_master_path", "")).resolve() != Path(patient_master).resolve()
                or identity.get("input_sha256") != gold_metadata.get("input_sha256", {}).get("patients")
                or gold_metadata.get("input_sha256", {}).get("patient_master")
                != hashlib.sha256(Path(patient_master).read_bytes()).hexdigest()
                or hashlib.sha256(Path(validation).read_bytes()).hexdigest() != snapshot.status.gate_sha256
                or gate.get("verified_sha256", {}).get("gold") != hashlib.sha256(Path(gold).read_bytes()).hexdigest()
                or gold_metadata.get("gold_rows") != snapshot.quality.gold_rows):
            raise ValueError("Identity-to-Gold lineage is invalid")
        counts = identity.get("review_status_counts", {})
        if (not isinstance(counts, dict) or set(counts) - {"PENDING", "ABSTAINED", "ACCEPTED", "REJECTED"}
                or any(type(value) is not int or value < 0 for value in counts.values())
                or sum(counts.values()) != identity.get("review_candidates")):
            raise ValueError("Invalid identity review counts")
        unique = identity.get("unique_master_patients")
        if type(unique) is not int or unique < 0 or unique != gold_metadata.get("patient_master_unique_patients"):
            raise ValueError("Invalid identity patient counts")
        pending = counts.get("PENDING", 0) + counts.get("ABSTAINED", 0)
        quality = quality.model_copy(update={
            "identity_resolution": "reviews_unresolved" if pending else "reviews_completed",
            "unresolved_identity_reviews": pending, "unique_master_patients": unique,
        })
    bundle = ReleaseBundle(overall=snapshot.overall, breakdowns=list(snapshot.breakdowns),
                           status=snapshot.status, quality=quality)
    content = bundle.model_dump_json(indent=2, exclude_none=True) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents silently replacing a previously approved release.
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
    return hashlib.sha256(output.read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export approved aggregate release JSON for hosting")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--identity-audit", type=Path)
    parser.add_argument("--patient-master", type=Path)
    parser.add_argument("--gold-audit", type=Path)
    parser.add_argument("--gold", type=Path)
    parser.add_argument("--validation", type=Path)
    args = parser.parse_args(argv)
    try:
        digest = export_bundle(args.database, args.output, identity_audit=args.identity_audit,
                               patient_master=args.patient_master, gold_audit=args.gold_audit,
                               gold=args.gold, validation=args.validation)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, SnapshotUnavailable):
        parser.error("Release export failed; inspect protected inputs locally")
    print(json.dumps({"bundle_sha256": digest, "status": "PASS"}))
    return 0

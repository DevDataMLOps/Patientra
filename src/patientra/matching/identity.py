"""Conservative, auditable cross-hospital patient identity resolution.

Only one-to-one, strongly corroborated pairs are linked automatically. Uncertain pairs
remain separate identities and are written to a protected human review queue. Aggregate
audit output contains no source identifiers or demographic values.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import json
import os
import tempfile
import unicodedata
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from patientra.ingestion.ingest import LINEAGE_COLUMNS
from patientra.transformations.silver import PATIENT_COLUMNS


RULE_VERSION = "phase3-identity-v1"
MASTER_FIELDS = (
    "master_patient_id", "patient_id", "source_system", "link_status",
    "match_case_id", "rule_version",
)
DECISION_FIELDS = (
    "match_case_id", "lg_patient_id", "rs_patient_id", "decision",
    "decision_source", "match_score", "evidence_codes", "conflict_codes",
    "decision_rule", "rule_version", "reviewer_id", "reviewed_at_utc",
    "review_notes",
)
REVIEW_FIELDS = (
    "review_case_id", "lg_patient_id", "rs_patient_id", "review_status",
    "match_score", "evidence_codes", "conflict_codes", "decision_rule",
    "rule_version", "reviewer_id", "reviewed_at_utc", "review_notes",
)
REVIEW_DECISION_FIELDS = (
    "review_case_id", "decision", "reviewer_id", "reviewed_at_utc", "review_notes",
)


class IdentityError(RuntimeError):
    """Raised when identity resolution cannot complete safely."""


@dataclass(frozen=True)
class IdentityConfig:
    """Versioned configuration for deterministic identity resolution."""

    rule_version: str = RULE_VERSION


@dataclass(frozen=True)
class IdentityResult:
    """Aggregate-only result; it contains no patient identifiers."""

    rule_version: str
    run_id: str
    created_at_utc: str
    input_patients: int
    source_counts: dict[str, int]
    candidate_pairs_generated: int
    auto_matches: int
    human_accepted_matches: int
    review_candidates: int
    review_status_counts: dict[str, int]
    master_patient_rows: int
    unique_master_patients: int
    linked_source_rows: int
    review_pending_source_rows: int
    unlinked_source_rows: int
    auto_rule_counts: dict[str, int]
    review_rule_counts: dict[str, int]
    patient_master_path: str
    match_decisions_path: str
    review_queue_path: str
    audit_path: str


@dataclass(frozen=True)
class Patient:
    patient_id: str
    source_system: str
    first_name: str
    last_name: str
    date_of_birth: date
    sex: str
    phone: str
    state: str


@dataclass(frozen=True)
class Candidate:
    lg: Patient
    rs: Patient
    score: int
    evidence: tuple[str, ...]
    conflicts: tuple[str, ...]
    rule: str


def _normalize_text(value: str) -> str:
    ascii_text = (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
        .casefold()
    )
    return "".join(character for character in ascii_text if character.isalnum())


def _normalize_phone(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) == 11 and digits.startswith("0"):
        return digits[1:]
    if len(digits) == 13 and digits.startswith("234"):
        return digits[3:]
    return digits


def _edit_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if len(left) > len(right):
        left, right = right, left
    previous = list(range(len(left) + 1))
    for row_index, right_character in enumerate(right, start=1):
        current = [row_index]
        for column_index, left_character in enumerate(left, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column_index] + 1,
                    previous[column_index - 1]
                    + (left_character != right_character),
                )
            )
        previous = current
    return previous[-1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _token(key: bytes, prefix: str, *values: str, length: int = 20) -> str:
    payload = "\x1f".join((prefix, *values)).encode("utf-8")
    digest = hmac.new(key, payload, hashlib.sha256).hexdigest().upper()
    return f"{prefix}-{digest[:length]}"


def _read_patients(path: str | Path) -> tuple[Path, list[Patient]]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise IdentityError("The Silver patients input must be an existing file.")
    expected_header = [*PATIENT_COLUMNS, *LINEAGE_COLUMNS]
    patients: list[Patient] = []
    seen_ids: set[str] = set()
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if reader.fieldnames != expected_header:
                raise IdentityError(
                    "Silver patient schema drift detected; rebuild or review Silver first."
                )
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise IdentityError("Malformed Silver patient row detected.")
                patient_id = row["patient_id"].strip()
                source_system = row["source_system"].strip().upper()
                if not patient_id or patient_id in seen_ids:
                    raise IdentityError("Silver patient IDs must be present and unique.")
                if source_system not in {"LG", "RS"}:
                    raise IdentityError("Identity resolution supports only LG and RS sources.")
                seen_ids.add(patient_id)
                try:
                    birth_date = date.fromisoformat(row["date_of_birth"])
                except ValueError as exc:
                    raise IdentityError("Silver date_of_birth must be an ISO date.") from exc
                patients.append(
                    Patient(
                        patient_id=patient_id,
                        source_system=source_system,
                        first_name=_normalize_text(row["first_name"]),
                        last_name=_normalize_text(row["last_name"]),
                        date_of_birth=birth_date,
                        sex=row["sex"].strip().upper(),
                        phone=_normalize_phone(row["phone"]),
                        state=_normalize_text(row["state"]),
                    )
                )
    except IdentityError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise IdentityError(
            "Could not read Silver patients; no patient values were included in the error."
        ) from exc
    return source, patients


def _index(patients: Sequence[Patient], key_function) -> dict[object, list[Patient]]:
    result: dict[object, list[Patient]] = defaultdict(list)
    for patient in patients:
        result[key_function(patient)].append(patient)
    return result


def _add_cross_pairs(
    pairs: set[tuple[str, str]],
    left_index: dict[object, list[Patient]],
    right_index: dict[object, list[Patient]],
) -> None:
    for key in left_index.keys() & right_index.keys():
        if key == "" or (isinstance(key, tuple) and any(value == "" for value in key)):
            continue
        for left in left_index[key]:
            for right in right_index[key]:
                pairs.add((left.patient_id, right.patient_id))


def _candidate_pairs(lg: Sequence[Patient], rs: Sequence[Patient]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    key_functions = (
        lambda patient: patient.phone,
        lambda patient: (patient.date_of_birth, patient.sex, patient.state),
        lambda patient: (
            patient.first_name, patient.last_name, patient.sex, patient.state
        ),
    )
    for key_function in key_functions:
        _add_cross_pairs(pairs, _index(lg, key_function), _index(rs, key_function))

    # Equal-length phone values with one substituted digit share a deletion signature.
    left_signatures: dict[tuple[int, int, str], list[Patient]] = defaultdict(list)
    right_signatures: dict[tuple[int, int, str], list[Patient]] = defaultdict(list)
    for patients, index in ((lg, left_signatures), (rs, right_signatures)):
        for patient in patients:
            for position in range(len(patient.phone)):
                signature = (
                    len(patient.phone),
                    position,
                    patient.phone[:position] + patient.phone[position + 1 :],
                )
                index[signature].append(patient)
    _add_cross_pairs(pairs, left_signatures, right_signatures)
    return pairs


def _evaluate(
    lg: Patient,
    rs: Patient,
    lg_phone_counts: Counter[str],
    rs_phone_counts: Counter[str],
) -> tuple[Candidate, bool, bool]:
    phone_exact = bool(lg.phone) and lg.phone == rs.phone
    phone_near = (
        not phone_exact
        and len(lg.phone) == len(rs.phone)
        and bool(lg.phone)
        and _edit_distance(lg.phone, rs.phone) == 1
    )
    dob_exact = lg.date_of_birth == rs.date_of_birth
    birth_year_exact = lg.date_of_birth.year == rs.date_of_birth.year
    birth_month_day_exact = (
        lg.date_of_birth.month,
        lg.date_of_birth.day,
    ) == (rs.date_of_birth.month, rs.date_of_birth.day)
    first_exact = bool(lg.first_name) and lg.first_name == rs.first_name
    last_exact = bool(lg.last_name) and lg.last_name == rs.last_name
    first_near = (
        not first_exact
        and bool(lg.first_name and rs.first_name)
        and _edit_distance(lg.first_name, rs.first_name) == 1
    )
    last_near = (
        not last_exact
        and bool(lg.last_name and rs.last_name)
        and _edit_distance(lg.last_name, rs.last_name) == 1
    )
    sex_exact = bool(lg.sex) and lg.sex == rs.sex
    state_exact = bool(lg.state) and lg.state == rs.state
    unique_phone = (
        phone_exact
        and lg_phone_counts[lg.phone] == 1
        and rs_phone_counts[rs.phone] == 1
    )

    evidence: list[str] = []
    score = 0
    for condition, code, points in (
        (phone_exact, "PHONE_EXACT", 50),
        (phone_near, "PHONE_EDIT_DISTANCE_1", 30),
        (dob_exact, "DOB_EXACT", 25),
        (not dob_exact and birth_year_exact, "BIRTH_YEAR_EXACT", 8),
        (not dob_exact and birth_month_day_exact, "BIRTH_MONTH_DAY_EXACT", 8),
        (first_exact, "FIRST_NAME_EXACT", 10),
        (first_near, "FIRST_NAME_EDIT_DISTANCE_1", 5),
        (last_exact, "LAST_NAME_EXACT", 15),
        (last_near, "LAST_NAME_EDIT_DISTANCE_1", 7),
        (sex_exact, "SEX_EXACT", 5),
        (state_exact, "STATE_EXACT", 5),
        (unique_phone, "PHONE_UNIQUE_BOTH_SOURCES", 5),
    ):
        if condition:
            evidence.append(code)
            score += points

    conflicts: list[str] = []
    for condition, code in (
        (not phone_exact, "PHONE_DIFFERS"),
        (not dob_exact, "DOB_DIFFERS"),
        (not first_exact, "FIRST_NAME_DIFFERS"),
        (not last_exact, "LAST_NAME_DIFFERS"),
        (not sex_exact, "SEX_DIFFERS"),
        (not state_exact, "STATE_DIFFERS"),
        (phone_exact and not unique_phone, "PHONE_NOT_UNIQUE"),
    ):
        if condition:
            conflicts.append(code)

    auto_eligible = (
        unique_phone
        and sex_exact
        and state_exact
        and last_exact
        and (dob_exact or first_exact)
    )
    review_eligible = (
        (
            phone_near
            and sex_exact
            and state_exact
            and (dob_exact or (first_exact and last_exact))
        )
        or (
            dob_exact
            and sex_exact
            and state_exact
            and (
                (first_exact and (last_exact or last_near))
                or (last_exact and (first_exact or first_near))
            )
        )
        or (
            first_exact
            and last_exact
            and sex_exact
            and state_exact
            and not dob_exact
            and (birth_year_exact or birth_month_day_exact)
        )
        or (
            phone_exact
            and not unique_phone
            and sex_exact
            and state_exact
            and (dob_exact or last_exact)
        )
    )
    if auto_eligible:
        rule = (
            "UNIQUE_PHONE_DOB_LAST"
            if dob_exact
            else "UNIQUE_PHONE_FULL_NAME"
        )
    elif phone_near:
        rule = "NEAR_PHONE_WITH_CORROBORATION"
    elif dob_exact:
        rule = "EXACT_DOB_WITH_NEAR_NAME"
    elif first_exact and last_exact:
        rule = "EXACT_FULL_NAME_WITH_BIRTH_COMPONENT"
    else:
        rule = "NON_UNIQUE_PHONE_WITH_CORROBORATION"
    return (
        Candidate(
            lg=lg,
            rs=rs,
            score=score,
            evidence=tuple(evidence),
            conflicts=tuple(conflicts),
            rule=rule,
        ),
        auto_eligible,
        review_eligible,
    )


def _read_review_decisions(
    path: str | Path | None, valid_case_ids: set[str]
) -> dict[str, dict[str, str]]:
    if path is None:
        return {}
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise IdentityError("The review decisions input must be an existing file.")
    decisions: dict[str, dict[str, str]] = {}
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if reader.fieldnames != list(REVIEW_DECISION_FIELDS):
                raise IdentityError("Review decision schema does not match the contract.")
            for row in reader:
                case_id = row["review_case_id"].strip()
                decision = row["decision"].strip().upper()
                if case_id not in valid_case_ids or case_id in decisions:
                    raise IdentityError("Review decisions contain an unknown or duplicate case.")
                if decision not in {"ACCEPT", "REJECT", "ABSTAIN"}:
                    raise IdentityError("Review decision must be ACCEPT, REJECT, or ABSTAIN.")
                if not row["reviewer_id"].strip() or not row["reviewed_at_utc"].strip():
                    raise IdentityError("Completed reviews require reviewer and time metadata.")
                try:
                    reviewed_at = datetime.fromisoformat(
                        row["reviewed_at_utc"].strip().replace("Z", "+00:00")
                    )
                except ValueError as exc:
                    raise IdentityError("Review time must be a valid ISO timestamp.") from exc
                if reviewed_at.tzinfo is None:
                    raise IdentityError("Review time must include a timezone.")
                decisions[case_id] = {**row, "decision": decision}
    except IdentityError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise IdentityError(
            "Could not read review decisions; no review values were included in the error."
        ) from exc
    return decisions


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", dir=path.parent,
        prefix=".tmp-", suffix=".tmp", delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent,
        prefix=".tmp-", suffix=".tmp", delete=False,
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


def resolve_identities(
    patients_silver: str | Path,
    output_dir: str | Path,
    master_key: bytes,
    *,
    review_decisions: str | Path | None = None,
    config: IdentityConfig | None = None,
    overwrite: bool = False,
    run_id: str | None = None,
    created_at: datetime | None = None,
) -> IdentityResult:
    """Resolve high-confidence identities and create a protected review queue."""
    if len(master_key) < 32:
        raise IdentityError("The identity HMAC key must be at least 32 bytes.")
    selected = config or IdentityConfig()
    source_path, patients = _read_patients(patients_silver)
    lg = [patient for patient in patients if patient.source_system == "LG"]
    rs = [patient for patient in patients if patient.source_system == "RS"]
    by_id = {patient.patient_id: patient for patient in patients}
    lg_phone_counts = Counter(patient.phone for patient in lg if patient.phone)
    rs_phone_counts = Counter(patient.phone for patient in rs if patient.phone)

    generated_pairs = _candidate_pairs(lg, rs)
    evaluated: dict[tuple[str, str], tuple[Candidate, bool, bool]] = {}
    for lg_id, rs_id in generated_pairs:
        evaluated[(lg_id, rs_id)] = _evaluate(
            by_id[lg_id], by_id[rs_id], lg_phone_counts, rs_phone_counts
        )

    preliminary_auto = {
        pair: candidate
        for pair, (candidate, auto_eligible, _) in evaluated.items()
        if auto_eligible
    }
    degrees: Counter[str] = Counter()
    for lg_id, rs_id in preliminary_auto:
        degrees[f"LG:{lg_id}"] += 1
        degrees[f"RS:{rs_id}"] += 1
    auto_matches: dict[tuple[str, str], Candidate] = {}
    auto_conflicts: set[tuple[str, str]] = set()
    for pair, candidate in preliminary_auto.items():
        lg_id, rs_id = pair
        if degrees[f"LG:{lg_id}"] == 1 and degrees[f"RS:{rs_id}"] == 1:
            auto_matches[pair] = candidate
        else:
            auto_conflicts.add(pair)

    auto_nodes = {patient_id for pair in auto_matches for patient_id in pair}
    review_candidates: dict[tuple[str, str], Candidate] = {}
    for pair, (candidate, _, review_eligible) in evaluated.items():
        if pair in auto_matches or any(patient_id in auto_nodes for patient_id in pair):
            continue
        if pair in auto_conflicts:
            candidate = Candidate(
                lg=candidate.lg,
                rs=candidate.rs,
                score=candidate.score,
                evidence=candidate.evidence,
                conflicts=tuple(sorted((*candidate.conflicts, "AUTO_CANDIDATE_COLLISION"))),
                rule="AUTO_CANDIDATE_COLLISION",
            )
            review_candidates[pair] = candidate
        elif review_eligible:
            review_candidates[pair] = candidate

    case_by_pair = {
        pair: _token(master_key, "RV", pair[0], pair[1])
        for pair in review_candidates
    }
    supplied_decisions = _read_review_decisions(
        review_decisions, set(case_by_pair.values())
    )

    accepted_links: dict[str, tuple[str, str, str]] = {}
    decision_rows: list[dict[str, str]] = []
    auto_rule_counts: Counter[str] = Counter()
    for pair, candidate in sorted(auto_matches.items()):
        lg_id, rs_id = pair
        case_id = _token(master_key, "MT", lg_id, rs_id)
        accepted_links[lg_id] = (rs_id, "AUTO", case_id)
        accepted_links[rs_id] = (lg_id, "AUTO", case_id)
        auto_rule_counts[candidate.rule] += 1
        decision_rows.append(
            {
                "match_case_id": case_id,
                "lg_patient_id": lg_id,
                "rs_patient_id": rs_id,
                "decision": "ACCEPT",
                "decision_source": "AUTOMATED_RULE",
                "match_score": str(candidate.score),
                "evidence_codes": ";".join(candidate.evidence),
                "conflict_codes": ";".join(candidate.conflicts),
                "decision_rule": candidate.rule,
                "rule_version": selected.rule_version,
                "reviewer_id": "",
                "reviewed_at_utc": "",
                "review_notes": "",
            }
        )

    for pair, candidate in sorted(review_candidates.items()):
        case_id = case_by_pair[pair]
        review = supplied_decisions.get(case_id)
        if review and review["decision"] == "ACCEPT":
            lg_id, rs_id = pair
            if lg_id in accepted_links or rs_id in accepted_links:
                raise IdentityError(
                    "Human ACCEPT decisions violate the one-to-one identity constraint."
                )
            accepted_links[lg_id] = (rs_id, "HUMAN", case_id)
            accepted_links[rs_id] = (lg_id, "HUMAN", case_id)
        if review:
            decision_rows.append(
                {
                    "match_case_id": case_id,
                    "lg_patient_id": pair[0],
                    "rs_patient_id": pair[1],
                    "decision": review["decision"],
                    "decision_source": "HUMAN_REVIEW",
                    "match_score": str(candidate.score),
                    "evidence_codes": ";".join(candidate.evidence),
                    "conflict_codes": ";".join(candidate.conflicts),
                    "decision_rule": candidate.rule,
                    "rule_version": selected.rule_version,
                    "reviewer_id": review["reviewer_id"],
                    "reviewed_at_utc": review["reviewed_at_utc"],
                    "review_notes": review["review_notes"],
                }
            )

    review_rows: list[dict[str, str]] = []
    review_status_counts: Counter[str] = Counter()
    review_rule_counts: Counter[str] = Counter()
    pending_patients: set[str] = set()
    rejected_patients: set[str] = set()
    for pair, candidate in sorted(review_candidates.items()):
        case_id = case_by_pair[pair]
        review = supplied_decisions.get(case_id)
        status = (
            {
                "ACCEPT": "ACCEPTED",
                "REJECT": "REJECTED",
                "ABSTAIN": "ABSTAINED",
            }[review["decision"]]
            if review
            else "PENDING"
        )
        review_status_counts[status] += 1
        review_rule_counts[candidate.rule] += 1
        if status in {"PENDING", "ABSTAINED"}:
            pending_patients.update(pair)
        elif status == "REJECTED":
            rejected_patients.update(pair)
        review_rows.append(
            {
                "review_case_id": case_id,
                "lg_patient_id": pair[0],
                "rs_patient_id": pair[1],
                "review_status": status,
                "match_score": str(candidate.score),
                "evidence_codes": ";".join(candidate.evidence),
                "conflict_codes": ";".join(candidate.conflicts),
                "decision_rule": candidate.rule,
                "rule_version": selected.rule_version,
                "reviewer_id": review["reviewer_id"] if review else "",
                "reviewed_at_utc": review["reviewed_at_utc"] if review else "",
                "review_notes": review["review_notes"] if review else "",
            }
        )

    master_rows: list[dict[str, str]] = []
    component_tokens: dict[str, str] = {}
    for patient in sorted(patients, key=lambda item: (item.source_system, item.patient_id)):
        link = accepted_links.get(patient.patient_id)
        if link:
            counterpart_id, link_source, case_id = link
            counterpart = by_id[counterpart_id]
            component = "|".join(
                sorted(
                    (
                        f"{patient.source_system}:{patient.patient_id}",
                        f"{counterpart.source_system}:{counterpart.patient_id}",
                    )
                )
            )
            status = "AUTO_MATCHED" if link_source == "AUTO" else "HUMAN_MATCHED"
        else:
            component = f"{patient.source_system}:{patient.patient_id}"
            case_id = ""
            if patient.patient_id in pending_patients:
                status = "REVIEW_PENDING"
            elif patient.patient_id in rejected_patients:
                status = "REVIEW_REJECTED"
            else:
                status = "UNMATCHED"
        master_id = _token(master_key, "MP", component, length=24)
        previous_component = component_tokens.setdefault(master_id, component)
        if previous_component != component:
            raise IdentityError("A master identifier collision occurred; rotate the key.")
        master_rows.append(
            {
                "master_patient_id": master_id,
                "patient_id": patient.patient_id,
                "source_system": patient.source_system,
                "link_status": status,
                "match_case_id": case_id,
                "rule_version": selected.rule_version,
            }
        )

    output_root = Path(output_dir).expanduser().resolve()
    patient_master_path = output_root / "patient_master.csv"
    match_decisions_path = output_root / "match_decisions.csv"
    review_queue_path = output_root / "review_queue.csv"
    audit_path = output_root / "identity_audit.json"
    planned = (
        patient_master_path, match_decisions_path, review_queue_path, audit_path
    )
    if source_path in planned:
        raise IdentityError("Identity outputs must not overwrite the Silver input.")
    if not overwrite and any(path.exists() for path in planned):
        raise IdentityError("An identity output exists; use overwrite=True intentionally.")

    _write_csv(patient_master_path, MASTER_FIELDS, master_rows)
    _write_csv(match_decisions_path, DECISION_FIELDS, decision_rows)
    _write_csv(review_queue_path, REVIEW_FIELDS, review_rows)

    timestamp = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    human_accepted = sum(
        1
        for review in supplied_decisions.values()
        if review["decision"] == "ACCEPT"
    )
    unique_master_patients = len({row["master_patient_id"] for row in master_rows})
    linked_source_rows = len(accepted_links)
    result = IdentityResult(
        rule_version=selected.rule_version,
        run_id=run_id or str(uuid.uuid4()),
        created_at_utc=timestamp.isoformat().replace("+00:00", "Z"),
        input_patients=len(patients),
        source_counts={"LG": len(lg), "RS": len(rs)},
        candidate_pairs_generated=len(generated_pairs),
        auto_matches=len(auto_matches),
        human_accepted_matches=human_accepted,
        review_candidates=len(review_candidates),
        review_status_counts=dict(sorted(review_status_counts.items())),
        master_patient_rows=len(master_rows),
        unique_master_patients=unique_master_patients,
        linked_source_rows=linked_source_rows,
        review_pending_source_rows=len(pending_patients),
        unlinked_source_rows=len(patients) - linked_source_rows,
        auto_rule_counts=dict(sorted(auto_rule_counts.items())),
        review_rule_counts=dict(sorted(review_rule_counts.items())),
        patient_master_path=str(patient_master_path),
        match_decisions_path=str(match_decisions_path),
        review_queue_path=str(review_queue_path),
        audit_path=str(audit_path),
    )
    audit = {
        **asdict(result),
        "input_file": source_path.name,
        "input_sha256": _sha256(source_path),
        "key_fingerprint": hashlib.sha256(master_key).hexdigest()[:16],
        "low_confidence_pairs_not_queued": (
            len(generated_pairs) - len(auto_matches) - len(review_candidates)
        ),
        "one_to_one_constraint_passed": len(accepted_links) == 2 * (
            len(auto_matches) + human_accepted
        ),
        "scope_exclusions": [
            "readmission_labels", "feature_engineering", "readmission_analytics"
        ],
    }
    _write_json(audit_path, audit)
    return result


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build PATIENTRA patient_master and human review queue."
    )
    parser.add_argument("--patients", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("data/matching"))
    parser.add_argument("--review-decisions", type=Path)
    parser.add_argument(
        "--key-env", default="PATIENTRA_MATCH_KEY",
        help="Environment variable containing a 32+ character HMAC key.",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    secret = os.environ.get(args.key_env)
    if secret is None:
        parser.error(f"Set the {args.key_env} environment variable before matching.")
    try:
        result = resolve_identities(
            args.patients,
            args.output_dir,
            secret.encode("utf-8"),
            review_decisions=args.review_decisions,
            overwrite=args.overwrite,
        )
    except IdentityError as exc:
        parser.error(str(exc))
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

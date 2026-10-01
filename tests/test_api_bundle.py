"""Approved aggregate transfer, governance lineage and hosted-mode controls."""
import hashlib
import json
import sqlite3
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from patientra.api.app import cloud_main, create_app
from patientra.api.bundle import export_bundle, read_bundle
from patientra.api.snapshot import SnapshotUnavailable
from patientra.serving.store import publish
from test_api import AUTH, PUBLISHED, TOKEN
from test_serving import _release


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def release(tmp_path):
    args = _release(tmp_path)
    publish(*args, now=PUBLISHED)
    bundle = tmp_path / "approved.json"
    digest = export_bundle(args[-1], bundle)
    return args, bundle, digest


def test_bundle_contains_only_released_fields_and_supports_http(release):
    args, bundle, digest = release
    text = bundle.read_text()
    assert "Riverside Specialist" not in text
    assert "suppression_reason" not in text and "database" not in text
    assert str(args[-1]) not in text
    client = TestClient(create_app(token=TOKEN, release_bundle=bundle, bundle_sha256=digest))
    for path in ("/ready", "/api/v1/overall", "/api/v1/breakdowns",
                 "/api/v1/pipeline-status", "/api/v1/data-quality"):
        assert client.get(path, headers=AUTH).status_code == 200
        assert client.get(path).status_code == 401
    assert client.get("/api/v1/breakdowns", headers=AUTH).json()["total"] == 1
    result = read_bundle(bundle, digest, now=PUBLISHED + timedelta(days=2))
    assert result.status.current_freshness == "STALE"
    assert result.status.freshness_at_publication == "FRESH"


@pytest.mark.parametrize("change", [
    lambda data: data.update(patient_id="unapproved"),
    lambda data: data["quality"].update(suppressed_rows=99),
    lambda data: data["quality"].update(identity_resolution="reviews_completed", unresolved_identity_reviews=8),
    lambda data: data["breakdowns"].append(data["breakdowns"][0]),
    lambda data: data["breakdowns"][0].update(suppression_reason="primary_small_cell"),
    lambda data: data["breakdowns"][0].update(readmitted_admissions=1),
    lambda data: data["status"].update(release_status="FAIL"),
    lambda data: data["status"].update(gate_sha256="invalid"),
    lambda data: data["status"].update(freshness_at_publication="STALE"),
    lambda data: data["status"].update(published_at_utc="2099-01-01T00:00:00Z"),
])
def test_malformed_even_pinned_bundles_fail_closed(release, change):
    _, bundle, _ = release
    data = json.loads(bundle.read_text())
    change(data)
    bundle.write_text(json.dumps(data))
    client = TestClient(create_app(token=TOKEN, release_bundle=bundle, bundle_sha256=_sha(bundle)))
    response = client.get("/api/v1/overall", headers=AUTH)
    assert response.status_code == 503
    assert response.json() == {"detail": "Approved snapshot unavailable"}


def test_changed_and_missing_bundles_fail_closed(release):
    _, bundle, digest = release
    bundle.write_text(bundle.read_text() + " ")
    with pytest.raises(SnapshotUnavailable):
        read_bundle(bundle, digest)
    bundle.unlink()
    with pytest.raises(SnapshotUnavailable):
        read_bundle(bundle, digest)


def test_existing_or_partial_lineage_export_is_refused(release, tmp_path):
    args, bundle, _ = release
    with pytest.raises(ValueError):
        export_bundle(args[-1], bundle)
    with pytest.raises(ValueError):
        export_bundle(args[-1], tmp_path / "partial.json", identity_audit=tmp_path / "identity.json")


def test_governance_counts_require_local_lineage_and_export_no_identifiers(release, tmp_path):
    args, _, _ = release
    master, gold = tmp_path / "master.csv", tmp_path / "gold.csv"
    master.write_text("opaque synthetic fixture for hash checks")
    gold.write_text("opaque synthetic fixture for hash checks")
    identity, gold_audit = tmp_path / "identity.json", tmp_path / "gold-audit.json"
    identity.write_text(json.dumps({
        "rule_version": "phase3-identity-v1", "one_to_one_constraint_passed": True,
        "patient_master_path": str(master), "input_sha256": "a" * 64,
        "review_status_counts": {"PENDING": 8}, "review_candidates": 8,
        "unique_master_patients": 37,
    }))
    gold_audit.write_text(json.dumps({
        "gold_rows": 45, "patient_master_unique_patients": 37,
        "input_sha256": {"patient_master": _sha(master), "patients": "a" * 64},
    }))
    gate = json.loads(args[3].read_text())
    gate["verified_sha256"]["gold"] = _sha(gold)
    args[3].write_text(json.dumps(gate))
    with sqlite3.connect(args[-1]) as conn:
        conn.execute("UPDATE pipeline_status SET gate_sha256 = ?", (_sha(args[3]),))
    output = tmp_path / "governance.json"
    digest = export_bundle(args[-1], output, identity_audit=identity, patient_master=master,
                           gold_audit=gold_audit, gold=gold, validation=args[3])
    quality = read_bundle(output, digest).quality
    assert quality.identity_resolution == "reviews_unresolved"
    assert quality.unresolved_identity_reviews == 8 and quality.unique_master_patients == 37
    assert str(master) not in output.read_text() and "patient_master_path" not in output.read_text()
    master.write_text("changed synthetic fixture")
    with pytest.raises(ValueError):
        export_bundle(args[-1], tmp_path / "wrong.json", identity_audit=identity,
                      patient_master=master, gold_audit=gold_audit, gold=gold, validation=args[3])


def test_authenticated_rate_limit_has_bounded_state_and_safe_errors(release):
    _, bundle, digest = release
    client = TestClient(create_app(token=TOKEN, release_bundle=bundle,
                                  bundle_sha256=digest, rate_limit_per_minute=2))
    assert client.get("/health").status_code == 401
    assert client.get("/health", headers=AUTH).status_code == 200
    assert client.get("/health", headers=AUTH).status_code == 200
    response = client.get("/health", headers=AUTH)
    assert response.status_code == 429 and response.headers["Retry-After"] == "60"


def test_cloud_entrypoint_uses_bundle_and_platform_port(release, monkeypatch):
    import uvicorn
    _, bundle, digest = release
    monkeypatch.setenv("PATIENTRA_API_RELEASE_BUNDLE", str(bundle))
    monkeypatch.setenv("PATIENTRA_API_BUNDLE_SHA256", digest)
    monkeypatch.setenv("PATIENTRA_API_TOKEN", TOKEN)
    monkeypatch.setenv("PORT", "8081")
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))
    assert cloud_main() == 0
    app, configuration = calls[0]
    assert configuration == {"host": "0.0.0.0", "port": 8081, "access_log": False,
                             "proxy_headers": False, "server_header": False, "limit_concurrency": 20}
    client = TestClient(app, base_url="http://localhost")
    assert client.get("/ready", headers=AUTH).status_code == 200
    assert client.get("/ready", headers={**AUTH, "Host": "untrusted.example"}).status_code == 400


def test_cloud_entrypoint_refuses_sqlite_only_configuration(monkeypatch):
    monkeypatch.delenv("PATIENTRA_API_RELEASE_BUNDLE", raising=False)
    with pytest.raises(SystemExit):
        cloud_main()


def test_ambiguous_release_sources_are_rejected(release):
    args, bundle, digest = release
    with pytest.raises(ValueError):
        create_app(args[-1], token=TOKEN, release_bundle=bundle, bundle_sha256=digest)

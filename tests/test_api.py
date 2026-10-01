"""Phase 8 access, snapshot-integrity and disclosure boundaries."""
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from patientra.api.app import create_app, main
from patientra.api.snapshot import read_snapshot
from patientra.serving.store import publish
from test_serving import _release

TOKEN = "synthetic-test-api-token-000000000000"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
ENDPOINTS = ("/health", "/ready", "/api/v1/overall", "/api/v1/breakdowns",
             "/api/v1/pipeline-status", "/api/v1/data-quality")
PUBLISHED = datetime(2026, 9, 30, 18, tzinfo=timezone.utc)


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _client(path, digest=None):
    return TestClient(create_app(path, token=TOKEN, snapshot_sha256=digest or _digest(path)))


@pytest.fixture
def database(tmp_path):
    args = _release(tmp_path)
    publish(*args, now=PUBLISHED)
    return args[-1]


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_all_endpoints_require_bearer_auth(database, endpoint):
    client = _client(database)
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {TOKEN}"}):
        response = client.get(endpoint, headers=headers)
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert response.headers["Cache-Control"] == "no-store"
        assert TOKEN not in response.text
    assert client.get(endpoint, headers=AUTH).status_code == 200


def test_approved_responses_and_database_remain_read_only(database):
    original = database.read_bytes()
    client = _client(database)
    overall = client.get("/api/v1/overall", headers=AUTH).json()
    assert overall["eligible_admissions"] == 40
    assert overall["readmitted_admissions"] == 20
    page = client.get("/api/v1/breakdowns?dimension=hospital&limit=1", headers=AUTH).json()
    assert page["total"] == 1 and len(page["items"]) == 1
    assert "suppression_reason" not in page["items"][0]
    assert "Riverside Specialist" not in str(page)
    assert client.get("/api/v1/breakdowns?offset=1", headers=AUTH).json()["items"] == []
    assert client.get("/api/v1/breakdowns?dimension=sex", headers=AUTH).json()["total"] == 0
    quality = client.get("/api/v1/data-quality", headers=AUTH).json()
    assert quality == {
        "gold_rows": 45, "eligible_rows": 40, "excluded_rows": 5,
        "breakdown_rows": 2, "released_breakdown_rows": 1, "suppressed_rows": 1,
        "minimum_cell_size": 11, "validation_checks_passed": 13,
        "row_reconciliation": "PASS", "suppression_integrity": "PASS",
        "identity_resolution": "not_assessed", "clinical_accuracy": "not_assessed",
    }
    status = client.get("/api/v1/pipeline-status", headers=AUTH).json()
    assert status["release_status"] == "PASS"
    assert status["freshness_at_publication"] == "FRESH"
    assert "database" not in status and "gold_sha256" not in status
    assert database.read_bytes() == original
    assert client.post("/api/v1/overall", headers=AUTH, json={"sql": "DROP TABLE overall"}).status_code == 405
    assert database.read_bytes() == original


@pytest.mark.parametrize("query", [
    "dimension=patient_id", "dimension=hospital%27%3BDROP%20TABLE%20overall",
    "limit=0", "limit=101", "offset=-1", "offset=10001", "limit=invalid",
    "sql=SELECT%20*%20FROM%20breakdowns", "database=unapproved",
    "category=unapproved", "limit=1&limit=2", "token=unapproved",
])
def test_unapproved_and_unbounded_queries_are_rejected_without_echo(database, query):
    response = _client(database).get(f"/api/v1/breakdowns?{query}", headers=AUTH)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid query parameters"}


def test_non_breakdown_routes_reject_queries(database):
    assert _client(database).get("/api/v1/overall?dimension=hospital", headers=AUTH).status_code == 422
    assert _client(database).get("/health?token=unapproved", headers=AUTH).status_code == 422


@pytest.mark.parametrize("path", ["/redoc", "/api/v1/breakdowns/", "/api/v1/patients"])
def test_no_extra_query_surfaces(database, path):
    assert _client(database).get(path, headers=AUTH).status_code == 404


def test_swagger_exposes_contract_without_release_data_or_credentials(database):
    client = _client(database)
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert '"persistAuthorization": false' in docs.text
    assert '"validatorUrl": null' in docs.text
    schema_response = client.get("/openapi.json")
    assert schema_response.status_code == 200
    schema = schema_response.json()
    assert set(schema["paths"]) == set(ENDPOINTS)
    assert schema["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    for path in ENDPOINTS:
        assert schema["paths"][path]["get"]["security"] == [{"HTTPBearer": []}]
        assert client.get(path).status_code == 401
    assert TOKEN not in docs.text + schema_response.text
    assert str(database) not in docs.text + schema_response.text
    assert docs.headers["Cache-Control"] == "no-store"


def test_missing_and_replaced_snapshots_fail_closed(database):
    client = _client(database)
    original = database.read_bytes()
    database.unlink()
    assert client.get("/health", headers=AUTH).status_code == 200
    for endpoint in ENDPOINTS[1:]:
        response = client.get(endpoint, headers=AUTH)
        assert response.status_code == 503
        assert str(database) not in response.text
    assert not database.exists()  # A missing SQLite path must never create a file.
    database.write_bytes(original + b"tampered")
    assert client.get("/api/v1/overall", headers=AUTH).status_code == 503


@pytest.mark.parametrize("sql", [
    "UPDATE pipeline_status SET release_status='FAIL'",
    "UPDATE pipeline_status SET validation_checks_passed=12",
    "UPDATE pipeline_status SET excluded_rows=999",
    "UPDATE pipeline_status SET suppressed_rows=0",
    "UPDATE pipeline_status SET source_age_seconds=0",
    "UPDATE pipeline_status SET analytics_sha256='invalid'",
    "UPDATE overall SET readmission_rate_pct=99",
    "UPDATE breakdowns SET readmitted_admissions=1 WHERE suppression_reason != ''",
    "UPDATE breakdowns SET eligible_admissions=10 WHERE suppression_reason = ''",
    "UPDATE breakdowns SET dimension='unapproved' WHERE suppression_reason != ''",
    "ALTER TABLE overall ADD COLUMN patient_id TEXT",
    "DELETE FROM overall",
])
def test_invalid_even_operator_pinned_snapshots_are_rejected(database, sql):
    with sqlite3.connect(database) as conn:
        conn.execute(sql)
    response = _client(database).get("/api/v1/overall", headers=AUTH)
    assert response.status_code == 503
    assert response.json() == {"detail": "Approved snapshot unavailable"}


def test_current_freshness_is_recomputed_without_rewriting_publication(database):
    result = read_snapshot(database, _digest(database), now=PUBLISHED + timedelta(days=2))
    assert result.status.freshness_at_publication == "FRESH"
    assert result.status.current_freshness == "STALE"
    assert result.status.current_source_age_seconds == 194400


def test_breakdown_view_cannot_expand_release_surface(database):
    with sqlite3.connect(database) as conn:
        conn.execute("DROP VIEW released_breakdowns")
        conn.execute("CREATE VIEW released_breakdowns AS SELECT * FROM breakdowns")
    response = _client(database).get("/api/v1/breakdowns", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_corrupt_pinned_snapshot_returns_safe_error(database):
    database.write_bytes(b"not a database")
    assert _client(database).get("/ready", headers=AUTH).status_code == 503


@pytest.mark.parametrize("token,digest", [("", "a" * 64), ("short", "a" * 64),
                                         (" " * 32, "a" * 64), (TOKEN, "not-a-hash")])
def test_invalid_configuration_cannot_start(tmp_path, token, digest):
    with pytest.raises(ValueError):
        create_app(tmp_path / "missing.sqlite", token=token, snapshot_sha256=digest)


def test_cli_binds_only_loopback_and_disables_access_logging(database, monkeypatch):
    import uvicorn

    monkeypatch.setenv("PATIENTRA_API_TOKEN", TOKEN)
    monkeypatch.setenv("PATIENTRA_API_DATABASE", str(database))
    monkeypatch.setenv("PATIENTRA_API_SNAPSHOT_SHA256", _digest(database))
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    assert main(["--port", "8123"]) == 0
    assert calls == [{"host": "127.0.0.1", "port": 8123, "access_log": False}]

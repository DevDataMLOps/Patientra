"""The synthetic product must preserve authentication and disclosure boundaries."""
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from patientra.api.snapshot import SnapshotUnavailable
from patientra.prototype.app import create_prototype_app, read_evidence
from patientra.prototype.demo import prepare_demo

TOKEN = "local-synthetic-test-token-0000000000000"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
REPOSITORY = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def release(tmp_path_factory):
    return prepare_demo(REPOSITORY, tmp_path_factory.mktemp("demo") / "run")


def client(release):
    return TestClient(create_prototype_app(**{key: release[key] for key in
        ("bundle_path", "bundle_sha256", "evidence_path", "evidence_sha256")}, token=TOKEN))


def test_four_view_demo_uses_actual_governed_synthetic_results(release):
    api = client(release)
    response = api.get("/api/v1/prototype", headers=AUTH)
    assert response.status_code == 200
    data = response.json()
    assert data["data_mode"] == "SYNTHETIC_ONLY"
    assert len(data["validation_checks"]) == 13
    assert data["quarantine"] == {"patients": 1, "admissions": 1, "lab_results": 1}
    assert data["gold_rows"] == 200 and data["unresolved_identity_reviews"] == 1
    assert data["ml"]["split"]["shared_master_patients"] == 0
    assert data["ml"]["split"]["pending_identity_excluded_admissions"] == 2
    assert data["ml"]["release_status"] == "DEMONSTRATION_ONLY"
    assert "FICTIONALDEMO" not in response.text and "IDENTITYREVIEW" not in response.text
    assert "patient_id" not in response.text and "lab_id" not in response.text
    quality = api.get("/api/v1/data-quality", headers=AUTH).json()
    assert quality["unresolved_identity_reviews"] == 1 and quality["suppressed_rows"] > 0
    assert quality["validation_checks_passed"] == 13
    assert api.get("/api/v1/predict", headers=AUTH).status_code == 404


def test_prototype_preserves_base_security_and_public_shell(release):
    api = client(release)
    assert api.get("/api/v1/prototype").status_code == 401
    assert api.get("/api/v1/prototype", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert api.get("/api/v1/prototype?patient_id=private", headers=AUTH).status_code == 422
    for path in ("/prototype", "/prototype.css", "/prototype.js"):
        response = api.get(path)
        assert response.status_code == 200
        assert "connect-src 'self'" in response.headers["Content-Security-Policy"]
        assert response.headers["Cache-Control"] == "no-store"
        assert TOKEN not in response.text
        assert release["run_id"] not in response.text
    script = api.get("/prototype.js").text
    assert "localStorage" not in script and "sessionStorage" not in script and "innerHTML" not in script
    assert "authorization" not in api.get("/prototype").text.lower().split("href=")[-1]
    assert api.get("/prototype/../../raw/patients.csv", headers=AUTH).status_code == 404


def test_evidence_tampering_and_extra_patient_fields_fail_closed(release, tmp_path):
    payload = json.loads(Path(release["evidence_path"]).read_text())
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(SnapshotUnavailable):
        read_evidence(path, release["evidence_sha256"], release["bundle_path"], release["bundle_sha256"])
    payload["patient_records"] = [{"patient_id": "private"}]
    path.write_text(json.dumps(payload))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(SnapshotUnavailable):
        read_evidence(path, digest, release["bundle_path"], release["bundle_sha256"])
    payload.pop("patient_records")
    payload["bundle_sha256"] = "a" * 64
    path.write_text(json.dumps(payload))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(SnapshotUnavailable):
        read_evidence(path, digest, release["bundle_path"], release["bundle_sha256"])


def test_unavailable_release_clears_backend_and_shared_rate_limit(release, tmp_path):
    path = tmp_path / "evidence.json"
    path.write_bytes(Path(release["evidence_path"]).read_bytes())
    changed = {**release, "evidence_path": str(path)}
    api = client(changed)
    path.write_text("changed")
    assert api.get("/api/v1/prototype", headers=AUTH).status_code == 503
    assert api.get("/prototype").status_code == 200
    api = client(release)
    for _ in range(60):
        assert api.get("/health", headers=AUTH).status_code == 200
    assert api.get("/api/v1/prototype", headers=AUTH).status_code == 429


def test_hosted_shell_health_and_authenticated_data(release, tmp_path):
    path = tmp_path / "evidence.json"
    path.write_bytes(Path(release["evidence_path"]).read_bytes())
    app = create_prototype_app(**{**{key: release[key] for key in
        ("bundle_path", "bundle_sha256", "evidence_path", "evidence_sha256")}, "evidence_path": str(path)}, token=TOKEN, hosted=True)
    api = TestClient(app)
    shell = api.get("/")
    assert shell.status_code == 200 and "Hosted synthetic prototype" in shell.text
    assert "Paste hosted demo token" in shell.text and TOKEN not in shell.text
    assert api.get("/healthz").json() == {"status": "ready", "data_mode": "SYNTHETIC_ONLY"}
    assert api.get("/api/v1/prototype").status_code == 401
    assert api.get("/api/v1/prototype", headers=AUTH).status_code == 200
    path.write_text("changed")
    assert api.get("/healthz").status_code == 503
    assert api.get("/api/v1/prototype", headers=AUTH).status_code == 503


def test_hosting_config_restricts_files_and_token_binding(monkeypatch):
    from patientra.prototype.hosting import load_config, main
    from patientra.prototype.app import read_evidence
    config = load_config(REPOSITORY / "demo_release")
    assert read_evidence(config["evidence_path"], config["evidence_sha256"], config["bundle_path"], config["bundle_sha256"]).data_mode == "SYNTHETIC_ONLY"
    monkeypatch.chdir(REPOSITORY)
    monkeypatch.delenv("PATIENTRA_HOSTED_DEMO_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        main()
    monkeypatch.setenv("PATIENTRA_HOSTED_DEMO_TOKEN", TOKEN)
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "patientra-prototype.onrender.com")
    monkeypatch.setenv("PORT", "10000")
    called = {}
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: called.update(app=app, **kwargs))
    main()
    assert called["host"] == "0.0.0.0" and called["port"] == 10000
    assert called["access_log"] is False
    api = TestClient(called["app"])
    assert api.get("/healthz", headers={"Host": "patientra-prototype.onrender.com"}).status_code == 200
    assert api.get("/healthz", headers={"Host": "attacker.example"}).status_code == 400

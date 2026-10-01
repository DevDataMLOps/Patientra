"""Dashboard delivery must not widen the aggregate disclosure boundary."""
from fastapi.testclient import TestClient

from patientra.api.app import create_app
from test_api import TOKEN, AUTH, ENDPOINTS, _digest, database


def test_public_shell_keeps_data_authenticated_and_constrains_browser(database):
    client = TestClient(create_app(database, token=TOKEN, snapshot_sha256=_digest(database)))
    for path in ("/", "/dashboard", "/dashboard.css", "/dashboard.js"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        assert "connect-src 'self'" in response.headers["Content-Security-Policy"]
        assert TOKEN not in response.text and str(database) not in response.text
    for path in ENDPOINTS:
        assert client.get(path).status_code == 401
        assert client.get(path, headers=AUTH).status_code == 200
    assert set(client.get("/openapi.json").json()["paths"]) == set(ENDPOINTS)
    assert client.get("/dashboard/../../data/raw/patients.csv").status_code == 404


def test_shell_survives_unavailable_release_without_embedding_values(database):
    client = TestClient(create_app(database, token=TOKEN, snapshot_sha256=_digest(database)))
    database.unlink()
    assert client.get("/dashboard").status_code == 200
    assert client.get("/api/v1/overall", headers=AUTH).status_code == 503
    assert "548" not in client.get("/dashboard").text

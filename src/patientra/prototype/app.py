"""Optional four-view prototype; base aggregate API protections remain intact."""
import hashlib
import hmac
from pathlib import Path
from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse
from patientra.api.app import create_app
from patientra.api.bundle import read_bundle
from patientra.api.dashboard import CSP
from patientra.api.snapshot import SnapshotUnavailable
from patientra.prototype.models import DemoEvidence

ASSETS = Path(__file__).with_name("web")


def read_evidence(path, expected_sha256, bundle_path, bundle_sha256):
    try:
        with Path(path).open("rb") as handle:
            content = handle.read(128 * 1024 + 1)
        if len(content) > 128 * 1024 or not hmac.compare_digest(hashlib.sha256(content).hexdigest(), expected_sha256):
            raise ValueError("Unapproved prototype evidence")
        evidence = DemoEvidence.model_validate_json(content)
        snapshot = read_bundle(Path(bundle_path), bundle_sha256)
        if (evidence.bundle_sha256 != bundle_sha256 or evidence.gold_rows != snapshot.quality.gold_rows
                or evidence.unresolved_identity_reviews != snapshot.quality.unresolved_identity_reviews
                or evidence.master_patients != snapshot.quality.unique_master_patients):
            raise ValueError("Prototype and aggregate bundle differ")
        return evidence
    except (OSError, ValueError, TypeError, SnapshotUnavailable):
        raise SnapshotUnavailable("Approved prototype evidence unavailable") from None


def create_prototype_app(*, bundle_path, bundle_sha256, evidence_path, evidence_sha256, token):
    read_evidence(evidence_path, evidence_sha256, bundle_path, bundle_sha256)
    app = create_app(token=token, release_bundle=bundle_path, bundle_sha256=bundle_sha256,
                     rate_limit_per_minute=60)
    app.title = "PATIENTRA synthetic live prototype"
    app.description = ("Governed synthetic-data demonstration. Aggregate-only bearer-authenticated API. "
                       "DEMONSTRATION_ONLY: no clinical decision support or prediction endpoint.")
    @app.get("/api/v1/prototype", response_model=DemoEvidence, dependencies=[Depends(app.state.authenticate)])
    def evidence():
        try:
            return read_evidence(evidence_path, evidence_sha256, bundle_path, bundle_sha256)
        except SnapshotUnavailable:
            raise HTTPException(503, "Approved prototype evidence unavailable") from None

    def asset(name, media_type):
        return FileResponse(ASSETS / name, media_type=media_type, headers={
            "Content-Security-Policy": CSP, "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"})

    @app.get("/prototype", include_in_schema=False)
    def page():
        return asset("prototype.html", "text/html")

    @app.get("/prototype.css", include_in_schema=False)
    def styles():
        return asset("prototype.css", "text/css")

    @app.get("/prototype.js", include_in_schema=False)
    def script():
        return asset("prototype.js", "application/javascript")

    return app

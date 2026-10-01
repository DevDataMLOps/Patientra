"""Authenticated, bounded aggregate endpoints for a local approved snapshot."""
import argparse
import hmac
import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from patientra.api.models import BreakdownPage, DataQuality, Dimension, Overall, PipelineStatus
from patientra.api.bundle import read_bundle
from patientra.api.snapshot import Snapshot, SnapshotUnavailable, read_snapshot


def create_app(database=None, *, token=None, snapshot_sha256=None, release_bundle=None,
               bundle_sha256=None, rate_limit_per_minute=None):
    """Configure trusted operator inputs; never accept a path, hash or SQL via HTTP."""
    secret = token if token is not None else os.environ.get("PATIENTRA_API_TOKEN", "")
    bundle_path = release_bundle or os.environ.get("PATIENTRA_API_RELEASE_BUNDLE")
    if bundle_path and database is not None:
        raise ValueError("Configure one approved release source")
    if bundle_path:
        digest = bundle_sha256 if bundle_sha256 is not None else os.environ.get("PATIENTRA_API_BUNDLE_SHA256", "")
    else:
        digest = snapshot_sha256 if snapshot_sha256 is not None else os.environ.get("PATIENTRA_API_SNAPSHOT_SHA256", "")
    if not isinstance(secret, str) or len(secret) < 32 or not secret.isascii() or any(c.isspace() for c in secret):
        raise ValueError("Configure PATIENTRA_API_TOKEN with at least 32 non-whitespace ASCII characters")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Configure an approved release SHA-256 digest")
    if rate_limit_per_minute is not None and (type(rate_limit_per_minute) is not int or not 1 <= rate_limit_per_minute <= 1000):
        raise ValueError("Rate limit must be between 1 and 1000 requests per minute")
    path = Path(bundle_path or database or os.environ.get("PATIENTRA_API_DATABASE", "outputs/phase7/patientra_serving.sqlite"))
    reader = read_bundle if bundle_path else read_snapshot
    requests = deque()
    rate_lock = threading.Lock()
    app = FastAPI(title="PATIENTRA aggregate API", version="phase8-api-v1",
                  description="Approved aggregate demonstration API. Use Authorize with your bearer token. "
                  "Eight reconstructed identity reviews remain unresolved; clinical accuracy is not assessed.",
                  docs_url="/docs", redoc_url=None, openapi_url="/openapi.json", redirect_slashes=False,
                  swagger_ui_parameters={"persistAuthorization": False, "validatorUrl": None})
    bearer = HTTPBearer(auto_error=False)

    def authenticate(request: Request,
                     credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        supplied = credentials.credentials if credentials else ""
        if not hmac.compare_digest(supplied.encode("utf-8"), secret.encode("ascii")):
            raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
        if rate_limit_per_minute is not None:
            with rate_lock:
                now = time.monotonic()
                while requests and requests[0] <= now - 60:
                    requests.popleft()
                if len(requests) >= rate_limit_per_minute:
                    raise HTTPException(429, "Request limit exceeded", headers={"Retry-After": "60"})
                requests.append(now)
        allowed = {"dimension", "limit", "offset"} if request.url.path == "/api/v1/breakdowns" else set()
        keys = [key for key, _ in request.query_params.multi_items()]
        if set(keys) - allowed or len(keys) != len(set(keys)):
            raise HTTPException(422, "Invalid query parameters")

    def snapshot(_auth=Depends(authenticate)) -> Snapshot:
        try:
            return reader(path, digest)
        except SnapshotUnavailable:
            raise HTTPException(503, "Approved snapshot unavailable") from None

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, _exc):
        # Default validation responses echo inputs; keep arbitrary supplied values out.
        return JSONResponse(status_code=422, content={"detail": "Invalid query parameters"})

    @app.middleware("http")
    async def response_controls(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/health", dependencies=[Depends(authenticate)])
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready(_snapshot: Annotated[Snapshot, Depends(snapshot)]):
        return {"status": "ready"}

    @app.get("/api/v1/overall", response_model=Overall)
    def overall(data: Annotated[Snapshot, Depends(snapshot)]):
        return data.overall

    @app.get("/api/v1/breakdowns", response_model=BreakdownPage)
    def breakdowns(data: Annotated[Snapshot, Depends(snapshot)], dimension: Dimension | None = None,
                   limit: Annotated[int, Query(ge=1, le=100)] = 100,
                   offset: Annotated[int, Query(ge=0, le=10000)] = 0):
        rows = [row for row in data.breakdowns if dimension is None or row.dimension == dimension]
        return BreakdownPage(items=rows[offset:offset + limit], total=len(rows), limit=limit, offset=offset)

    @app.get("/api/v1/pipeline-status", response_model=PipelineStatus)
    def pipeline_status(data: Annotated[Snapshot, Depends(snapshot)]):
        return data.status

    @app.get("/api/v1/data-quality", response_model=DataQuality, response_model_exclude_none=True)
    def data_quality(data: Annotated[Snapshot, Depends(snapshot)]):
        return data.quality

    return app


def main(argv=None):
    parser = argparse.ArgumentParser(description="Serve approved PATIENTRA aggregates on loopback")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    try:
        app = create_app()
    except ValueError as exc:
        parser.error(str(exc))
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)
    return 0


def cloud_main():
    """Provider HTTPS terminates outside the container; serve only approved bundles."""
    if not os.environ.get("PATIENTRA_API_RELEASE_BUNDLE"):
        raise SystemExit("Hosted mode requires an approved aggregate release bundle")
    try:
        port = int(os.environ.get("PORT", "8080"))
        if not 1 <= port <= 65535:
            raise ValueError
        app = create_app(rate_limit_per_minute=60)
    except ValueError:
        raise SystemExit("Invalid hosted API configuration") from None
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    allowed_hosts = ["*.run.app", "localhost", "127.0.0.1"]
    render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    if render_host:
        import re
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.onrender\.com", render_host):
            raise SystemExit("Invalid Render hostname")
        allowed_hosts = [render_host, "localhost", "127.0.0.1"]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port, access_log=False, proxy_headers=False,
                server_header=False, limit_concurrency=20)
    return 0

"""Host only the checked-in approved synthetic aggregate snapshot."""
import json
import os
import re
from pathlib import Path

from starlette.middleware.trustedhost import TrustedHostMiddleware
from patientra.prototype.app import create_prototype_app
from patientra.api.snapshot import SnapshotUnavailable


def load_config(root):
    root = Path(root)
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    if set(config) != {"bundle_file", "bundle_sha256", "evidence_file", "evidence_sha256"}:
        raise ValueError("Invalid hosted synthetic release configuration")
    if config["bundle_file"] != "approved-aggregates.json" or config["evidence_file"] != "prototype-evidence.json":
        raise ValueError("Invalid hosted release filenames")
    for key in ("bundle_sha256", "evidence_sha256"):
        if not isinstance(config[key], str) or not re.fullmatch(r"[0-9a-f]{64}", config[key]):
            raise ValueError("Invalid approved release digest")
    return {"bundle_path": root / config["bundle_file"], "bundle_sha256": config["bundle_sha256"],
            "evidence_path": root / config["evidence_file"], "evidence_sha256": config["evidence_sha256"]}


def main():
    repository = Path.cwd()
    stage = "release_config"
    try:
        config = load_config(repository / "demo_release")
        stage = "approved_snapshot"
        app = create_prototype_app(**config, token=os.environ.get("PATIENTRA_HOSTED_DEMO_TOKEN", ""), hosted=True)
        stage = "render_hostname"
        hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.onrender\.com", hostname):
            raise ValueError("Invalid Render hostname")
        stage = "port"
        port = int(os.environ.get("PORT", "10000"))
        if not 1 <= port <= 65535:
            raise ValueError("Invalid port")
    except (OSError, ValueError, SnapshotUnavailable) as exc:
        raise SystemExit(f"Hosted synthetic prototype startup failed at {stage} ({type(exc).__name__}); no values logged") from None
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[hostname, "localhost", "127.0.0.1"])
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port, access_log=False, proxy_headers=False,
                server_header=False, limit_concurrency=20)


if __name__ == "__main__":
    main()

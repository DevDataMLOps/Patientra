"""Prepare a fresh synthetic demo and serve on loopback; never deploy cloud jobs."""
import argparse
import json
import secrets
import sys
import uuid
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))
from patientra.prototype.demo import prepare_demo
from patientra.prototype.app import create_prototype_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--config", type=Path, help="Reuse an existing approved local demo config")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Invalid port")
    if args.config:
        config_path = args.config.resolve()
        config = json.loads(config_path.read_text())
    else:
        root = REPOSITORY / "work/prototype" / str(uuid.uuid4())
        config = prepare_demo(REPOSITORY, root)
        config_path = root / "config.json"
        config_path.write_text(json.dumps(config, indent=2) + "\n")
    # This local demo never reuses an existing Render/production API credential.
    secret = secrets.token_urlsafe(36)
    token_path = config_path.with_name("local-demo-token.txt")
    if token_path.exists():
        secret = token_path.read_text().strip()
    else:
        token_path.write_text(secret, encoding="ascii")
        try:
            token_path.chmod(0o600)
        except OSError:
            pass
    app = create_prototype_app(**{key: config[key] for key in ("bundle_path", "bundle_sha256", "evidence_path", "evidence_sha256")}, token=secret)
    print(json.dumps({"prototype_url": f"http://127.0.0.1:{args.port}/prototype", "config": str(config_path),
                      "token_file": str(token_path), "run_id": config["run_id"], "data_mode": "SYNTHETIC_ONLY"}), flush=True)
    if not args.prepare_only:
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, server_header=False)


if __name__ == "__main__":
    main()

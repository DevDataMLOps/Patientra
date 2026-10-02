# Databricks notebook source
# MAGIC %md
# MAGIC # PATIENTRA: validated Medallion batch and Phase 10
# MAGIC Owner-controlled, bounded case-study execution. Patient rows and individual
# MAGIC predictions are never displayed. Each run creates new Delta snapshots; the
# MAGIC release registry is written only after all validation gates pass.

# COMMAND ----------
# MAGIC %pip install scikit-learn==1.7.2

# COMMAND ----------
dbutils.library.restartPython()

# COMMAND ----------
import importlib.util
import json
import secrets
import shutil
import sys
import tempfile
import uuid
from datetime import date
from pathlib import Path

for name, default in {
    "repository_root": "", "catalog": "patientra_dev", "source_commit": "",
    "observation_end": "2025-12-31", "cutoff": "2025-01-01", "demo": "true",
    "raw_dir": "/Volumes/patientra/bronze/raw", "secret_scope": "patientra",
    "secret_key": "matching-hmac", "experiment_path": "",
}.items():
    dbutils.widgets.text(name, default)

repository = Path(dbutils.widgets.get("repository_root"))
if not (repository / "src/patientra").is_dir():
    raise RuntimeError("Set repository_root to the deployed bundle or Git folder.")
sys.path.insert(0, str(repository / "src"))

from patientra.databricks.pipeline import run_pipeline, verify_run
from patientra.databricks.delta import identifier, publish_snapshots

catalog = identifier(dbutils.widgets.get("catalog"))
demo_setting = dbutils.widgets.get("demo")
if demo_setting not in {"true", "false"}:
    raise RuntimeError("demo must be true or false.")
demo_mode = demo_setting == "true"
if demo_mode and not catalog.endswith("_dev"):
    raise RuntimeError("Synthetic smoke runs must use a separate development catalog.")
run_id = str(uuid.uuid4())
volume_root = Path(f"/Volumes/{catalog}/bronze/runs")
persisted = volume_root / run_id

# COMMAND ----------
# Creation requires the maintainer's existing catalog privileges. No grants are
# widened here. Administrators must inspect inherited permissions before prod.
spark.sql(f"CREATE CATALOG IF NOT EXISTS {catalog}")
for schema in ("bronze", "silver", "gold", "quarantine", "ml"):
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.bronze.runs")

# COMMAND ----------
try:
    with tempfile.TemporaryDirectory(prefix="patientra-") as temporary:
        local = Path(temporary)
        if demo_mode:
            spec = importlib.util.spec_from_file_location("patientra_demo", repository / "scripts/generate_databricks_demo.py")
            generator = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(generator)
            raw = generator.generate(local / "raw")
            # A demo key is never used for hospital deliveries or persisted.
            master_key = secrets.token_bytes(32)
        else:
            raw = Path(dbutils.widgets.get("raw_dir"))
            master_key = dbutils.secrets.get(dbutils.widgets.get("secret_scope"),
                                            dbutils.widgets.get("secret_key")).encode()
        try:
            run_pipeline(raw, local / "run", repository, master_key,
                         date.fromisoformat(dbutils.widgets.get("observation_end")),
                         cutoff=date.fromisoformat(dbutils.widgets.get("cutoff")),
                         source_commit=dbutils.widgets.get("source_commit"), run_id=run_id)
        except Exception:
            # Retain partial evidence under the same protected volume; it has no
            # valid release and is never added to the registry.
            if (local / "run").exists():
                shutil.copytree(local / "run", persisted, dirs_exist_ok=False)
            raise
        del master_key
        # FUSE storage uses ordinary copies, not unsupported atomic rename calls.
        shutil.copytree(local / "run", persisted, dirs_exist_ok=False)
    verify_run(persisted)
except Exception:
    raise RuntimeError("PATIENTRA processing failed; no release was published. Inspect protected run evidence.") from None

# COMMAND ----------
import mlflow
import mlflow.sklearn

try:
    report = json.loads((persisted / "ml/readmission_ml.json").read_text())
    mlflow.sklearn.autolog(disable=True)
    experiment = dbutils.widgets.get("experiment_path")
    if experiment:
        mlflow.set_experiment(experiment)
    with mlflow.start_run(run_name=f"patientra-{run_id}") as experiment_run:
        mlflow.set_tags({"patientra.run_id": run_id, "release_status": "DEMONSTRATION_ONLY",
                         "source_commit": dbutils.widgets.get("source_commit"),
                         "data_mode": "synthetic_smoke" if demo_mode else "approved_delivery"})
        mlflow.log_params(report["configuration"])
        for model, values in report["evaluation"].items():
            mlflow.log_metrics({f"{model}.{key}": value for key, value in values.items()
                                if isinstance(value, (float, int)) and not isinstance(value, bool)})
        mlflow.log_dict(report, "aggregate_readmission_ml.json")
    release = publish_snapshots(spark, persisted, catalog)
except Exception:
    raise RuntimeError("PATIENTRA publication failed; inspect protected evidence and registry before rerunning.") from None

# COMMAND ----------
# Aggregate result only. No display() of Bronze/Silver/Gold patient rows.
dbutils.notebook.exit(json.dumps({"run_id": run_id, "status": release["status"],
                                 "validation_checks_passed": release["validation_checks_passed"],
                                 "delta_snapshot_count": len(release["tables"]),
                                 "mlflow_run_id": experiment_run.info.run_id}))

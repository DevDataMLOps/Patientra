"""Publish immutable Delta snapshots after file and semantic validation.

No Spark dependency is required for local pipeline tests. This adapter runs on
Databricks. The release registry is written last; failed snapshots remain unlisted.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from patientra.databricks.pipeline import PipelineError, verify_run


def publication_error_details(error, stage, run_id):
    """Return classifications only; never log messages, parameters, or tracebacks."""
    if stage not in {"mlflow", "delta_publication"}:
        raise ValueError("Invalid publication stage.")
    if not re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", run_id):
        raise ValueError("Invalid run UUID.")
    details = {"stage": stage, "run_id": run_id}
    kind = type(error).__name__
    details["exception_type"] = kind if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", kind) else "Exception"
    for key, methods in (("error_condition", ("getCondition", "getErrorClass")),
                         ("sql_state", ("getSqlState",))):
        for method in methods:
            try:
                value = getattr(error, method)()
            except Exception:
                continue
            pattern = r"[A-Z][A-Z0-9_.]{0,127}" if key == "error_condition" else r"[A-Z0-9]{5}"
            if isinstance(value, str) and re.fullmatch(pattern, value):
                details[key] = value
                break
    return details


def identifier(value):
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value):
        raise PipelineError("Invalid Unity Catalog identifier.")
    return value


def snapshot_plan(root, catalog, run_id):
    catalog = identifier(catalog)
    suffix = "r" + run_id.replace("-", "")
    identifier(suffix)
    root = Path(root)
    plan = []
    for layer, directory in (("bronze", "bronze"), ("silver", "silver"),
                             ("silver", "identity"), ("gold", "gold"),
                             ("gold", "analytics"), ("quarantine", "quarantine")):
        for path in sorted((root / directory).rglob("*.csv")):
            name = identifier(path.relative_to(root / directory).as_posix()
                              .replace("/", "_").replace(".", "_")[:-4])
            plan.append((path, f"{catalog}.{layer}.{name}_{suffix}"))
    return plan


def publish_snapshots(spark, root, catalog):
    from pyspark.sql import functions as F
    from pyspark.sql.types import StringType, StructField, StructType

    root = Path(root)
    manifest = verify_run(root)
    catalog = identifier(catalog)
    plan = snapshot_plan(root, catalog, manifest["run_id"])
    report_table = f"{catalog}.ml.report_r{manifest['run_id'].replace('-', '')}"
    if any(spark.catalog.tableExists(name) for _, name in plan) or spark.catalog.tableExists(report_table):
        raise PipelineError("Run snapshots already exist; rerun with a new ID.")
    registry = f"{catalog}.gold.release_manifests"
    if spark.catalog.tableExists(registry):
        if spark.table(registry).filter(F.col("run_id") == manifest["run_id"]).limit(1).count():
            raise PipelineError("Run is already published.")
    tables = {}
    for path, name in plan:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            fields = next(reader)
            expected = sum(1 for _ in reader)
        schema = StructType([StructField(field, StringType(), True) for field in fields])
        frame = (spark.read.schema(schema).option("header", True)
                 .option("multiLine", True).option("mode", "FAILFAST")
                 .option("quote", '"').option("escape", '"')
                 .option("nullValue", "\u0000").option("emptyValue", "").csv(str(path)))
        if frame.count() != expected:
            raise PipelineError("Spark CSV count differs from validated artifact.")
        # Strings preserve reviewed CSV contracts, including blank censored labels.
        # Spark Connect serializes the canonical "error" mode across runtimes.
        frame.write.format("delta").mode("error").saveAsTable(name)
        saved = spark.table(name)
        if saved.columns != fields or saved.count() != expected:
            raise PipelineError("Delta snapshot reconciliation failed.")
        if frame.exceptAll(saved).limit(1).count() or saved.exceptAll(frame).limit(1).count():
            raise PipelineError("Delta values differ from validated CSV.")
        tables[path.relative_to(root).as_posix()] = {"table": name, "rows": expected}
    ml_json = (root / "ml/readmission_ml.json").read_text(encoding="utf-8")
    spark.createDataFrame([(manifest["run_id"], ml_json)], "run_id string, report_json string").write.format(
        "delta").mode("error").saveAsTable(report_table)
    if spark.table(report_table).filter((F.col("run_id") == manifest["run_id"])
                                       & (F.col("report_json") == ml_json)).count() != 1:
        raise PipelineError("ML report snapshot reconciliation failed.")
    tables["ml/readmission_ml.json"] = {"table": report_table, "rows": 1}
    verify_run(root)
    release = {**manifest, "tables": tables}
    spark.createDataFrame([(manifest["run_id"], manifest["source_commit"], manifest["created_at_utc"],
                           "VALIDATED_DEMONSTRATION", json.dumps(release, sort_keys=True))],
                          "run_id string, source_commit string, created_at_utc string, status string, manifest_json string"
                          ).write.format("delta").mode("append").saveAsTable(registry)
    return release

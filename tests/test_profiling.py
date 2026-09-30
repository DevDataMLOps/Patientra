import json
from pathlib import Path

from patientra.profiling import profile_csv


def test_profile_is_aggregate_only(tmp_path: Path) -> None:
    secret = "SYNTHETIC-SECRET-NAME"
    source = tmp_path / "patients.csv"
    source.write_text(
        f"patient_id,name,sex\n001,{secret},F\n001,{secret},F\n002,,M\n",
        encoding="utf-8",
    )

    profile = profile_csv(source)
    serialized = json.dumps(profile)

    assert profile["row_count"] == 3
    assert profile["exact_duplicate_row_count"] == 1
    assert profile["columns"][1] == {
        "name": "name",
        "missing_count": 1,
        "non_missing_distinct_count": 1,
    }
    assert secret not in serialized
    assert "001" not in serialized

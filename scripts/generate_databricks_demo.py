"""Generate fictional contract-complete input for platform smoke testing.

These deliberately patterned data validate mechanics, not model accuracy.
Never replace a hospital delivery or use this to reproduce historical evidence.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
from pathlib import Path

from patientra.transformations.silver import PATIENT_COLUMNS, ADMISSION_COLUMNS, LAB_COLUMNS


def generate(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    patients, admissions, labs = [], [], []
    for number in range(160):
        source = "LG" if number % 2 == 0 else "RS"
        patient_id = f"LG-{number:06d}" if source == "LG" else f"RS{number:05d}"
        patients.append(dict(zip(PATIENT_COLUMNS, [patient_id, source,
            f"FICTIONAL{number}", f"TEST{number}", "1965-01-01",
            "F" if number % 3 else "M", "", "ZZ"])))
        start = date(2024 if number < 80 else 2025, 6, 1)
        hospital = "Lakeside General" if source == "LG" else "Riverside Specialist"
        for stay in range(2 if number % 4 == 0 else 1):
            admit = start + timedelta(days=stay * 15)
            admission_id = f"FICTIONAL-ADM-{number}-{stay}"
            admissions.append(dict(zip(ADMISSION_COLUMNS, [admission_id, patient_id, hospital,
                admit.isoformat(), (admit + timedelta(days=4)).isoformat(), "I50", "home"])))
            labs.append(dict(zip(LAB_COLUMNS, [f"FICTIONAL-LAB-{number}-{stay}", admission_id,
                "glucose", "5.5", "mmol/L", admit.isoformat() + "T12:00:00"])))
    for name, fields, rows in (("patients", PATIENT_COLUMNS, patients),
                               ("admissions", ADMISSION_COLUMNS, admissions),
                               ("lab_results", LAB_COLUMNS, labs)):
        with (output / f"{name}.csv").open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    generate(parser.parse_args().output)

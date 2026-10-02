"""Validate bundle syntax against the official CLI JSON schema (no login)."""
import argparse
import json
from pathlib import Path

import jsonschema
import regex
import yaml

parser = argparse.ArgumentParser()
parser.add_argument("schema", type=Path)
args = parser.parse_args()
schema = json.loads(args.schema.read_text(encoding="utf-8-sig"))
bundle = yaml.safe_load(Path("databricks.yml").read_text())
def unicode_pattern(validator, pattern, instance, schema):
    # The official CLI emits Go Unicode patterns (\p{L}), which Python re
    # cannot parse. regex supports these without weakening schema checks.
    if isinstance(instance, str) and not regex.search(pattern, instance):
        yield jsonschema.ValidationError("Value does not match the CLI pattern")


Validator = jsonschema.validators.extend(jsonschema.Draft202012Validator,
                                         {"pattern": unicode_pattern})
errors = list(Validator(schema).iter_errors(bundle))
for error in errors:
    print("/".join(map(str, error.absolute_path)), error.message)
if errors:
    raise SystemExit(1)
print("Bundle schema valid")

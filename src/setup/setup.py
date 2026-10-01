# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

CATALOG = "patientra"
BRONZE_SCHEMA = "bronze"
RAW_VOLUME = "raw"


# ---------------------------------------------------------
# Create Unity Catalog objects
# ---------------------------------------------------------

# Create catalog
spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}")

# create the schemas in the nugabank catalog
schema_list = ["bronze", "silver", "gold"]

for schema in schema_list:
  spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{schema}")

# create the volume in the bronze layer
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{BRONZE_SCHEMA}.{RAW_VOLUME}")


CATALOG = "patientra"
BRONZE_SCHEMA = "bronze"
VOLUME = "raw"

ADMISSIONS_FILE = f"/Volumes/{CATALOG}/{BRONZE_SCHEMA}/{VOLUME}/admissions.csv"
LAB_RESULTS_FILE = f"/Volumes/{CATALOG}/{BRONZE_SCHEMA}/{VOLUME}/lab_results.csv"
PATIENTS_FILE = f"/Volumes/{CATALOG}/{BRONZE_SCHEMA}/{VOLUME}/patients.csv"

# Read admissions raw CSV
admissions_df = (
    spark.read
    .option("header", "true")
    .option("inferSchema", "true")
    .csv(ADMISSIONS_FILE)
)

# Read lab-results raw CSV
lab_results_df = (
    spark.read
    .option("header", "true")
    .option("inferSchema", "true")
    .csv(LAB_RESULTS_FILE)
)

# Read patients raw CSV
patients_df = (
    spark.read
    .option("header", "true")
    .option("inferSchema", "true")
    .csv(PATIENTS_FILE)
)

# Write admissions data to Bronze Delta table
(
    admissions_df.write
    .format("delta")
    .mode("overwrite")
    .saveAsTable(f"{CATALOG}.{BRONZE_SCHEMA}.admissions")
)

# Write patients data to Bronze Delta table
(
    patients_df.write
    .format("delta")
    .mode("overwrite")
    .saveAsTable(f"{CATALOG}.{BRONZE_SCHEMA}.patients")
)

# Write lab_results data to Bronze Delta table
(
    lab_results_df.write
    .format("delta")
    .mode("overwrite")
    .saveAsTable(f"{CATALOG}.{BRONZE_SCHEMA}.lab_results")
)
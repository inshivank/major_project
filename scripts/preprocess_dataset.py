"""CLI wrapper for dataset preprocessing pipeline.

Examples:
  python -m scripts.preprocess_dataset --input data/raw/archive/data.csv --output data/processed/custom
  python -m scripts.preprocess_dataset --input data/raw/mimic.parquet --output data/processed/mimic --id-col PatientID --time-col RecordTime --target-cols Outcome,LOS,Readmission
"""

from backend.preprocessing.pipeline import main

if __name__ == "__main__":
    raise SystemExit(main())

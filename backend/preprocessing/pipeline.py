"""Configurable EHR/time-series preprocessing pipeline.

Usage:
  python -m backend.preprocessing.pipeline --input data/raw/mydata.csv --output data/processed/mydata
  python -m backend.preprocessing.pipeline --input data/raw/mimic.parquet --output data/processed/mimic --dataset mimic
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from backend.preprocessing.utils import (
    load_table,
    normalize_and_impute,
    stratified_patient_split,
    to_sequences,
)


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def preprocess(
    input_path: str | Path,
    output_dir: str | Path,
    id_col: str | None = None,
    time_col: str | None = None,
    target_cols: list[str] | None = None,
    feature_cols: list[str] | None = None,
    exclude_cols: list[str] | None = None,
    categorical_cols: list[str] | None = None,
    test_size: float = 0.2,
    val_size: float = 0.1,
    seed: int = 42,
) -> dict:
    df = load_table(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # infer columns
    if not id_col or not time_col:
        from backend.preprocessing.utils import detect_id_time_columns
        did, dt = detect_id_time_columns(df)
        id_col = id_col or did
        time_col = time_col or dt

    if time_col in df.columns:
        try:
            df[time_col] = pd.to_datetime(df[time_col])
        except Exception:
            pass
    df = df.sort_values([id_col, time_col]).reset_index(drop=True)

    target_cols = target_cols or [c for c in ["Outcome", "outcome", "label", "mortality", "Readmission", "LOS"] if c in df.columns]
    exclude = set((exclude_cols or []) + [id_col, time_col] + target_cols)
    if feature_cols:
        feature_cols = [c for c in feature_cols if c in df.columns and c not in exclude]
    else:
        feature_cols = [c for c in df.columns if c not in exclude]

    categorical_cols = [c for c in (categorical_cols or []) if c in feature_cols]

    # basic cleaning
    df = df.dropna(subset=[id_col])

    strat_target = target_cols[0] if target_cols else None
    train_ids, val_ids, test_ids = stratified_patient_split(df, id_col, strat_target, test_size, val_size, seed)

    train_df = df[df[id_col].isin(train_ids)].copy()
    val_df = df[df[id_col].isin(val_ids)].copy()
    test_df = df[df[id_col].isin(test_ids)].copy()

    train_df, val_df, test_df, stats = normalize_and_impute(
        train_df, val_df, test_df, id_col, time_col, feature_cols, categorical_cols
    )
    feature_cols = stats["feature_cols"]

    def save_split(name, split_df):
        x, y, pid, times = to_sequences(split_df, id_col, time_col, feature_cols, target_cols)
        pd.to_pickle(x, output_dir / f"{name}_x.pkl")
        pd.to_pickle(y, output_dir / f"{name}_y.pkl")
        pd.to_pickle(pid, output_dir / f"{name}_pid.pkl")
        pd.to_pickle(times, output_dir / f"{name}_record_time.pkl")
        split_df.to_csv(output_dir / f"{name}_flat.csv", index=False)
        return {"patients": len(pid), "rows": len(split_df)}

    summary = {
        "input": str(input_path),
        "output_dir": str(output_dir),
        "id_col": id_col,
        "time_col": time_col,
        "target_cols": target_cols,
        "feature_cols": feature_cols,
        "categorical_cols_input": categorical_cols,
        "seed": seed,
        "splits": {
            "train": save_split("train", train_df),
            "val": save_split("val", val_df),
            "test": save_split("test", test_df),
        },
        "normalization": {"num_cols": stats["num_cols"]},
    }

    # convenience aliases expected by some loaders
    pd.to_pickle(feature_cols, output_dir / "feature_names.pkl")
    pd.to_pickle(target_cols, output_dir / "target_names.pkl")
    with (output_dir / "preprocess_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Preprocess EHR/time-series dataset for CoreCare/ColaCare models.")
    p.add_argument("--input", required=True, help="Path to input file (.csv/.parquet/.json)")
    p.add_argument("--output", required=True, help="Output directory for processed artifacts")
    p.add_argument("--id-col", help="Patient/record identifier column")
    p.add_argument("--time-col", help="Timestamp/order column")
    p.add_argument("--target-cols", help="Comma-separated target columns (e.g. Outcome,LOS,Readmission)")
    p.add_argument("--feature-cols", help="Comma-separated feature columns (default: all except id/time/targets)")
    p.add_argument("--exclude-cols", help="Comma-separated columns to exclude from features")
    p.add_argument("--categorical-cols", help="Comma-separated categorical feature columns to one-hot encode")
    p.add_argument("--test-size", type=float, default=0.2)
    p.add_argument("--val-size", type=float, default=0.1)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    summary = preprocess(
        input_path=args.input,
        output_dir=args.output,
        id_col=args.id_col,
        time_col=args.time_col,
        target_cols=_split_csv(args.target_cols),
        feature_cols=_split_csv(args.feature_cols),
        exclude_cols=_split_csv(args.exclude_cols),
        categorical_cols=_split_csv(args.categorical_cols),
        test_size=args.test_size,
        val_size=args.val_size,
        seed=args.seed,
    )
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Utilities for EHR-style preprocessing: split, normalize, impute, export."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


def detect_id_time_columns(df: pd.DataFrame) -> tuple[str, str]:
    candidates_id = ["PatientID", "RecordID", "patient_id", "subject_id", "stay_id", "icustay_id", "id"]
    candidates_time = ["RecordTime", "charttime", "time", "timestamp", "event_time", "date"]
    id_col = next((c for c in candidates_id if c in df.columns), None)
    time_col = next((c for c in candidates_time if c in df.columns), None)
    if not id_col or not time_col:
        raise ValueError(
            f"Could not detect id/time columns. Found columns: {list(df.columns)}. "
            "Pass --id-col and --time-col explicitly."
        )
    return id_col, time_col


def load_table(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() in {".csv", ".txt"}:
        return pd.read_csv(path)
    if path.suffix.lower() in {".json", ".jsonl"}:
        return pd.read_json(path, lines=path.suffix.lower() == ".jsonl")
    raise ValueError(f"Unsupported input format: {path.suffix}")


def stratified_patient_split(
    df: pd.DataFrame,
    id_col: str,
    target_col: str | None,
    test_size: float,
    val_size: float,
    seed: int,
) -> tuple[list, list, list]:
    from sklearn.model_selection import train_test_split

    grouped = df.groupby(id_col)
    patients = np.array(list(grouped.groups.keys()))
    if target_col and target_col in df.columns:
        y = np.array([grouped.get_group(p)[target_col].iloc[0] for p in patients])
        try:
            train_val, test = train_test_split(
                patients, test_size=test_size, random_state=seed, stratify=y
            )
            y_tv = np.array([grouped.get_group(p)[target_col].iloc[0] for p in train_val])
            rel_val = val_size / max(1e-9, 1.0 - test_size)
            train, val = train_test_split(
                train_val, test_size=rel_val, random_state=seed, stratify=y_tv
            )
            return list(train), list(val), list(test)
        except ValueError:
            pass
    # fallback non-stratified
    rng = np.random.default_rng(seed)
    perm = rng.permutation(patients)
    n = len(perm)
    n_test = max(1, int(round(n * test_size)))
    n_val = max(1, int(round(n * val_size)))
    test = perm[:n_test]
    val = perm[n_test : n_test + n_val]
    train = perm[n_test + n_val :]
    return list(train), list(val), list(test)


def filter_outlier(x):
    try:
        v = float(x)
    except Exception:
        return x
    return 0 if abs(v) > 1e4 else v


def normalize_and_impute(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
    id_col: str,
    time_col: str,
    feature_cols: list[str],
    categorical_cols: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    train_df = train_df.copy()
    val_df = val_df.copy()
    test_df = test_df.copy()

    num_cols = [c for c in feature_cols if c not in categorical_cols and pd.api.types.is_numeric_dtype(train_df[c])]
    cat_cols = [c for c in feature_cols if c in categorical_cols or not pd.api.types.is_numeric_dtype(train_df[c])]

    # one-hot categoricals on union to align columns
    if cat_cols:
        all_cat = pd.concat([train_df[cat_cols], val_df[cat_cols], test_df[cat_cols]], axis=0)
        dummies = pd.get_dummies(all_cat.astype("string"), prefix_sep="->", dummy_na=True, dtype=float)
        n_train, n_val = len(train_df), len(val_df)
        train_df = pd.concat([train_df.drop(columns=cat_cols), dummies.iloc[:n_train].reset_index(drop=True)], axis=1)
        val_df = pd.concat([val_df.drop(columns=cat_cols).reset_index(drop=True), dummies.iloc[n_train:n_train+n_val].reset_index(drop=True)], axis=1)
        test_df = pd.concat([test_df.drop(columns=cat_cols).reset_index(drop=True), dummies.iloc[n_train+n_val:].reset_index(drop=True)], axis=1)
        feature_cols = num_cols + list(dummies.columns)

    if num_cols:
        q_low = train_df[num_cols].quantile(0.05)
        q_high = train_df[num_cols].quantile(0.95)
        filtered = train_df[(train_df[num_cols] > q_low) & (train_df[num_cols] < q_high)]
        mean = filtered[num_cols].mean().fillna(0.0)
        std = filtered[num_cols].std().replace(0, np.nan).fillna(1.0)
        median = filtered[num_cols].median().fillna(0.0)
        default_fill = ((median - mean) / std).fillna(0.0)
        for d in (train_df, val_df, test_df):
            d[num_cols] = (d[num_cols].astype(float) - mean) / std
            d[num_cols] = d[num_cols].map(filter_outlier)
    else:
        mean = pd.Series(dtype=float)
        std = pd.Series(dtype=float)
        default_fill = pd.Series(dtype=float)

    # forward fill per id, then fill remaining with defaults/0
    for d in (train_df, val_df, test_df):
        d.sort_values([id_col, time_col], inplace=True)
        d[feature_cols] = d.groupby(id_col)[feature_cols].ffill()
        for c in feature_cols:
            fill_val = float(default_fill.get(c, 0.0)) if c in default_fill.index else 0.0
            d[c] = d[c].fillna(fill_val)
        d.reset_index(drop=True, inplace=True)

    stats = {
        "feature_cols": feature_cols,
        "num_cols": num_cols,
        "mean": mean.to_dict() if len(mean) else {},
        "std": std.to_dict() if len(std) else {},
    }
    return train_df, val_df, test_df, stats


def to_sequences(
    df: pd.DataFrame,
    id_col: str,
    time_col: str,
    feature_cols: list[str],
    target_cols: list[str],
) -> tuple[list, list, list, list]:
    df = df.sort_values([id_col, time_col])
    xs, ys, pids, times = [], [], [], []
    for pid, g in df.groupby(id_col, sort=False):
        xs.append(g[feature_cols].to_numpy().tolist())
        ys.append(g[target_cols].to_numpy().tolist() if target_cols else [])
        pids.append(pid)
        if pd.api.types.is_datetime64_any_dtype(g[time_col]):
            times.append(g[time_col].dt.strftime("%Y-%m-%d %H:%M:%S").tolist())
        else:
            times.append(g[time_col].astype(str).tolist())
    return xs, ys, pids, times

"""Build a ColaCare-style formatted table from the MIMIC-IV demo CSVs."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

RAW_DIR = Path("data/raw/archive/mimic-iv-clinical-database-demo-2.2")
OUTPUT = Path("data/processed/mimic_demo_formatted.csv")

NUMERIC_ITEMS = {
    "Diastolic blood pressure": [220051],
    "Fraction inspired oxygen": [223835],
    "Glucose": [220621, 225664],
    "Heart Rate": [220045],
    "Height": [226730, 226707],
    "Mean blood pressure": [220052],
    "Oxygen saturation": [220277],
    "Respiratory rate": [220210],
    "Systolic blood pressure": [220050],
    "Temperature": [223762, 223761],
    "Weight": [226512, 224639],
    "pH": [223830],
}

CATEGORICAL_ITEMS = {
    "Capillary refill rate": [224308, 223951],
    "GCS eye opening": [220739],
    "GCS motor response": [223901],
    "GCS verbal response": [223900],
}

LAB_COLS = list(NUMERIC_ITEMS) + list(CATEGORICAL_ITEMS) + ["GCS total"]


def _read_events() -> tuple[pd.DataFrame, pd.DataFrame]:
    chart = pd.read_csv(
        RAW_DIR / "icu/chartevents.csv",
        usecols=["stay_id", "charttime", "itemid", "valuenum", "value"],
    )
    chart["hour"] = pd.to_datetime(chart["charttime"]).dt.floor("h")

    num_ids = {item: name for name, items in NUMERIC_ITEMS.items() for item in items}
    cat_ids = {item: name for name, items in CATEGORICAL_ITEMS.items() for item in items}

    num = chart[chart["itemid"].isin(num_ids)].copy()
    num["feature"] = num["itemid"].map(num_ids)
    num["valuenum"] = pd.to_numeric(num["valuenum"], errors="coerce")
    num.loc[num["itemid"] == 226707, "valuenum"] *= 2.54
    num.loc[num["itemid"] == 223761, "valuenum"] = (num["valuenum"] - 32) * 5 / 9
    num = num.dropna(subset=["valuenum"])
    num_pivot = num.pivot_table(
        index=["stay_id", "hour"], columns="feature", values="valuenum", aggfunc="mean"
    )

    cat = chart[chart["itemid"].isin(cat_ids)].copy()
    cat["feature"] = cat["itemid"].map(cat_ids)
    cat["value"] = cat["value"].astype("string").str.strip()
    cat = cat[cat["value"].notna() & (cat["value"] != "")]
    cat_pivot = cat.pivot_table(
        index=["stay_id", "hour"], columns="feature", values="value", aggfunc="first"
    )

    gcs = cat_pivot.reindex(
        columns=["GCS eye opening", "GCS motor response", "GCS verbal response"]
    ).apply(pd.to_numeric, errors="coerce")
    cat_pivot["GCS total"] = gcs.sum(axis=1, min_count=1)
    return num_pivot, cat_pivot


def _stays_with_targets() -> pd.DataFrame:
    patients = pd.read_csv(
        RAW_DIR / "hosp/patients.csv", usecols=["subject_id", "gender", "anchor_age", "anchor_year"]
    )
    admissions = pd.read_csv(
        RAW_DIR / "hosp/admissions.csv",
        usecols=[
            "subject_id", "hadm_id", "admittime", "dischtime", "hospital_expire_flag"
        ],
    )
    stays = pd.read_csv(
        RAW_DIR / "icu/icustays.csv",
        usecols=["subject_id", "hadm_id", "stay_id", "intime", "outtime", "los"],
    )

    admissions["admittime"] = pd.to_datetime(admissions["admittime"])
    admissions["dischtime"] = pd.to_datetime(admissions["dischtime"])
    admissions = admissions.sort_values(["subject_id", "admittime"])
    admissions["next_admittime"] = admissions.groupby("subject_id")["admittime"].shift(-1)
    admissions["Readmission"] = (
        (admissions["next_admittime"] - admissions["dischtime"]).dt.total_seconds().between(0, 30 * 86400)
    ).astype(int)

    admissions["Age"] = (
        patients.set_index("subject_id")["anchor_age"].reindex(admissions["subject_id"]).to_numpy()
        + admissions["admittime"].dt.year
        - patients.set_index("subject_id")["anchor_year"].reindex(admissions["subject_id"]).to_numpy()
    ).clip(0, 120)
    admissions["Sex"] = patients.set_index("subject_id")["gender"].reindex(admissions["subject_id"]).to_numpy()
    admissions["Outcome"] = admissions["hospital_expire_flag"].astype(int)

    keep = [
        "hadm_id", "Outcome", "LOS", "Readmission", "Sex", "Age"
    ]
    adm = admissions[["hadm_id", "Outcome", "Readmission", "Sex", "Age"]].copy()
    stay_los = stays[["stay_id", "los"]].rename(columns={"los": "LOS"})
    merged = stays.merge(adm, on="hadm_id", how="left").merge(stay_los, on="stay_id", how="left")
    return merged[keep + ["subject_id", "hadm_id", "stay_id", "intime", "outtime"]]


def build() -> pd.DataFrame:
    num_pivot, cat_pivot = _read_events()
    events = num_pivot.join(cat_pivot, how="outer").reset_index()
    stays = _stays_with_targets()

    frames = []
    for stay in stays.itertuples(index=False):
        start = pd.to_datetime(stay.intime).floor("h")
        end = pd.to_datetime(stay.outtime).ceil("h")
        grid = pd.DataFrame({"stay_id": stay.stay_id, "hour": pd.date_range(start, end, freq="h")})
        merged = grid.merge(events[events["stay_id"] == stay.stay_id], on=["stay_id", "hour"], how="left")
        merged[LAB_COLS] = merged[LAB_COLS].ffill()
        merged[LAB_COLS] = merged[LAB_COLS].fillna({c: "Unknown" for c in CATEGORICAL_ITEMS})
        for col in NUMERIC_ITEMS:
            merged[col] = pd.to_numeric(merged[col], errors="coerce")
        merged["GCS total"] = pd.to_numeric(merged["GCS total"], errors="coerce")
        merged["RecordID"] = f"{stay.subject_id}_{stay.stay_id}"
        merged["PatientID"] = stay.subject_id
        merged["AdmissionID"] = stay.hadm_id
        merged["RecordTime"] = merged["hour"]
        merged["Outcome"] = stay.Outcome
        merged["LOS"] = stay.LOS
        merged["Readmission"] = stay.Readmission
        merged["Sex"] = stay.Sex
        merged["Age"] = stay.Age
        frames.append(merged)

    df = pd.concat(frames, ignore_index=True)
    columns = [
        "RecordID", "PatientID", "AdmissionID", "RecordTime",
        "Outcome", "LOS", "Readmission", "Sex", "Age",
    ] + LAB_COLS
    return df[columns].sort_values(["RecordID", "RecordTime"]).reset_index(drop=True)


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    df = build()
    df.to_csv(OUTPUT, index=False)
    print(f"Wrote {OUTPUT} with {len(df)} rows, {df['RecordID'].nunique()} ICU stays")
    print(df[["Outcome", "Readmission"]].mean().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

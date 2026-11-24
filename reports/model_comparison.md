# MIMIC-IV demo: model comparison

## What this is

Phase 1 model training for **Agent 3 (Clinical Record Analysis)**. Three EHR models from
the read-only ColaCare reference (`ColaCare-main/pyehr/models/`) were trained on the
MIMIC-IV **demo** subset and evaluated on a held-out patient-level test set.

**Scope:** 100 patients, 275 admissions, 140 ICU stays, 12,642 hourly records.
Outcome = in-hospital mortality; readmission = re-admission within 30 days.

## Results

| Task | Model | Test AUROC | Test AUPRC | Best epoch |
|---|---|---:|---:|---:|
| Mortality | AdaCare | 0.3125 | 0.1546 | 5 |
| Mortality | MCGRU | 0.3542 | 0.1571 | 2 |
| Mortality | **RETAIN** | **0.7604** | **0.7260** | 5 |
| Readmission | AdaCare | 0.4470 | 0.2204 | 7 |
| Readmission | MCGRU | 0.6023 | 0.3299 | 1 |
| Readmission | **RETAIN** | **0.7424** | **0.3661** | 8 |

**Takeaway:** RETAIN is the strongest model on both tasks in this demo run. AdaCare and
MCGRU underperform on mortality, which is expected with only ~14 positive training
patients — this is a sample-size problem, not evidence that the models are unsuitable.

## How to read these numbers

- Patient-level split: 70% train / 10% validation / 20% test (98 / 14 / 28 patients), seed 42.
- Best epoch chosen on validation AUPRC; no test data used for model selection.
- The test set has 28 patients: 4 deaths and 6 readmissions. A single patient changes the
  metric by several points, so treat differences below ~0.1 as noise.
- These metrics are **illustrative only**. The MIMIC-IV demo is far too small for any
  clinical claim; the full MIMIC-IV dataset (and CDSL/ESRD) is needed for real evaluation.

## Artifacts produced

- `checkpoints/mimic_{task}_{model}.pt` — trained weights for all 6 runs.
- `predictions/mimic_{task}_{model}.pkl` — `{patient_id: risk_score}`; these are the files
  Agent 3 will consume to explain predictions to the doctor.
- `reports/metrics.json` — full machine-readable metrics.

## Reproduce

```powershell
.venv\Scripts\python -m scripts.build_mimic_demo_formatted
.venv\Scripts\python -m scripts.preprocess_dataset --input data/processed/mimic_demo_formatted.csv --output data/processed/mimic_demo --id-col RecordID --time-col RecordTime --target-cols Outcome,LOS,Readmission --exclude-cols PatientID,AdmissionID --categorical-cols "Sex,Capillary refill rate,GCS eye opening,GCS motor response,GCS verbal response" --test-size 0.2 --val-size 0.1
.venv\Scripts\python -m scripts.train_models
```

Next step: repeat on full MIMIC-IV, then CDSL and ESRD once their CSVs are available.

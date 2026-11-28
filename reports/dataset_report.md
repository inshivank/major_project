# Dataset Report — CoreCare Major Project

**Project:** CoreCare — LLM-Driven Multi-Agent Framework for Intelligent Healthcare Services  
**Prepared for:** Major project evaluation  
**Repository:** `major_project` (branch `week2-online-foundation`, commit `d3cb730` plus local UI work)

---

## 1. Executive summary

The project uses **three data assets**, each built for a different part of the system:

| # | Asset | Used for | Status |
|---|---|---|---|
| 1 | MIMIC-IV Clinical Database **Demo v2.2** (raw EHR) | Offline model training and the Clinical Record Analysis agent | Fully processed and used end-to-end |
| 2 | Curated medical **RAG corpus** (18 documents, 43 chunks) | Patient Assistance agent and report agent references | Ingested into ChromaDB and used at runtime |
| 3 | ColaCare reference datasets (**full MIMIC-IV, CDSL, ESRD**) | Reference preprocessing designs and future scaling | Scripts only; data not available locally |

The main dataset work was to turn the raw MIMIC-IV demo into a **patient/hour-level EHR table**, convert it into **per-patient sequences** with leakage-safe splits, train and compare three EHR models for **in-hospital mortality** and **30-day readmission**, and expose the resulting risk scores through an agent with source attribution. The demo contains only 100 patients, so all model results are explicitly reported as **illustrative, not clinically valid** (`reports/model_comparison.md:27-34`).

---

## 2. Why this dataset was chosen

- The reference framework (ColaCare, WWW 2025) evaluates on **MIMIC-IV, CDSL (COVID-19 Data Saving Lives), and ESRD (End-Stage Renal Disease)** for mortality and 30-day readmission (`ColaCare-main/README.md:92-107`).
- Full MIMIC-IV access requires PhysioNet credentialing, CITI training and a DUA, with a typical 1–2 week turnaround; this was started early in Week 2 as a long-lead dependency (`docs/plan-week2.md:192-199`).
- To avoid blocking development, Phase 1 used the openly available **MIMIC-IV Clinical Database Demo v2.2**: 100 patients, 275 admissions, 140 ICU stays and 12,642 hourly records (`reports/model_comparison.md:9-10`).
- A deliberate two-phase architecture was planned: **Phase 1 (offline)** dataset preparation and model training; **Phase 2 (online)** multi-agent application (`docs/plan-week2.md:8-18`). The online backbone was built in Week 2 and the offline model work followed in Week 3.

---

## 3. Dataset 1 — MIMIC-IV demo EHR

### 3.1 Raw data

- Source archive: `data/raw/archive/mimic-iv-clinical-database-demo-2.2.zip` (16.2 MB); extracted to `data/raw/archive/mimic-iv-clinical-database-demo-2.2/` (~134.7 MB).
- Deidentified ICU/EHR data from Beth Israel Deaconess Medical Center. The demo restricts the cohort to 100 `subject_id` values and **excludes free-text clinical notes** (`data/raw/archive/mimic-iv-clinical-database-demo-2.2/README.txt:5-12`).
- Tables actually consumed by the pipeline:
  - `icu/chartevents.csv` — 668,862 rows; source of all vitals, labs and GCS values.
  - `icu/d_items.csv` — item ID dictionary used to identify measurement concepts.
  - `hosp/patients.csv` — 100 rows; sex and anchor age/year.
  - `hosp/admissions.csv` — 275 rows; admission/discharge times and `hospital_expire_flag`.
  - `icu/icustays.csv` — 140 rows; ICU in/out times and length of stay.
- Other demo tables (lab events, prescriptions, diagnoses, ICD dictionaries, etc.) were inspected but intentionally not used, keeping the feature set aligned with the ColaCare EHR format.
- The raw ZIP, extracted CSVs and generated artifacts are **git-ignored** (`.gitignore:16-19`), so no patient-derived data is committed.

### 3.2 Building the formatted hourly table

Script: `scripts/build_mimic_demo_formatted.py` → `data/processed/mimic_demo_formatted.csv`.

Work performed:

1. **Concept mapping** (`scripts/build_mimic_demo_formatted.py:13-35`): 12 numeric measurements (diastolic/mean/systolic BP, FiO₂, glucose, heart rate, height, SpO₂, respiratory rate, temperature, weight, pH) and 4 categorical measurements (capillary refill rate, GCS eye/motor/verbal) were mapped to their `itemid` values. A derived `GCS total` was added from the three GCS components (`:66-69`).
2. **Time binning and aggregation** (`:38-64`): `charttime` was floored to hourly bins; numeric observations were averaged per `(stay_id, hour)` and categorical ones took the first value.
3. **Unit normalisation** (`:51-52`): height in inches converted to cm (×2.54) and temperature in °F converted to °C.
4. **Target construction** (`:88-102`):
   - `Outcome` = `hospital_expire_flag` (in-hospital mortality).
   - `Readmission` = 1 if the next admission for the same patient starts within 0–30 days of discharge.
   - `LOS` = ICU length of stay from `icustays.csv`.
   - `Age` = `anchor_age + admittime.year - anchor_year`, clipped to `[0, 120]`; `Sex` from `gender`.
5. **Hourly grid and IDs** (`:113-145`): for each ICU stay, a complete hourly timeline from ICU admission to discharge was created, observations were forward-filled, unfilled categoricals were marked `Unknown`, and `RecordID = "<subject_id>_<stay_id>"` plus `PatientID`, `AdmissionID`, `RecordTime` were attached.

Result: **12,642 hourly rows, 26 columns, 140 ICU stays**, spanning 100 patients and 128 admissions.

### 3.3 Preprocessing, splitting and feature export

CLI: `scripts/preprocess_dataset.py`; implementation: `backend/preprocessing/pipeline.py:30-117` and `backend/preprocessing/utils.py:36-159`.

Steps completed:

- Load CSV/parquet and infer/validate `RecordID` and `RecordTime`; sort per patient by time.
- Exclude identifiers (`RecordID`, `PatientID`, `AdmissionID`, `RecordTime`) and targets (`Outcome`, `LOS`, `Readmission`) from the feature matrix.
- **Patient-level stratified split**, seed 42, so no patient appears in more than one split (`backend/preprocessing/utils.py:36-71`).
- **Train-only normalisation** using 5th–95th percentile trimmed mean/std/median, with outlier values `|z| > 1e4` mapped to 0 (`backend/preprocessing/utils.py:74-118`).
- One-hot encoding of the 5 categorical columns (`Sex`, capillary refill, 3 GCS responses), forward-fill within each patient, and explicit missing-value handling (`:95-131`).
- Export of per-patient sequences `x` (visits × features), `y` (visits × targets), `pid` and timestamps, plus flat CSVs and `preprocess_summary.json`.

Realised configuration (`data/processed/mimic_demo/preprocess_summary.json:1-95`):

| Split | Patients | Hourly rows | Share |
|---|---:|---:|---:|
| Train | 98 | 11,899 | 70% |
| Validation | 14 | 1,089 | 10% |
| Test | 28 | 2,575 | 20% |

- Final model input: **42 features** — 14 numeric vitals/labs/GCS total plus 28 one-hot categorical indicators.
- Targets retained: `Outcome`, `LOS`, `Readmission`; the two binary tasks were trained, `LOS` was kept for future regression work.

### 3.4 Model training and evaluation

Script: `scripts/train_models.py`; models imported from the read-only ColaCare reference (`ColaCare-main/pyehr/models/`).

- Models: **AdaCare, MCGRU, RETAIN**; hidden dim 32, 30 epochs, patience 5, learning rate 1e-3.
- Full-batch Adam training with `BCEWithLogitsLoss`; best epoch selected on **validation AUPRC only**; test set untouched during selection (`scripts/train_models.py:87-123`).
- Labels are taken from the last hourly visit of each patient.

| Task | Model | Test AUROC | Test AUPRC | Best epoch |
|---|---|---:|---:|---:|
| Mortality | AdaCare | 0.3125 | 0.1546 | 5 |
| Mortality | MCGRU | 0.3542 | 0.1571 | 2 |
| Mortality | **RETAIN** | **0.7604** | **0.7260** | 5 |
| Readmission | AdaCare | 0.4470 | 0.2204 | 7 |
| Readmission | MCGRU | 0.6023 | 0.3299 | 1 |
| Readmission | **RETAIN** | **0.7424** | **0.3661** | 8 |

Interpretation recorded in `reports/model_comparison.md:23-34`: RETAIN is strongest on both tasks in this demo run; the weaker AdaCare/MCGRU mortality results are consistent with only ~14 positive training patients. With 4 deaths and 6 readmissions among 28 test patients, differences below ~0.1 are noise. These numbers demonstrate the pipeline, not clinical performance.

Artifacts: 6 checkpoints in `checkpoints/`, 6 risk-score maps in `predictions/`, and machine-readable metrics in `reports/metrics.json`.

### 3.5 Downstream use by the Clinical Record Analysis agent

`backend/agents/clinical_agent.py` consumes both the formatted CSV and the prediction pickles:

- Resolves a `RecordID`, `PatientID` or `AdmissionID` to a test patient with available predictions (`:72-92`).
- Displays latest available age, sex, heart rate, oxygen saturation and record count (`:106-148`).
- Converts model scores into low/moderate/high bands (`:64-69`) and uses RETAIN as the primary estimate (`:325-332`).
- Always attaches `record` and `model` sources; an LLM explanation is optional, consent-gated, and receives only risk bands and retrieved reference passages — **never patient identifiers or raw values** (`:31-37`, `:345-387`).
- Explicitly warns that comparisons are illustrative on the small demo test set (`:193-201`).

---

## 4. Dataset 2 — Medical RAG corpus

- **Content:** 12 curated Markdown summaries (fever, cold/flu, diabetes, hypertension, asthma, heart attack, stroke, emergency signs, medication safety, dehydration, when to see a doctor, antibiotic use) plus `lab_tests.json` with 6 lab-education records (CBC, lipid profile, creatinine, liver panel, TSH, HbA1c/glucose). Sources are NHS, CDC, WHO, AHA, ASA, FDA, MedlinePlus and Medical News Today; all text is paraphrased and provenance is recorded in `data/corpus/SOURCES.md:1-20,30-45`.
- **Ingestion:** `backend/rag/ingest.py` loads `.md/.txt/.json`, skips `SOURCES.md`, chunks into ~800 characters with 100-character overlap, assigns stable SHA1 IDs and embeds with Chroma's built-in MiniLM ONNX embedder (`backend/rag/ingest.py:24-136`).
- **Store:** `data/chroma/` collection `corecare_medical`, cosine distance, **18 documents / 43 chunks**, top-k 4 (`backend/config/settings.py:26-31`; `backend/rag/retriever.py:19-90`).
- **Consumers:** Patient Assistance agent (retrieval-grounded answers with mandatory citations), Clinical Record Analysis agent (reference passages for risk explanation), and Medical Report Analysis agent (lab reference passages).
- A 20-question keyword-coverage smoke set was added in `scripts/eval_patient_agent.py:24-64`; manual relevance/groundedness columns remain for faculty review.

---

## 5. Dataset 3 — ColaCare reference datasets

- `ColaCare-main/` and `research/colacare/` hold the read-only reference framework, including preprocessing scripts for **MIMIC-IV, CDSL and ESRD** (`ColaCare-main/ehr_datasets/`).
- These scripts document the target format, patient-level splits, missingness masks, normalization and clinical-context fields that informed our own pipeline (`ColaCare-main/ehr_datasets/utils/tools.py:20-308`).
- They are **not executed locally**: the expected raw files (`mimic4_formatted_ehr.parquet`, `cdsl_dataset_formatted.csv`, `esrd_dataset.csv`) and `processed/fold_1` artifacts are absent. Copies of the CDSL/ESRD scripts also exist under `data/raw/archive/{cdsl,esrd}/preprocess.py`.
- Differences were deliberate: our builder emits `GCS …` column names while ColaCare expects `Glascow coma scale …`, and our split is 70/10/20 rather than ColaCare's dataset-specific fractions. The demo also has no clinical notes, so ColaCare's `test_notes.pkl` context path cannot be reused as-is.

---

## 6. How the team worked on it (timeline and method)

| Phase | Dataset-related work | Evidence |
|---|---|---|
| **Week 1 — foundation** | FastAPI skeleton, pytest setup, read-only ColaCare clone kept untouched; no dataset processing yet. | commit `9d798fb`; `docs/plan-week2.md:5-6` |
| **Week 2 — online foundation** | Long-lead MIMIC access work started; curated RAG corpus authored with per-source provenance; Chroma ingest/retriever, Patient agent and `/chat` built; offline tests with fake LLM/retriever; merged via PR #1. | `docs/plan-week2.md:81-199`; commits `63a5010`–`277aa96` |
| **Week 3 — Phase 1 data + models** | Added local `ColaCare-main` reference copy; built the hourly formatted table; implemented configurable preprocessing and patient-level splits; trained 6 models; wrote metrics/comparison reports. | commits `e4882c4`, `8296d25`; `reports/model_comparison.md` |
| **Week 4 — reports and records** | Medical Report Analysis agent added by Aanya Aggarwal (commit `46c0825`), including `lab_tests.json` corpus; Clinical Record Analysis agent wired to the formatted CSV and prediction pickles; UI/demo pages and launcher added. | `WEEK4_IMPLEMENTATION_REPORT.md`; commits `8308d30`, `d3cb730` |
| **Verification** | Offline suite grew to 148 passing tests on this branch (189 on `main` after PDF-security hardening); live checks exercised real OCR, real Chroma retrieval and live Groq with synthetic data only. | `README.md:353-360`; `WEEK4_IMPLEMENTATION_REPORT.md:286-299` |

Working method: **plan first** (daily Week 2 checklist with definition of done and risks), **incremental branch-based commits**, **offline-first testing** with fakes and synthetic fixtures, **explicit provenance** for every corpus source, **no credentials or patient data in version control**, and **separate runtime verification** for OCR/LLM behaviour. The research clone was treated as read-only and was never modified.

---

## 7. Reproducibility

From the repo root, with the virtual environment active (`reports/model_comparison.md:43-49`):

```powershell
.venv\Scripts\python -m scripts.build_mimic_demo_formatted
.venv\Scripts\python -m scripts.preprocess_dataset --input data/processed/mimic_demo_formatted.csv --output data/processed/mimic_demo --id-col RecordID --time-col RecordTime --target-cols Outcome,LOS,Readmission --exclude-cols PatientID,AdmissionID --categorical-cols "Sex,Capillary refill rate,GCS eye opening,GCS motor response,GCS verbal response" --test-size 0.2 --val-size 0.1
.venv\Scripts\python -m scripts.train_models
.venv\Scripts\python -m backend.rag.ingest --reset
```

Because `data/raw/`, `data/processed/` and `data/chroma/` are ignored by git, an evaluation machine must regenerate these artifacts (or be supplied with the raw demo ZIP) before running the app.

---

## 8. Ethics, privacy and safety

- The demo is deidentified; no real patient records were used in runtime verification, and corpus text is paraphrased with sources credited.
- Identifiers are excluded from model features and the LLM prompt; consent to external LLM use defaults to false and cannot be forced by configuration (`README.md:256-260`).
- The system is documented as **decision support / research software, not a diagnosis system** (`README.md:9-10`); emergency guidance remains jurisdiction-specific (`data/corpus/SOURCES.md:22-28`).
- Authentication and access control remain deployment work; the API must not be exposed to real patient traffic without them (`README.md:313-314`).

---

## 9. Limitations and future work

**Current limitations**

1. The MIMIC-IV demo is far too small for clinical claims: 28 test patients, ~14 positive training patients, and no free-text notes; model differences below ~0.1 AUROC/AUPRC are noise (`reports/model_comparison.md:23-34`).
2. CDSL/ESRD datasets and full MIMIC-IV were not available; only their reference preprocessing scripts are present.
3. `LOS` is processed but not trained; the agent serves scores only for the 28 test `RecordID`s in `predictions/`.
4. One-hot categories are built from the union of all splits (`backend/preprocessing/utils.py:99-106`), so the category vocabulary is not strictly train-only (normalisation statistics are train-only).
5. ColaCare's own MIMIC path cannot be run against this demo as-is (filename, column-name and clinical-note differences).
6. Corpus expansion requires licence verification per source; OCR/live-LLM availability must be re-verified in a new environment.

**Next steps**

- Repeat training/evaluation on full MIMIC-IV, then CDSL and ESRD once access and CSVs are available (`reports/model_comparison.md:51`).
- Add LOS regression and calibrate/validate probabilities before any clinical interpretation.
- Week 6 roadmap: multi-agent collaboration, fusion, evaluation and UI (`README.md:208`).
- Keep raw and derived datasets out of git; regenerate from documented commands during evaluation.

---

## 10. Key files

| Concern | Path |
|---|---|
| Raw demo + integrity info | `data/raw/archive/mimic-iv-clinical-database-demo-2.2/` |
| Hourly table builder | `scripts/build_mimic_demo_formatted.py` |
| Formatted EHR table | `data/processed/mimic_demo_formatted.csv` |
| Preprocessing CLI / pipeline / utils | `scripts/preprocess_dataset.py`, `backend/preprocessing/pipeline.py`, `backend/preprocessing/utils.py` |
| Processed splits + metadata | `data/processed/mimic_demo/` |
| Training | `scripts/train_models.py` |
| Metrics and comparison | `reports/metrics.json`, `reports/model_comparison.md` |
| Checkpoints / predictions | `checkpoints/`, `predictions/` |
| Clinical Record agent | `backend/agents/clinical_agent.py` |
| RAG corpus / provenance / store | `data/corpus/`, `data/corpus/SOURCES.md`, `data/chroma/` |
| Reference framework | `ColaCare-main/`, `research/colacare/` |

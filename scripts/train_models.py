"""Train AdaCare, MCGRU and RETAIN on the processed MIMIC-IV demo data."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import average_precision_score, roc_auc_score
from torch import nn

COLA_PYEHR = Path("ColaCare-main/pyehr")
sys.path.insert(0, str(COLA_PYEHR.resolve()))

import models  # noqa: E402
from models.utils import generate_mask  # noqa: E402

DATA_DIR = Path("data/processed/mimic_demo")
CHECKPOINT_DIR = Path("checkpoints")
PREDICTION_DIR = Path("predictions")
REPORT_DIR = Path("reports")

TASKS = {"outcome": 0, "readmission": 2}
MODEL_NAMES = ["AdaCare", "MCGRU", "RETAIN"]
HIDDEN_DIM = 32
EPOCHS = 30
PATIENCE = 5
LR = 1e-3


def load_split(name: str, task_idx: int):
    x = pd.read_pickle(DATA_DIR / f"{name}_x.pkl")
    y = pd.read_pickle(DATA_DIR / f"{name}_y.pkl")
    pid = pd.read_pickle(DATA_DIR / f"{name}_pid.pkl")
    dim = len(x[0][0])
    lens = torch.tensor([len(seq) for seq in x], dtype=torch.long)
    padded = torch.zeros(len(x), int(lens.max()), dim, dtype=torch.float32)
    for i, seq in enumerate(x):
        padded[i, : len(seq)] = torch.tensor(seq, dtype=torch.float32)
    labels = torch.tensor([float(seq[-1][task_idx]) for seq in y], dtype=torch.float32)
    return padded, labels, lens, list(pid)


def build_model(name: str, input_dim: int):
    if name == "AdaCare":
        encoder = models.AdaCare(input_dim=input_dim, hidden_dim=HIDDEN_DIM)
    elif name == "MCGRU":
        encoder = models.MCGRU(lab_dim=input_dim, demo_dim=0, hidden_dim=HIDDEN_DIM)
    elif name == "RETAIN":
        encoder = models.RETAIN(input_dim=input_dim, hidden_dim=HIDDEN_DIM)
    else:
        raise ValueError(name)
    head = nn.Linear(HIDDEN_DIM, 1)
    return encoder, head


def embed(name: str, encoder, x: torch.Tensor, lens: torch.Tensor) -> torch.Tensor:
    if name == "MCGRU":
        return encoder(x, torch.zeros(x.size(0), 0))
    out = encoder(x, generate_mask(lens))
    return out[0] if isinstance(out, tuple) else out


def safe_auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    if len(np.unique(y_true)) < 2:
        return 0.5
    return float(roc_auc_score(y_true, y_score))


def safe_ap(y_true: np.ndarray, y_score: np.ndarray) -> float:
    if len(np.unique(y_true)) < 2:
        return float(np.mean(y_true))
    return float(average_precision_score(y_true, y_score))


@torch.no_grad()
def predict(name, encoder, head, x, lens):
    encoder.eval()
    head.eval()
    logits = head(embed(name, encoder, x, lens)).squeeze(-1)
    return torch.sigmoid(logits).numpy()


def train_one(task: str, task_idx: int, model_name: str, splits: dict) -> dict:
    torch.manual_seed(42)
    np.random.seed(42)
    x_train, y_train, l_train, _ = splits["train"]
    x_val, y_val, l_val, _ = splits["val"]
    x_test, y_test, l_test, pid_test = splits["test"]

    encoder, head = build_model(model_name, x_train.shape[-1])
    optimizer = torch.optim.Adam(list(encoder.parameters()) + list(head.parameters()), lr=LR)
    criterion = nn.BCEWithLogitsLoss()

    best_ap = -1.0
    best_state = None
    best_epoch = 0
    for epoch in range(1, EPOCHS + 1):
        encoder.train()
        head.train()
        optimizer.zero_grad()
        logits = head(embed(model_name, encoder, x_train, l_train)).squeeze(-1)
        loss = criterion(logits, y_train)
        loss.backward()
        optimizer.step()

        val_prob = predict(model_name, encoder, head, x_val, l_val)
        val_ap = safe_ap(y_val.numpy(), val_prob)
        if val_ap > best_ap:
            best_ap = val_ap
            best_epoch = epoch
            best_state = {
                "encoder": {k: v.detach().clone() for k, v in encoder.state_dict().items()},
                "head": {k: v.detach().clone() for k, v in head.state_dict().items()},
            }
        if epoch - best_epoch >= PATIENCE:
            break

    encoder.load_state_dict(best_state["encoder"])
    head.load_state_dict(best_state["head"])
    test_prob = predict(model_name, encoder, head, x_test, l_test)

    ckpt = CHECKPOINT_DIR / f"mimic_{task}_{model_name.lower()}.pt"
    torch.save({"encoder": encoder.state_dict(), "head": head.state_dict(), "epoch": best_epoch}, ckpt)
    pred_file = PREDICTION_DIR / f"mimic_{task}_{model_name.lower()}.pkl"
    pd.to_pickle({pid: float(p) for pid, p in zip(pid_test, test_prob)}, pred_file)

    return {
        "dataset": "mimic-iv-demo",
        "task": task,
        "model": model_name,
        "best_epoch": best_epoch,
        "val_auprc": round(best_ap, 4),
        "test_auroc": round(safe_auc(y_test.numpy(), test_prob), 4),
        "test_auprc": round(safe_ap(y_test.numpy(), test_prob), 4),
        "checkpoint": str(ckpt),
        "predictions": str(pred_file),
        "test_patients": len(pid_test),
        "test_positive_rate": round(float(y_test.mean()), 4),
    }


def main() -> int:
    torch.set_num_threads(2)
    for directory in (CHECKPOINT_DIR, PREDICTION_DIR, REPORT_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    results = []
    for task, idx in TASKS.items():
        splits = {name: load_split(name, idx) for name in ("train", "val", "test")}
        for model_name in MODEL_NAMES:
            result = train_one(task, idx, model_name, splits)
            results.append(result)
            print(
                f"{task:12s} {model_name:8s} "
                f"AUROC={result['test_auroc']:.4f} AUPRC={result['test_auprc']:.4f} "
                f"(epoch {result['best_epoch']})",
                flush=True,
            )

    (REPORT_DIR / "metrics.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    lines = [
        "# MIMIC-IV demo: model comparison",
        "",
        "Trained on the MIMIC-IV **demo** subset (100 patients, 140 ICU stays).",
        "Metrics are illustrative only; the demo is far too small for clinical claims.",
        "",
        "| Task | Model | Test AUROC | Test AUPRC | Best epoch |",
        "|---|---|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| {r['task']} | {r['model']} | {r['test_auroc']:.4f} | "
            f"{r['test_auprc']:.4f} | {r['best_epoch']} |"
        )
    lines += ["", "Split: patient-level 70/10/20, seed 42. Best epoch selected on validation AUPRC.", ""]
    (REPORT_DIR / "model_comparison.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {REPORT_DIR / 'model_comparison.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

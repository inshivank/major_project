"""Smoke evaluation for the Patient Assistance agent.

Offline mode checks retrieval only (no API key needed). Live mode runs the full
orchestrator through Groq and writes a CSV with blank manual scoring columns.

Usage:
    python -m scripts.eval_patient_agent --offline
    python -m scripts.eval_patient_agent --live
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

from backend.config.settings import PROJECT_ROOT
from backend.orchestrator.orchestrator import Orchestrator
from backend.rag.retriever import Retriever
from backend.schemas.chat import ChatRequest

QUESTIONS: list[tuple[str, str]] = [
    ("What are the symptoms of type 2 diabetes?", "diabetes"),
    ("How is high blood pressure treated?", "hypertension"),
    ("What should I do if someone is having a stroke?", "stroke"),
    ("What are the warning signs of a heart attack?", "heart attack"),
    ("How can I tell if I am dehydrated?", "dehydrat"),
    ("Do antibiotics work for a cold?", "antibiotic"),
    ("When is a fever an emergency?", "fever"),
    ("How is asthma usually managed?", "asthma"),
    ("What is the difference between a cold and flu?", "influenza"),
    ("Can I stop taking my blood pressure medicine?", "medic"),
    ("How much water should I drink when I have diarrhoea?", "dehydrat"),
    ("What are the early signs of a stroke?", "stroke"),
    ("Is a temperature of 38.5C dangerous for an adult?", "fever"),
    ("What is HbA1c used for?", "diabetes"),
    ("How does an inhaler help asthma?", "asthma"),
    ("Which symptoms mean I should call an ambulance?", "emergency"),
    ("What are common triggers of asthma attacks?", "asthma"),
    ("How is influenza prevented?", "influenza"),
    ("What does a systolic and diastolic reading mean?", "blood pressure"),
    ("What are the risks of untreated hypertension?", "hypertension"),
]


def run_offline() -> int:
    retriever = Retriever()
    if retriever.count() == 0:
        print("Retrieval store is empty. Run: python -m backend.rag.ingest")
        return 1

    hits = 0
    for question, expected in QUESTIONS:
        chunks = retriever.retrieve(question, k=3)
        combined = " ".join(chunk.text.lower() for chunk in chunks)
        hit = expected in combined
        hits += int(hit)
        top = chunks[0].title if chunks else "-"
        print(f"[{'PASS' if hit else 'MISS'}] {question} -> {top}")

    print(f"\nRetrieval keyword coverage: {hits}/{len(QUESTIONS)}")
    return 0 if hits == len(QUESTIONS) else 2


def run_live() -> int:
    orchestrator = Orchestrator.build_default()
    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    output = reports_dir / f"eval_patient_agent_{datetime.now():%Y%m%d_%H%M%S}.csv"

    rows = []
    for question, _ in QUESTIONS:
        response = orchestrator.chat(ChatRequest(message=question))
        rows.append(
            {
                "question": question,
                "intent": response.intent.value,
                "agent": response.agent,
                "status": response.status,
                "citation_count": response.answer.count("["),
                "sources": " | ".join(source.title for source in response.sources),
                "answer_preview": response.answer[:300].replace("\n", " "),
                "manual_relevance_1_5": "",
                "manual_groundedness_1_5": "",
                "notes": "",
            }
        )
        print(f"[{response.status}] {question} -> {response.agent}")

    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote scoring sheet: {output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-evaluate the Patient agent.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true", help="Retrieval-only check")
    mode.add_argument("--live", action="store_true", help="Full run through Groq")
    args = parser.parse_args(argv)

    return run_offline() if args.offline else run_live()


if __name__ == "__main__":
    sys.exit(main())

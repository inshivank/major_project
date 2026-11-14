"""Ingest the local medical reference corpus into ChromaDB.

Usage:
    python -m backend.rag.ingest                # incremental upsert
    python -m backend.rag.ingest --reset        # rebuild from scratch
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

from backend.config.settings import settings

SUPPORTED_SUFFIXES = {".md", ".txt", ".json"}
BATCH_SIZE = 64
TITLE_PATTERN = re.compile(r"^#\s+(.+)$", re.MULTILINE)
SOURCE_PATTERN = re.compile(r"^Source:\s*(\S+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Document:
    path: Path
    title: str
    url: str | None
    text: str


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def load_documents(corpus_dir: Path) -> Iterator[Document]:
    if not corpus_dir.exists():
        raise FileNotFoundError(f"Corpus directory not found: {corpus_dir}")

    for path in sorted(corpus_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if path.name.upper() == "SOURCES.MD":
            continue

        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                for item in payload:
                    yield Document(
                        path=path,
                        title=str(item.get("title") or path.stem),
                        url=item.get("url"),
                        text=str(item.get("content") or item.get("text") or ""),
                    )
            else:
                yield Document(
                    path=path,
                    title=str(payload.get("title") or path.stem),
                    url=payload.get("url"),
                    text=str(payload.get("content") or payload.get("text") or ""),
                )
            continue

        raw = path.read_text(encoding="utf-8")
        title_match = TITLE_PATTERN.search(raw)
        source_match = SOURCE_PATTERN.search(raw)
        yield Document(
            path=path,
            title=(title_match.group(1).strip() if title_match else path.stem),
            url=(source_match.group(1).strip() if source_match else None),
            text=raw.strip(),
        )


def chunk_text(text: str, size: int = 800, overlap: int = 100) -> list[str]:
    """Split on paragraph boundaries, keeping chunks near ``size`` characters."""
    if size <= 0:
        raise ValueError("chunk size must be positive")
    overlap = max(0, min(overlap, size // 2))

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= size:
            current = candidate
            continue

        if current:
            chunks.append(current)

        remainder = paragraph
        while len(remainder) > size:
            chunks.append(remainder[:size].strip())
            remainder = remainder[size - overlap :].strip()
        current = remainder

    if current.strip():
        chunks.append(current.strip())

    return chunks


def make_id(relative_path: str, chunk_index: int, chunk: str) -> str:
    digest = hashlib.sha1(f"{relative_path}::{chunk_index}::{chunk}".encode()).hexdigest()
    return digest


def iter_records(
    documents: Iterable[Document],
    corpus_dir: Path,
    size: int,
    overlap: int,
) -> Iterator[tuple[str, str, dict]]:
    for document in documents:
        relative = _relative(document.path, corpus_dir)
        for index, chunk in enumerate(chunk_text(document.text, size, overlap)):
            metadata = {
                "title": document.title,
                "source": relative,
                "url": document.url or "",
                "chunk_index": index,
            }
            yield make_id(relative, index, chunk), chunk, metadata


def ingest(
    corpus_dir: Path | None = None,
    persist_dir: Path | None = None,
    collection_name: str | None = None,
    reset: bool = False,
    size: int | None = None,
    overlap: int | None = None,
) -> int:
    corpus_dir = Path(corpus_dir or settings.corpus_dir)
    persist_dir = Path(persist_dir or settings.chroma_dir)
    collection_name = collection_name or settings.collection_name
    size = size or settings.chunk_size
    overlap = overlap if overlap is not None else settings.chunk_overlap

    persist_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(persist_dir))

    if reset:
        try:
            client.delete_collection(collection_name)
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=collection_name,
        embedding_function=embedding_functions.DefaultEmbeddingFunction(),
        metadata={"hnsw:space": "cosine"},
    )

    batch_ids: list[str] = []
    batch_texts: list[str] = []
    batch_meta: list[dict] = []
    total = 0

    for record_id, chunk, metadata in iter_records(
        load_documents(corpus_dir), corpus_dir, size, overlap
    ):
        batch_ids.append(record_id)
        batch_texts.append(chunk)
        batch_meta.append(metadata)
        if len(batch_ids) >= BATCH_SIZE:
            collection.upsert(ids=batch_ids, documents=batch_texts, metadatas=batch_meta)
            total += len(batch_ids)
            batch_ids, batch_texts, batch_meta = [], [], []

    if batch_ids:
        collection.upsert(ids=batch_ids, documents=batch_texts, metadatas=batch_meta)
        total += len(batch_ids)

    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest the CoreCare corpus into ChromaDB.")
    parser.add_argument("--corpus", type=Path, default=settings.corpus_dir)
    parser.add_argument("--persist", type=Path, default=settings.chroma_dir)
    parser.add_argument("--collection", default=settings.collection_name)
    parser.add_argument("--reset", action="store_true", help="Delete and rebuild the collection")
    parser.add_argument("--chunk-size", type=int, default=settings.chunk_size)
    parser.add_argument("--chunk-overlap", type=int, default=settings.chunk_overlap)
    args = parser.parse_args(argv)

    try:
        total = ingest(
            corpus_dir=args.corpus,
            persist_dir=args.persist,
            collection_name=args.collection,
            reset=args.reset,
            size=args.chunk_size,
            overlap=args.chunk_overlap,
        )
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"Ingested {total} chunks into {args.persist} (collection={args.collection}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

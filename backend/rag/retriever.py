"""ChromaDB-backed retriever for the medical reference corpus."""

from __future__ import annotations

from dataclasses import dataclass

import chromadb
from chromadb.utils import embedding_functions

from backend.config.settings import settings


@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    title: str
    url: str | None
    score: float


class Retriever:
    """Queries the persistent Chroma collection built by ``backend.rag.ingest``."""

    def __init__(
        self,
        persist_dir: str | None = None,
        collection_name: str | None = None,
    ) -> None:
        self.persist_dir = str(persist_dir or settings.chroma_dir)
        self.collection_name = collection_name or settings.collection_name
        self._embedding_function = embedding_functions.DefaultEmbeddingFunction()
        self._client: chromadb.ClientAPI | None = None
        self._collection = None

    @property
    def collection(self):
        if self._collection is None:
            self._client = chromadb.PersistentClient(path=self.persist_dir)
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self._embedding_function,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def count(self) -> int:
        return self.collection.count()

    def retrieve(self, query: str, k: int | None = None) -> list[RetrievedChunk]:
        if not query.strip():
            return []
        if self.count() == 0:
            return []

        limit = max(1, k or settings.retrieval_top_k)
        result = self.collection.query(
            query_texts=[query],
            n_results=limit,
            include=["documents", "metadatas", "distances"],
        )

        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        chunks: list[RetrievedChunk] = []
        for text, metadata, distance in zip(documents, metadatas, distances):
            metadata = metadata or {}
            chunks.append(
                RetrievedChunk(
                    text=text or "",
                    title=str(metadata.get("title") or "Untitled reference"),
                    url=str(metadata.get("url") or "") or None,
                    score=round(max(0.0, 1.0 - float(distance)), 4),
                )
            )
        return chunks

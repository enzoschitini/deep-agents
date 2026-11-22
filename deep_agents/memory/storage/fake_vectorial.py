"""Banco vetorial FALSO: guarda tudo em memória RAM e imita a busca por similaridade.

O "embedding" é um vetor de trigramas de caracteres e a similaridade é cosseno. Não é semântico
de verdade; serve só para exercitar o fluxo "salvar → buscar por similaridade" do agente.
Os dados somem quando o processo termina. Para o real, trocar por Pinecone/pgvector mantendo
o contrato `MemoryRepository`.
"""

from __future__ import annotations

import math
import uuid
from collections import Counter
from datetime import datetime, timezone

from deep_agents.memory.storage.storage_memory import MemoryRecord, MemoryRepository


def _fake_embedding(text: str) -> Counter[str]:
    text = f"  {text.lower()}  "
    return Counter(text[i : i + 3] for i in range(len(text) - 2))


def _cosine(a: Counter[str], b: Counter[str]) -> float:
    dot = sum(count * b[gram] for gram, count in a.items())
    norm = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return dot / norm if norm else 0.0


class FakeVectorialDatabase(MemoryRepository):
    MIN_SCORE = 0.2  # abaixo disso a nota é considerada não relacionada

    def __init__(self) -> None:
        self._rows: list[tuple[MemoryRecord, Counter[str]]] = []

    def save(self, session_id: str, role: str, content: str) -> MemoryRecord:
        record = MemoryRecord(
            id=uuid.uuid4().hex[:8],
            session_id=session_id,
            role=role,
            content=content.strip(),
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self._rows.append((record, _fake_embedding(record.content)))
        return record

    def get(self, record_id: str) -> MemoryRecord | None:
        return next((r for r, _ in self._rows if r.id == record_id), None)

    def list(self, session_id: str | None = None) -> list[MemoryRecord]:
        return [r for r, _ in self._rows if session_id is None or r.session_id == session_id]

    def search(self, query: str, limit: int = 5) -> list[MemoryRecord]:
        q = _fake_embedding(query)
        scored = [(_cosine(q, emb), r) for r, emb in self._rows]
        scored = [(s, r) for s, r in scored if s >= self.MIN_SCORE]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [r for _, r in scored[:limit]]

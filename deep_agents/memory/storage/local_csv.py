"""Storage em arquivo CSV: simula um banco de dados sem precisar de integração."""

from __future__ import annotations

import csv
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from deep_agents.memory.storage.storage_memory import MemoryRecord, MemoryRepository

_FIELDS = ["id", "session_id", "role", "content", "created_at"]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


class LocalCSV(MemoryRepository):
    def __init__(self, file_path: str | Path) -> None:
        self.file_path = Path(file_path)

    def _read(self) -> list[MemoryRecord]:
        if not self.file_path.exists() or self.file_path.stat().st_size == 0:
            return []
        with self.file_path.open(newline="", encoding="utf-8") as f:
            return [MemoryRecord(**row) for row in csv.DictReader(f)]

    def save(self, session_id: str, role: str, content: str) -> MemoryRecord:
        record = MemoryRecord(
            id=uuid.uuid4().hex[:8],
            session_id=session_id,
            role=role,
            content=content.strip(),
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        is_new = not self.file_path.exists() or self.file_path.stat().st_size == 0
        with self.file_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_FIELDS)
            if is_new:
                writer.writeheader()
            writer.writerow(vars(record))
        return record

    def get(self, record_id: str) -> MemoryRecord | None:
        return next((r for r in self._read() if r.id == record_id), None)

    def list(self, session_id: str | None = None) -> list[MemoryRecord]:
        records = self._read()
        return [r for r in records if session_id is None or r.session_id == session_id]

    def search(self, query: str, limit: int = 5) -> list[MemoryRecord]:
        """Relevância = quantas palavras da consulta aparecem na nota (busca por palavra-chave)."""
        wanted = _tokens(query)
        scored = [(len(wanted & _tokens(r.content)), r) for r in self._read()]
        scored = [(score, r) for score, r in scored if score > 0]
        scored.sort(key=lambda pair: (-pair[0], pair[1].created_at), reverse=False)
        return [r for _, r in scored[:limit]]

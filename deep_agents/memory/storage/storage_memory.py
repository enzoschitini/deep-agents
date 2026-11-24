"""Armazenamento da memória de conversas: os tipos de dados, o contrato dos backends e o `StorageMemory`.

Este módulo não importa nenhum backend: os backends (`local_csv.py`, `fake_vectorial.py`) é que importam
daqui o `MemoryRecord` e o `MemoryRepository`. Quem escolhe o backend é o `MemoryBuilder`, que entrega
o repositório pronto ao `StorageMemory`.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

ROLES = ("human", "ai")  # quem escreveu a mensagem (mesmos nomes do LangChain)


@dataclass(frozen=True)
class MemoryRecord:
    """Uma mensagem de uma conversa."""
    id: str
    session_id: str
    role: str        # "human" (usuário) ou "ai" (agente)
    content: str
    created_at: str  # ISO 8601, UTC


@dataclass(frozen=True)
class SessionInfo:
    """Resumo de uma sessão, para listar e escolher (calculado a partir das mensagens)."""
    id: str
    count: int          # número de mensagens
    updated_at: str     # data da última mensagem
    preview: str        # primeira mensagem do usuário
    title: str = ""      # nome dado pelo usuário (vazio = usa o `preview`)


class MemoryRepository(ABC):
    """Todo backend (CSV, vetorial, PostgreSQL, Pinecone…) implementa estes métodos."""

    @abstractmethod
    def save(self, session_id: str, role: str, content: str) -> MemoryRecord:
        """Grava uma mensagem e devolve o registro criado."""

    @abstractmethod
    def get(self, record_id: str) -> MemoryRecord | None:
        """Busca uma mensagem pelo ID."""

    @abstractmethod
    def list(self, session_id: str | None = None) -> list[MemoryRecord]:
        """Mensagens (da sessão, se informada), na ordem em que foram trocadas."""

    @abstractmethod
    def search(self, query: str, limit: int = 5) -> list[MemoryRecord]:
        """Mensagens mais relevantes para a consulta, da mais à menos relevante."""

    @abstractmethod
    def delete_session(self, session_id: str) -> int:
        """Apaga todas as mensagens da sessão. Devolve quantas foram apagadas."""

    @abstractmethod
    def delete_all(self) -> int:
        """Apaga todas as mensagens de todas as sessões. Devolve quantas foram apagadas."""


class StorageMemory:
    """Gerencia a memória em armazenamento, sobre um `MemoryRepository` qualquer (hoje CSV e um vetorial
    fake; futuramente PostgreSQL e até Pinecone para memória vetorial). Acrescenta as regras comuns a
    todos os backends: validação do `role`, o resumo das sessões e os nomes dados às sessões.

    Os nomes ficam num JSON ao lado do banco (`titles_path`); sem caminho, só em RAM."""

    def __init__(self, repository: MemoryRepository, titles_path: str | Path | None = None) -> None:
        self._db_instance = repository
        self._titles_path = Path(titles_path) if titles_path else None
        self._titles: dict[str, str] = self._load_titles()

    def _load_titles(self) -> dict[str, str]:
        if self._titles_path is None or not self._titles_path.exists():
            return {}
        try:
            data = json.loads(self._titles_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _save_titles(self) -> None:
        if self._titles_path is None:
            return
        if not self._titles:
            self._titles_path.unlink(missing_ok=True)
            return
        self._titles_path.write_text(json.dumps(self._titles, ensure_ascii=False, indent=2), encoding="utf-8")

    def rename_session(self, session_id: str, title: str) -> None:
        """Dá um nome à sessão; título vazio volta ao automático (a primeira mensagem)."""
        title = " ".join(title.split())[:80]
        if title:
            self._titles[session_id] = title
        else:
            self._titles.pop(session_id, None)
        self._save_titles()

    def delete_session(self, session_id: str) -> int:
        removed = self._db_instance.delete_session(session_id)
        if self._titles.pop(session_id, None) is not None:
            self._save_titles()
        return removed

    def delete_all(self) -> int:
        removed = self._db_instance.delete_all()
        self._titles.clear()
        self._save_titles()
        return removed

    def get_message(self, record_id: str) -> MemoryRecord | None:
        """Busca pelo ID de uma mensagem."""
        return self._db_instance.get(record_id)

    def get_messages(self, session_id: str | None = None) -> list[MemoryRecord]:
        """Mensagens de uma sessão (ou de todas, sem session_id), na ordem da conversa."""
        return self._db_instance.list(session_id)

    def sessions(self) -> list[SessionInfo]:
        """Sessões existentes, da mais recente (última mensagem) para a mais antiga."""
        grouped: dict[str, list[MemoryRecord]] = {}
        for record in self.get_messages():
            grouped.setdefault(record.session_id, []).append(record)
        infos = [
            SessionInfo(
                id=session_id,
                count=len(records),
                updated_at=records[-1].created_at,
                preview=next((r.content for r in records if r.role == "human"), records[0].content),
                title=self._titles.get(session_id, ""),
            )
            for session_id, records in grouped.items()
        ]
        return sorted(infos, key=lambda s: s.updated_at, reverse=True)

    def save_message(self, session_id: str, role: str, content: str) -> MemoryRecord:
        """Salva uma mensagem (`role` = "human" ou "ai") e devolve o registro, com o ID gerado."""
        if role not in ROLES:
            raise ValueError(f"role inválido: {role!r} (use {ROLES})")
        return self._db_instance.save(session_id, role, content)

    def search_messages(self, query: str, limit: int = 5) -> list[MemoryRecord]:
        """Mensagens mais relevantes para a consulta."""
        return self._db_instance.search(query, limit)

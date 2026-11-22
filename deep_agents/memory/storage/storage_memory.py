"""Armazenamento da memória de conversas: os tipos de dados, o contrato dos backends e o `StorageMemory`.

Este módulo não importa nenhum backend: os backends (`local_csv.py`, `fake_vectorial.py`) é que importam
daqui o `MemoryRecord` e o `MemoryRepository`. Quem escolhe o backend é o `MemoryBuilder`, que entrega
o repositório pronto ao `StorageMemory`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

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


class MemoryRepository(ABC):
    """Todo backend (CSV, vetorial, PostgreSQL, Pinecone…) implementa estes quatro métodos."""

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


class StorageMemory:
    """Gerencia a memória em armazenamento, sobre um `MemoryRepository` qualquer (hoje CSV e um vetorial
    fake; futuramente PostgreSQL e até Pinecone para memória vetorial). Acrescenta as regras comuns a
    todos os backends: validação do `role` e o resumo das sessões."""

    def __init__(self, repository: MemoryRepository) -> None:
        self._db_instance = repository

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

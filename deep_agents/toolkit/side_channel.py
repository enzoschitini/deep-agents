"""Canal lateral: onde as tools publicam dados estruturados (ex.: fontes de uma busca)
para serem consultados pelo código depois (CLI, banco). O modelo não vê esse canal."""
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass(frozen=True)
class Publication:
    """Uma publicação rastreável: de qual sessão/turno/toolkit/tool veio e o que ela carrega."""

    session_id: str
    turn: int
    toolkit: str
    tool: str
    kind: str                       # tipo do payload, ex.: "sources"
    payload: Any                    # JSON-serializável
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SideChannel:
    """Coleção thread-safe de publicações (subagentes podem rodar tools em paralelo)."""

    def __init__(self, session_provider: Callable[[], str] | None = None) -> None:
        """`session_provider` devolve o ID da sessão atual (acompanha /pulisci e /sessioni)."""
        self._session_provider = session_provider or (lambda: "default")
        self._publications: list[Publication] = []
        self._subscribers: list[Callable[[Publication], None]] = []
        self._turn = 0
        self._lock = threading.Lock()

    def begin_turn(self) -> int:
        """Marca o início de uma nova mensagem do usuário; as publicações seguintes pertencem a ela."""
        with self._lock:
            self._turn += 1
            return self._turn

    def publish(self, toolkit: str, tool: str, kind: str, payload: Any) -> Publication:
        with self._lock:
            pub = Publication(self._session_provider(), self._turn, toolkit, tool, kind, payload)
            self._publications.append(pub)
            subscribers = list(self._subscribers)
        for callback in subscribers:  # fora do lock: um consumidor lento não trava as tools
            callback(pub)
        return pub

    def subscribe(self, callback: Callable[[Publication], None]) -> None:
        """Consumidor em tempo real (ex.: banco de dados no futuro)."""
        with self._lock:
            self._subscribers.append(callback)

    def query(
        self,
        *,
        session_id: str | None = None,
        toolkit: str | None = None,
        tool: str | None = None,
        kind: str | None = None,
        turn: int | None = None,
    ) -> list[Publication]:
        """Publicações que batem com todos os filtros informados, em ordem de publicação."""
        wanted = {"session_id": session_id, "toolkit": toolkit, "tool": tool, "kind": kind, "turn": turn}
        with self._lock:
            return [
                p for p in self._publications
                if all(v is None or getattr(p, k) == v for k, v in wanted.items())
            ]

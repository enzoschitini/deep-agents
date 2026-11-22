"""MemoryBuilder: fachada da memória de conversas (sessões para a CLI e resumo de contexto para o agente)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from deepagents.middleware import SummarizationMiddleware

from deep_agents.memory.storage.fake_vectorial import FakeVectorialDatabase
from deep_agents.memory.storage.local_csv import LocalCSV
from deep_agents.memory.storage.storage_memory import MemoryRepository, SessionInfo, StorageMemory
from deep_agents.memory.config import KEEP_MESSAGES, SUMMARY_EVERY_INTERACTIONS, TRIM_TOKENS_TO_SUMMARIZE
from deep_agents.prompts.system import SUMMARY_PROMPT

DEFAULT_CSV = Path(__file__).resolve().parent / "local_database.csv"
_CHAT_ROLE = {"human": "user", "ai": "assistant"}  # papéis no formato de mensagens do chat


def _new_session_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


class MemoryBuilder:
    """Esconde da CLI qual storage é usado e cuida do histórico e da sessão atual.

    A memória é o histórico de mensagens de conversas (uma linha por mensagem, com o papel de quem
    falou: `human` ou `ai`), agrupadas por sessão. Uma instância tem uma sessão atual (`session_id`):
    começa nova e vazia, e pode ser trocada por `new_session()` ou `resume()`.
      - storage → `StorageMemory` (CSV ou vetorial fake, hoje; bancos reais depois)
      - sessão  → `session_id`, `message_count()`, `sessions()`, `history()`, `record_turn()`
      - resumo  → `summarization(model, backend)`, o único ponto em que o agente usa a memória (comprime o contexto)
    """

    def __init__(
        self,
        database: str = "local_csv",
        session_id: str | None = None,
        file_path: str | Path | None = None,
    ) -> None:
        self.storage = StorageMemory(self._resolve_database(database, file_path))
        self.session_id = session_id or self._unique_session_id()

    @staticmethod
    def _resolve_database(database: str, file_path: str | Path | None) -> MemoryRepository:
        """Escolhe o backend pelo nome. Para um banco novo: implementar `MemoryRepository` e registrar aqui."""
        if database == "local_csv":
            return LocalCSV(file_path=file_path or DEFAULT_CSV)
        if database == "fake_vectorial":
            return FakeVectorialDatabase()
        raise ValueError(f"Tipo de banco de dados desconhecido: {database}")

    # ------------------------------------------------------------------ resumo
    def summarization(self, model: Any, backend: Any) -> SummarizationMiddleware:
        """Middleware que comprime o contexto: passando de `SUMMARY_EVERY_INTERACTIONS` interações, as mensagens
        antigas viram um resumo (guiado por `SUMMARY_PROMPT`) e as `KEEP_MESSAGES` mais recentes ficam intactas
        (valores em `memory/config.py`).
        Uma interação = pergunta + resposta = 2 mensagens (chamadas de ferramenta contam como mensagens extras).
        Passar este middleware a `create_deep_agent(middleware=[...])` substitui o resumo padrão do SDK."""
        return SummarizationMiddleware(
            model=model,
            backend=backend,
            summary_prompt=SUMMARY_PROMPT,
            trigger=("messages", SUMMARY_EVERY_INTERACTIONS * 2),
            keep=("messages", KEEP_MESSAGES),
            trim_tokens_to_summarize=TRIM_TOKENS_TO_SUMMARIZE,
        )

    # ------------------------------------------------------------------ sessão
    def _unique_session_id(self) -> str:
        """ID por data/hora, com sufixo (-2, -3…) se já existir ou se for o da sessão atual."""
        taken = {s.id for s in self.sessions()} | {getattr(self, "session_id", None)}
        base = candidate = _new_session_id()
        n = 1
        while candidate in taken:
            n += 1
            candidate = f"{base}-{n}"
        return candidate

    def new_session(self) -> str:
        """Começa uma sessão nova, sem relação com as anteriores (que continuam salvas)."""
        self.session_id = self._unique_session_id()
        return self.session_id

    def resume(self, session_id: str) -> bool:
        """Torna `session_id` a sessão atual. False (sem mudar nada) se ela não existir."""
        if not any(s.id == session_id for s in self.sessions()):
            return False
        self.session_id = session_id
        return True

    def sessions(self) -> list[SessionInfo]:
        return self.storage.sessions()

    def message_count(self) -> int:
        return len(self.storage.get_messages(self.session_id))

    def history(self) -> list[dict[str, str]]:
        """Mensagens da sessão atual no formato do chat (`role` user/assistant), para retomar a conversa."""
        return [
            {"role": _CHAT_ROLE[m.role], "content": m.content}
            for m in self.storage.get_messages(self.session_id)
        ]

    def record_turn(self, user_text: str, ai_text: str) -> None:
        """Grava na sessão atual a mensagem do usuário e a resposta do agente."""
        self.storage.save_message(self.session_id, "human", user_text)
        self.storage.save_message(self.session_id, "ai", ai_text)

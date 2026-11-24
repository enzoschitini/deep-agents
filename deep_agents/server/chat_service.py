"""ChatService: o que a CLI faz em `ChatCLI._send`, sem terminal. Uma conversa por vez (como a CLI).

Roda o turno numa thread e devolve eventos (dicts) por uma fila, para o servidor transmitir ao navegador:
  {"type": "step", "phase": "start"|"end", "id", "kind": "subagent"|"tool", "name", "label", "error"?}
  {"type": "answer", "text", "sources": [...], "metrics": str}
  {"type": "error", "message"}
O fim do fluxo é o `None` na fila."""

from __future__ import annotations

import queue
import threading
from typing import Any, Iterator

from langchain_core.callbacks import BaseCallbackHandler

from deep_agents.bootstrap import Backend
from deep_agents.cli.models import AVAILABLE_MODELS, resolve_choice
from deep_agents.cli.renderer import format_metrics
from deep_agents.utils.json_manager import extract_response_text, manage_result_json

_SKIP_TOOLS = {"write_todos"}   # ruído interno: não interessa a quem lê a conversa


def _clip(text: Any, n: int = 110) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


class _LiveSteps(BaseCallbackHandler):
    """Traduz o início/fim das tools em eventos para a página (a `task` é a delegação a um subagent)."""

    def __init__(self, emit) -> None:
        self.emit = emit
        self._names: dict[Any, str] = {}

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kwargs):
        name = (serialized or {}).get("name") or kwargs.get("name") or "?"
        if name in _SKIP_TOOLS:
            return
        args = kwargs.get("inputs") if isinstance(kwargs.get("inputs"), dict) else {}
        if name == "task":
            kind, shown, label = "subagent", args.get("subagent_type") or "subagent", _clip(args.get("description"))
        else:
            kind, shown = "tool", name
            label = _clip(args.get("query") or args.get("path") or args.get("file_path") or "")
        self._names[run_id] = shown
        self.emit({"type": "step", "phase": "start", "id": str(run_id), "kind": kind, "name": shown, "label": label})

    def _end(self, run_id, error=None):
        if self._names.pop(run_id, None) is not None:
            self.emit({"type": "step", "phase": "end", "id": str(run_id), "error": error})

    def on_tool_end(self, output, *, run_id, **kwargs):
        self._end(run_id)

    def on_tool_error(self, error, *, run_id, **kwargs):
        self._end(run_id, f"{type(error).__name__}: {str(error)[:200]}")


class ChatService:
    def __init__(self, backend: Backend) -> None:
        self.backend = backend
        self.messages: list[dict[str, str]] = backend.memory.history()   # vazio numa sessão nova
        self._busy = threading.Lock()

    # ------------------------------------------------------------------ estado
    @property
    def memory(self):
        return self.backend.memory

    def state(self) -> dict[str, Any]:
        return {
            "model": self.backend.gateway.config.spec,
            "models": self.model_specs(),
            "session": self.memory.session_id,
            "messages": list(self.messages),
            "sessions": [
                {"id": s.id, "count": s.count, "updated_at": s.updated_at, "preview": _clip(s.preview, 60), "title": s.title}
                for s in self.memory.sessions()
            ],
        }

    def model_specs(self) -> list[str]:
        """Modelos oferecidos (os mesmos do /modello da CLI); o atual entra na lista mesmo se não for um deles."""
        specs = [m.spec for m in AVAILABLE_MODELS]
        current = self.backend.gateway.config.spec
        return specs if current in specs else [current, *specs]

    def set_model(self, choice: str) -> str | None:
        """Troca o modelo como o /modello da CLI: reconstrói agente e gateway; em caso de erro mantém o anterior.
        Devolve None se deu certo, ou a mensagem de erro."""
        if not self._busy.acquire(blocking=False):
            return "c'è una risposta in corso: attendi che finisca"
        try:
            current = self.backend.gateway.config
            new_config = resolve_choice(choice, AVAILABLE_MODELS, current)
            if new_config is None:
                return "modello non valido: usa il formato provider:modello"
            if new_config.spec == current.spec:
                return None
            try:
                agent, gateway = self.backend.create_agent(new_config)
            except Exception as e:
                return f"impossibile usare {new_config.spec}: {type(e).__name__}: {str(e).strip()[:200]}"
            self.backend.agent, self.backend.gateway = agent, gateway
            return None
        finally:
            self._busy.release()

    def new_session(self) -> bool:
        if not self._busy.acquire(blocking=False):
            return False
        try:
            self.messages = []
            self.memory.new_session()
            return True
        finally:
            self._busy.release()

    def rename_session(self, session_id: str, title: str) -> bool:
        if not any(s.id == session_id for s in self.memory.sessions()):
            return False
        self.memory.rename_session(session_id, title)
        return True

    def delete_session(self, session_id: str) -> bool:
        """Apaga uma sessão salva (a mesma da CLI). Se era a que está aberta, a conversa volta ao início."""
        if not self._busy.acquire(blocking=False):
            return False
        try:
            if not any(s.id == session_id for s in self.memory.sessions()):
                return False
            was_current = session_id == self.memory.session_id
            self.memory.delete_session(session_id)
            if was_current:
                self.messages = []
            return True
        finally:
            self._busy.release()

    def delete_all_sessions(self) -> bool:
        if not self._busy.acquire(blocking=False):
            return False
        try:
            self.memory.delete_all_sessions()
            self.messages = []
            return True
        finally:
            self._busy.release()

    def resume(self, session_id: str) -> bool:
        if not self._busy.acquire(blocking=False):
            return False
        try:
            if not self.memory.resume(session_id):
                return False
            self.messages = self.memory.history()
            return True
        finally:
            self._busy.release()

    # ------------------------------------------------------------------- turno
    def send(self, text: str) -> Iterator[dict[str, Any]] | None:
        """Inicia um turno. Devolve o iterador de eventos, ou None se já há um turno em andamento."""
        if not self._busy.acquire(blocking=False):
            return None
        events: queue.Queue[dict[str, Any] | None] = queue.Queue()
        threading.Thread(target=self._run, args=(text, events), daemon=True).start()

        def drain() -> Iterator[dict[str, Any]]:
            while (event := events.get()) is not None:
                yield event
        return drain()

    def _run(self, text: str, events: queue.Queue) -> None:
        backend, channel = self.backend, self.backend.toolkit.channel
        self.messages.append({"role": "user", "content": text})
        turn = channel.begin_turn() if channel is not None else None
        dynamic: dict[str, str] = {}   # id do evento do `eval` -> subagent

        def on_event(event: Any) -> None:   # subagents dinâmicos (despachados dentro do `eval`)
            if not isinstance(event, dict) or event.get("type") != "subagent":
                return
            sid, phase = f"dyn-{event.get('id')}", event.get("phase")
            if phase == "start":
                dynamic[sid] = event.get("subagent_type", "subagent")
                label = _clip(event.get("label") or event.get("description"))
                events.put({"type": "step", "phase": "start", "id": sid, "kind": "subagent", "name": dynamic[sid], "label": label})
            elif phase in {"complete", "error"} and sid in dynamic:
                events.put({"type": "step", "phase": "end", "id": sid, "error": str(event.get("error", ""))[:200] if phase == "error" else None})

        try:
            result, report = backend.gateway.run_agent(
                backend.agent, {"messages": list(self.messages)},   # cópia: o LangGraph converte a lista no lugar
                config={"callbacks": [_LiveSteps(events.put)]}, on_event=on_event,
            )
            manage_result_json(result)
            answer = extract_response_text(result)
            if not answer.strip():
                raise RuntimeError("l'agente non ha restituito nessuna risposta")
            self.messages.append({"role": "assistant", "content": answer})
            sources, seen = [], set()
            if channel is not None:
                for pub in channel.query(turn=turn, kind="sources"):
                    for item in pub.payload:
                        if item["url"] not in seen:
                            seen.add(item["url"])
                            sources.append(item)
            events.put({"type": "answer", "text": answer, "sources": sources, "metrics": format_metrics(report)})
            try:
                self.memory.record_turn(text, answer)
            except Exception as e:   # falha ao gravar não derruba a resposta
                events.put({"type": "notice", "message": f"salvataggio non riuscito: {e}"})
        except Exception as e:
            self.messages.pop()   # mantém o histórico consistente
            events.put({"type": "error", "message": f"{type(e).__name__}: {str(e).strip() or '(nessun messaggio)'}"})
        finally:
            self._busy.release()
            events.put(None)

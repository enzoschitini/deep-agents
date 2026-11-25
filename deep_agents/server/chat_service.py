"""ChatService: o que a CLI faz em `ChatCLI._send`, sem terminal. Uma conversa por vez (como a CLI).

Roda o turno numa thread (`AgentStreamer`) e devolve, por uma fila, os eventos do streaming já como dicts
(`StreamEvent.to_dict()`), para o servidor transmiti-los ao navegador em SSE:
  {"kind": "response", "phase": "delta"|"end", "data": {"text", ...}, ...}   texto da resposta (palavra a palavra)
  {"kind": "tool"|"subagent"|"subagent_dynamic"|"skill"|"todos"|"file"|..., "phase": "start"|"end"|"error", "id", "parent_id", "label", ...}
  {"kind": "run", "phase": "end", "data": {"answer", "sources": [...], "metrics": str, "stats": {...}}}
  {"kind": "run", "phase": "error", "error": "..."}      erro do turno (montado aqui)
  {"kind": "notice", "phase": "info", "data": {"message"}}   aviso não fatal (ex.: falha ao gravar a sessão)
Não existem mais os eventos `step` e `answer`. O fim do fluxo é o `None` na fila."""

from __future__ import annotations

import queue
import threading
from typing import Any, Iterator

from deep_agents.bootstrap import STREAMING, Backend
from deep_agents.cli.models import AVAILABLE_MODELS, resolve_choice
from deep_agents.cli.renderer import format_metrics
from deep_agents.streaming.events import EventKind, Phase, Visibility
from deep_agents.streaming.streamer import AgentStreamer
from deep_agents.utils.json_manager import manage_result_json


def _clip(text: Any, n: int = 110) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _own_event(kind: EventKind, phase: Phase, *, error: str | None = None, data: dict | None = None) -> dict[str, Any]:
    """Evento montado pelo próprio serviço (erro do turno, avisos), no mesmo formato de `StreamEvent.to_dict()`."""
    return {"kind": str(kind), "phase": str(phase), "id": "service", "agent": "main", "error": error,
            "visibility": "primary", "data": data or {}}


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
    def send(self, text: str, *, debug: bool = False) -> Iterator[dict[str, Any]] | None:
        """Inicia um turno. Devolve o iterador de eventos, ou None se já há um turno em andamento.
        `debug` inclui também os eventos DEBUG (por padrão vão só os PRIMARY e SECONDARY)."""
        if not self._busy.acquire(blocking=False):
            return None
        events: queue.Queue[dict[str, Any] | None] = queue.Queue()
        threading.Thread(target=self._run, args=(text, events, debug), daemon=True).start()

        def drain() -> Iterator[dict[str, Any]]:
            while (event := events.get()) is not None:
                yield event
        return drain()

    def _run(self, text: str, events: queue.Queue, debug: bool = False) -> None:
        backend = self.backend
        limit = Visibility.DEBUG if debug else Visibility.SECONDARY
        self.messages.append({"role": "user", "content": text})
        try:
            streamer = AgentStreamer(backend.agent, backend.gateway, options=STREAMING, channel=backend.toolkit.channel,
                                    tracer=backend.tracer, origin="web")
            handle = streamer.start(list(self.messages))   # cópia: o LangGraph converte a lista no lugar
            run_end: dict[str, Any] | None = None
            for ev in handle:
                if ev.kind == EventKind.RUN:
                    if ev.phase == Phase.END:
                        run_end = ev.to_dict()   # segurado: só sai depois de gravar a sessão e com as métricas
                    continue   # START não interessa à página; ERROR/CANCELLED viram o erro de `res.error`
                if ev.visibility <= limit:
                    events.put(ev.to_dict())
            res = handle.result
            if res.error is not None:
                raise res.error
            manage_result_json(res.state)
            answer = res.answer
            if not (answer or "").strip():
                raise RuntimeError("l'agente non ha restituito nessuna risposta")
            self.messages.append({"role": "assistant", "content": answer})
            try:
                self.memory.record_turn(text, answer)
            except Exception as e:   # falha ao gravar não derruba a resposta
                events.put(_own_event(EventKind.NOTICE, Phase.INFO, data={"message": f"salvataggio non riuscito: {e}"}))
            end = run_end or _own_event(EventKind.RUN, Phase.END)
            end["kind"], end["phase"] = str(EventKind.RUN), str(Phase.END)
            end["data"] = {**(end.get("data") or {}), "answer": answer, "sources": res.sources,
                           "metrics": format_metrics(res.report, res.stats)}
            events.put(end)
        except Exception as e:
            if self.messages and self.messages[-1].get("role") == "user":
                self.messages.pop()   # mantém o histórico consistente
            events.put(_own_event(EventKind.RUN, Phase.ERROR, error=f"{type(e).__name__}: {str(e).strip() or '(nessun messaggio)'}"))
        finally:
            self._busy.release()
            events.put(None)

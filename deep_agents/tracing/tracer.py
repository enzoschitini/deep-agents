"""Tracer: a classe única do rastreamento. O resto do projeto só chama estes métodos.

Ciclo de um run:  begin_run(...)  ->  callback(run_id) + sink(run_id) alimentam o coletor  ->  end_run(...)
O `AgentStreamer` faz isso sozinho quando recebe `tracer=`; a CLI e o servidor web só passam o mesmo `Tracer`.
Nenhum método levanta: um problema no rastreamento é logado em `deep_agents.tracing` e a resposta segue."""

from __future__ import annotations

import logging
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from langchain_core.callbacks import BaseCallbackHandler

from deep_agents.tracing.callbacks import TraceCallbackHandler
from deep_agents.tracing.collector import RunCollector
from deep_agents.tracing.documents import EndInfo, build_documents
from deep_agents.tracing.options import TraceOptions
from deep_agents.tracing.serialize import iso, to_json_safe
from deep_agents.tracing.snapshot import config_hash, environment_info
from deep_agents.tracing.store import SCHEMA_VERSION, TraceStore

log = logging.getLogger("deep_agents.tracing")


class Tracer:
    def __init__(
        self,
        options: TraceOptions | None = None,
        *,
        config_snapshot: Callable[[Any], dict[str, Any]] | None = None,
        session_provider: Callable[[], str] | None = None,
    ) -> None:
        """`config_snapshot(model_config) -> dict` descreve a configuração declarada do agente (ver `snapshot.py`);
        `session_provider()` devolve o ID da sessão atual (como o do `SideChannel`)."""
        self.options = options or TraceOptions()
        self.store = TraceStore(self.options.base_dir, pretty=self.options.pretty)
        self._config_snapshot = config_snapshot
        self._session_provider = session_provider
        self._collectors: dict[str, RunCollector] = {}
        self._lock = threading.Lock()
        self.last_error: BaseException | None = None

    @property
    def enabled(self) -> bool:
        return self.options.enabled

    def _fail(self, where: str, error: BaseException) -> None:
        self.last_error = error
        log.warning("tracing: falha em %s: %s: %s", where, type(error).__name__, error)

    # ------------------------------------------------------------------ início
    def begin_run(
        self,
        run_id: str,
        *,
        messages: list[Any],
        label: str | None = None,
        origin: str | None = None,
        model_config: Any = None,
        session_id: str | None = None,
        turn: int | None = None,
    ) -> None:
        """Abre o rastreamento de um run. `messages` é serializado AGORA (o LangGraph converte a lista no lugar)."""
        if not self.enabled:
            return
        try:
            limit = self.options.max_str_chars
            input_messages = to_json_safe(list(messages), limit)
            user_message = next((m.get("content", "") for m in reversed(input_messages)
                                 if isinstance(m, dict) and m.get("role") in ("user", "human")), "")
            snapshot, chash = {}, None
            if self._config_snapshot is not None and model_config is not None:
                snapshot = self._config_snapshot(model_config)
                chash = config_hash(snapshot)
                self.store.save_config(chash, snapshot)
            if session_id is None and self._session_provider is not None:
                try:
                    session_id = self._session_provider()
                except Exception:
                    session_id = None
            model = (snapshot.get("model") if isinstance(snapshot.get("model"), dict) else None) or (
                {"spec": getattr(model_config, "spec", None)} if model_config is not None else {})
            meta = {
                "label": label, "origin": origin or "unknown", "session_id": session_id, "turn": turn, "model": model,
                "config_hash": chash, "input_messages": input_messages, "user_message": user_message,
                "history_messages": len(input_messages),
                "history_chars": sum(len(str(m.get("content", ""))) for m in input_messages if isinstance(m, dict)),
                "environment": environment_info(),
            }
            collector = RunCollector(run_id, self.options, meta)
            with self._lock:
                self._collectors[run_id] = collector
            started = {
                "schema_version": SCHEMA_VERSION, "run_id": run_id, "label": label, "session_id": session_id, "turn": turn,
                "origin": meta["origin"], "status": "running", "started_at": iso(collector.t0), "ended_at": None,
                "input": {"user_message": user_message}, "model": model, "config_hash": chash,
                "environment": meta["environment"],
                "index_entry": {"run_id": run_id, "session_id": session_id, "turn": turn, "origin": meta["origin"],
                                "status": "running", "started_at": iso(collector.t0), "user_message": user_message[:200],
                                "model": model.get("spec"), "config_hash": chash, "path": f"runs/{run_id}"},
            }
            self.store.write_run_files(run_id, {"run.json": started})
            self.store.upsert_index(started["index_entry"], iso(time.time()))
        except Exception as e:
            self._fail("begin_run", e)

    # ------------------------------------------------------------- alimentação
    def callback(self, run_id: str) -> BaseCallbackHandler | None:
        """Handler do LangChain deste run (para pôr em `config["callbacks"]`); None se desligado/sem run."""
        collector = self._collectors.get(run_id)
        return TraceCallbackHandler(collector) if collector is not None else None

    def record_event(self, run_id: str, event: Any) -> None:
        collector = self._collectors.get(run_id)
        if collector is not None:
            try:
                collector.add_event(event)
            except Exception as e:
                self._fail("record_event", e)

    def sink(self, run_id: str) -> Callable[[Any], None]:
        """Sink para o `EventBus` do streaming: cada `StreamEvent` vai para o `events.json`."""
        return lambda event: self.record_event(run_id, event)

    # --------------------------------------------------------------------- fim
    def end_run(
        self,
        run_id: str,
        *,
        status: str,
        answer: str = "",
        state: dict | None = None,
        report: Any = None,
        stats: Any = None,
        sources: list[dict] | None = None,
        publications: list[Any] | None = None,
        error: BaseException | None = None,
    ) -> Path | None:
        """Fecha o run e grava todos os JSONs. `status`: completed | error | cancelled. Devolve a pasta do run."""
        with self._lock:
            collector = self._collectors.pop(run_id, None)
        if collector is None:
            return None
        try:
            tb = "".join(traceback.format_exception(type(error), error, error.__traceback__)) if error is not None else None
            pubs = [to_json_safe(p, self.options.max_str_chars) for p in (publications or [])]
            end = EndInfo(status=status, ended_at=time.time(), answer=answer or "", state=state, report=report, stats=stats,
                          sources=to_json_safe(sources or [], self.options.max_str_chars), publications=pubs,
                          error=error, error_traceback=tb)
            docs = build_documents(collector, end)
            run_doc = docs.pop("run.json")
            sizes = self.store.write_run_files(run_id, docs)
            run_doc["files"] = {name: {"bytes": n} for name, n in sizes.items()}
            run_doc["files"]["run.json"] = {"bytes": None}
            self.store.write_run_files(run_id, {"run.json": run_doc})
            now = iso(time.time())
            self.store.upsert_index(run_doc["index_entry"], now)
            self.store.update_session(run_doc["index_entry"], now)
            return self.store.run_dir(run_id)
        except Exception as e:
            self._fail("end_run", e)
            return None

    # ----------------------------------------------------------------- leitura
    def list_runs(self, *, session_id: str | None = None, status: str | None = None, limit: int | None = None) -> list[dict]:
        """Runs do índice, do mais recente ao mais antigo."""
        return self.store.list_runs(session_id=session_id, status=status, limit=limit)

    def load_run(self, run_id: str, files: list[str] | None = None) -> dict[str, Any]:
        """Os JSONs do run por nome de arquivo (`run.json`, `llm_calls.json`, ...)."""
        return self.store.load_run(run_id, files)

    def rebuild_index(self) -> dict[str, Any]:
        return self.store.rebuild_index()

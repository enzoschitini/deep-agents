"""ActionCallbackHandler: callback do LangChain que emite DIRETO no bus cada chamada ao LLM e cada tool.

Substitui o `_LiveSteps` do servidor e a parte de árvore de execução do `MetricsCallbackHandler`. O LangChain
propaga os callbacks do principal para os subagents; `metadata["langgraph_checkpoint_ns"]` diz onde cada
execução acontece (a tool `task` roda em `tools:X`; o que o subagent faz roda em `tools:X|model:Y` etc.)."""

from __future__ import annotations

import functools
import threading
import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage

from deep_agents.streaming.actions.classifier import classify
from deep_agents.streaming.actions.labels import label
from deep_agents.streaming.actions.summarize import clip, content_text, safe_repr, tool_output, to_jsonable
from deep_agents.streaming.bus import EventBus
from deep_agents.streaming.events import EventKind, Phase, RunStats, StreamEvent, Visibility
from deep_agents.streaming.options import StreamOptions
from deep_agents.streaming.registry import RunRegistry


class ActionStats:
    """Contadores do turno (thread-safe); viram `RunStats`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._s = RunStats()
        self._dynamic_seen: set[str] = set()

    def tool(self, name: str, kind: EventKind, data: dict) -> None:
        with self._lock:
            s = self._s
            s.n_tools += 1
            s.tools[name] = s.tools.get(name, 0) + 1
            if kind == EventKind.SUBAGENT:
                s.n_subagents += 1
            elif kind == EventKind.SKILL and data.get("skill") not in s.skills:
                s.skills.append(data["skill"])
            elif kind == EventKind.FILE and data.get("path") and data["path"] not in s.files:
                s.files.append(data["path"])
            elif kind == EventKind.TODOS:
                s.todos_updates += 1

    def llm(self) -> None:
        with self._lock:
            self._s.n_llm_calls += 1

    def error(self) -> None:
        with self._lock:
            self._s.errors += 1

    def dynamic_started(self, dyn_id: str) -> bool:
        """True na primeira vez que o id aparece (replay não conta de novo)."""
        with self._lock:
            if dyn_id in self._dynamic_seen:
                return False
            self._dynamic_seen.add(dyn_id)
            self._s.n_dynamic_subagents += 1
            return True

    def snapshot(self) -> RunStats:
        with self._lock:
            s = self._s
            return RunStats(s.n_tools, s.n_subagents, s.n_dynamic_subagents, s.n_llm_calls, dict(s.tools),
                            list(s.skills), list(s.files), s.todos_updates, s.errors)


def split_ns(metadata: dict | None) -> tuple[str, ...]:
    """Namespace do AGENTE dono da execução: `langgraph_checkpoint_ns` sem o último segmento (o do próprio nó)."""
    raw = (metadata or {}).get("langgraph_checkpoint_ns") or ""
    parts = tuple(p for p in str(raw).split("|") if p)
    return parts[:-1]


def clip_args(args: dict, limit: int) -> dict:
    """Argumentos da chamada com cada valor encurtado (strings) ou resumido (estruturas)."""
    out: dict[str, Any] = {}
    for key, value in (args or {}).items():
        if isinstance(value, str):
            out[key] = clip(value, limit)
        elif value is None or isinstance(value, (bool, int, float)):
            out[key] = value
        else:
            out[key] = safe_repr(value, limit)
    return out


def _safe(fn):
    """O callback nunca derruba a execução do agente."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except Exception:
            return None
    return wrapper


class ActionCallbackHandler(BaseCallbackHandler):
    raise_error = False
    run_inline = True   # roda no mesmo fio: o registro do ns da `task` precisa existir antes do subagent começar

    def __init__(self, bus: EventBus, registry: RunRegistry, options: StreamOptions, stats: ActionStats | None = None) -> None:
        self.bus, self.registry, self.options = bus, registry, options
        self.stats = stats or ActionStats()
        self._lock = threading.Lock()
        self._llm: dict[UUID, dict[str, Any]] = {}
        self._tools: dict[UUID, dict[str, Any]] = {}

    # ------------------------------------------------------------------ util
    def _where(self, metadata: dict | None) -> dict[str, Any]:
        ns = split_ns(metadata)
        agent, agent_id = self.registry.agent_for(ns)
        name = (metadata or {}).get("lc_agent_name")
        if ns and name:
            agent = name
        return {"ns": ns, "agent": agent, "agent_id": agent_id, "parent_id": self.registry.parent_for(ns)}

    def _is_summary(self, messages: list[list[Any]]) -> bool:
        marker = self.options.summary_marker
        flat = [m for batch in messages or [] for m in batch]
        if not marker or len(flat) != 1 or not isinstance(flat[0], HumanMessage):
            return False
        return marker in content_text(flat[0].content)

    def _emit(self, kind: EventKind, phase: Phase, ctx: dict, *, id: str, **fields: Any) -> StreamEvent:
        ev = self.bus.make(kind, phase, id=id, ns=ctx["ns"], agent=ctx["agent"], agent_id=ctx["agent_id"],
                           parent_id=ctx["parent_id"], **fields)
        return self.bus.emit(ev)

    # ------------------------------------------------------------------ LLM
    @_safe
    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):
        ctx = self._where(metadata)
        purpose = "summary" if self._is_summary(messages) else "agent"
        inv = kwargs.get("invocation_params") or {}
        model = (inv.get("model") or inv.get("model_name") or (metadata or {}).get("ls_model_name")
                 or (serialized or {}).get("name") or inv.get("_type"))
        n_messages = sum(len(batch) for batch in messages or [])
        self.registry.llm_started(str(run_id), purpose=purpose, ns=ctx["ns"], agent=ctx["agent"])
        with self._lock:
            self._llm[run_id] = {"t0": time.perf_counter(), "ctx": ctx, "purpose": purpose, "model": model}
        self.stats.llm()
        vis = Visibility.SECONDARY if not ctx["ns"] else Visibility.DEBUG
        data = {"purpose": purpose, "model": model, "n_messages": n_messages}
        self._emit(EventKind.MODEL_CALL, Phase.START, ctx, id=str(run_id), name=model, visibility=vis, data=data,
                   label=label(EventKind.MODEL_CALL, Phase.START, model, data=data))
        if purpose == "summary":
            self._emit(EventKind.SUMMARIZATION, Phase.START, ctx, id=f"sum-{run_id}", name=model, visibility=Visibility.SECONDARY,
                       data={"model": model, "n_messages": n_messages}, label=label(EventKind.SUMMARIZATION, Phase.START))

    @_safe
    def on_llm_end(self, response, *, run_id, **kwargs):
        with self._lock:
            info = self._llm.pop(run_id, None)
        if info is None:
            return
        ctx, purpose, latency = info["ctx"], info["purpose"], time.perf_counter() - info["t0"]
        gen = response.generations[0][0] if response.generations and response.generations[0] else None
        msg = getattr(gen, "message", None)
        usage, finish, tool_calls, text = None, None, [], ""
        if isinstance(msg, AIMessage):
            usage = to_jsonable(dict(msg.usage_metadata)) if msg.usage_metadata else None
            rm = msg.response_metadata or {}
            finish = rm.get("finish_reason") or rm.get("stop_reason")
            text = content_text(msg.content) if not isinstance(getattr(msg, "text", None), str) else msg.text
            tool_calls = [{"id": tc.get("id"), "name": tc.get("name"), "args": clip_args(tc.get("args") or {}, self.options.arg_chars)}
                          for tc in (msg.tool_calls or [])]
        elif gen is not None:
            text = getattr(gen, "text", "") or ""
        decision = {"tool_calls": tool_calls, "has_text": bool(text.strip()), "text": clip(text, self.options.summary_chars)}
        data = {"purpose": purpose, "model": info["model"], "usage": usage, "finish_reason": finish,
                "latency_s": round(latency, 4), "decision": decision}
        vis = Visibility.SECONDARY if not ctx["ns"] else Visibility.DEBUG
        self._emit(EventKind.MODEL_CALL, Phase.END, ctx, id=str(run_id), name=info["model"], visibility=vis, duration_s=latency,
                   data=data, summary=("decide: " + ", ".join(c["name"] or "?" for c in tool_calls)) if tool_calls else clip(text, self.options.summary_chars),
                   label=label(EventKind.MODEL_CALL, Phase.END, info["model"], data=data))
        if purpose == "summary":
            self._emit(EventKind.SUMMARIZATION, Phase.END, ctx, id=f"sum-{run_id}", name=info["model"],
                       visibility=Visibility.SECONDARY, duration_s=latency, summary=clip(text, self.options.summary_chars),
                       data={"model": info["model"], "usage": usage, "chars": len(text)}, label=label(EventKind.SUMMARIZATION, Phase.END))

    @_safe
    def on_llm_error(self, error, *, run_id, **kwargs):
        with self._lock:
            info = self._llm.pop(run_id, None)
        if info is None:
            return
        ctx, latency = info["ctx"], time.perf_counter() - info["t0"]
        message = f"{type(error).__name__}: {clip(error, self.options.summary_chars)}"
        self.stats.error()
        data = {"purpose": info["purpose"], "model": info["model"], "latency_s": round(latency, 4)}
        self._emit(EventKind.MODEL_CALL, Phase.ERROR, ctx, id=str(run_id), name=info["model"], visibility=Visibility.PRIMARY,
                   error=message, duration_s=latency, data=data, label=label(EventKind.MODEL_CALL, Phase.ERROR, info["model"], data=data))
        if info["purpose"] == "summary":
            self._emit(EventKind.SUMMARIZATION, Phase.ERROR, ctx, id=f"sum-{run_id}", visibility=Visibility.PRIMARY, error=message,
                       duration_s=latency, label=label(EventKind.SUMMARIZATION, Phase.ERROR))

    # ------------------------------------------------------------------ tools
    @_safe
    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, tags=None, metadata=None, inputs=None, **kwargs):
        name = (serialized or {}).get("name") or kwargs.get("name") or "?"
        args = inputs if isinstance(inputs, dict) else {"input": input_str}
        tool_call_id = str(kwargs.get("tool_call_id") or run_id)
        ctx = self._where(metadata)
        kind, vis, data = classify(name, args, description_chars=self.options.summary_chars)
        shown = name
        if kind == EventKind.SUBAGENT:
            shown = data.get("subagent_type") or "subagent"
            raw_ns = (metadata or {}).get("langgraph_checkpoint_ns")
            if raw_ns:   # os eventos do subagent passam a apontar para esta `task` (parent_id/agent/depth)
                self.registry.register_subagent_ns(str(raw_ns), tool_call_id=tool_call_id, name=shown)
        self.registry.tool_started(tool_call_id, name=name, ns=ctx["ns"], run_id=str(run_id))
        shown_args = clip_args(args, self.options.arg_chars)
        with self._lock:
            self._tools[run_id] = {"id": tool_call_id, "name": name, "shown": shown, "kind": kind, "vis": vis, "data": data,
                                   "args": shown_args, "ctx": ctx, "t0": time.perf_counter()}
        self.stats.tool(name, kind, data)
        self._emit(kind, Phase.START, ctx, id=tool_call_id, name=shown, args=shown_args, visibility=vis, data=dict(data),
                   label=label(kind, Phase.START, shown, shown_args, data))

    def _tool_finish(self, run_id: UUID, text: str, is_error: bool, raw: Any, error: str | None = None) -> None:
        with self._lock:
            info = self._tools.pop(run_id, None)
        if info is None:
            return
        kind, ctx = info["kind"], info["ctx"]
        duration = time.perf_counter() - info["t0"]
        data = dict(info["data"])
        data["result_chars"] = len(text)
        phase = Phase.ERROR if is_error else Phase.END
        if is_error:
            self.stats.error()
        fields: dict[str, Any] = {
            "name": info["shown"], "args": info["args"], "duration_s": duration, "data": data,
            "summary": clip(text, self.options.summary_chars) if text else None,
            "visibility": Visibility.PRIMARY if is_error else info["vis"],
            "label": label(kind, phase, info["shown"], info["args"], data),
        }
        if is_error:
            fields["error"] = error or clip(text, self.options.summary_chars)
        if self.options.capture_raw:
            fields["raw"] = raw
        self._emit(kind, phase, ctx, id=info["id"], **fields)

    @_safe
    def on_tool_end(self, output, *, run_id, **kwargs):
        text, is_error = tool_output(output)
        self._tool_finish(run_id, text, is_error, output)

    @_safe
    def on_tool_error(self, error, *, run_id, **kwargs):
        self._tool_finish(run_id, str(error), True, error, error=f"{type(error).__name__}: {clip(error, self.options.summary_chars)}")

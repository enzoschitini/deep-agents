"""RunCollector: estado de UM run (spans, chamadas ao LLM, tools, eventos) alimentado pelos callbacks e pelo stream.

Só guarda dados brutos já serializados; a montagem dos documentos JSON está em `documents.py`."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

from deep_agents.streaming.actions.callbacks import split_ns
from deep_agents.tracing.options import TraceOptions
from deep_agents.tracing.serialize import (
    clip_str,
    message_text,
    serialize_message,
    serialize_tool_output,
    to_json_safe,
)


def _tool_names(schemas: list) -> list[str]:
    names = []
    for t in schemas or []:
        if isinstance(t, dict):
            name = (t.get("function") or {}).get("name") or t.get("name")
            if name:
                names.append(name)
    return names


class RunCollector:
    def __init__(self, run_id: str, options: TraceOptions, meta: dict[str, Any]) -> None:
        self.run_id = run_id
        self.options = options
        self.meta = meta                       # identidade e entrada do run (montado pelo Tracer.begin_run)
        self.t0 = time.time()
        self.lock = threading.RLock()
        self.seq = 0
        self.spans: dict[str, dict[str, Any]] = {}
        self.llm: dict[str, dict[str, Any]] = {}
        self.tools: dict[str, dict[str, Any]] = {}
        self.tool_schemas: dict[str, list] = {}
        self.events: list[dict[str, Any]] = []
        self.retries: list[dict[str, Any]] = []
        self.callback_errors: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ util
    def _limit(self) -> int:
        return self.options.max_str_chars

    def _next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def note_error(self, where: str, error: BaseException) -> None:
        with self.lock:
            self.callback_errors.append({"where": where, "type": type(error).__name__, "message": str(error)[:300], "at": time.time()})

    # ----------------------------------------------------------------- spans
    def span_open(self, run_id: Any, parent_run_id: Any, type_: str, name: str | None, tags: list | None,
                  metadata: dict | None, **extra: Any) -> dict[str, Any]:
        md = metadata or {}
        span = {
            "span_id": str(run_id), "parent_id": str(parent_run_id) if parent_run_id else None, "type": type_,
            "name": name or "?", "seq": 0, "t0": time.time(), "t1": None, "status": "running", "error": None,
            "tags": list(tags or []), "node": md.get("langgraph_node"), "step": md.get("langgraph_step"),
            "lc_agent_name": md.get("lc_agent_name"), "ns": list(split_ns(md)), "io": {}, **extra,
        }
        with self.lock:
            span["seq"] = self._next_seq()
            self.spans[span["span_id"]] = span
        return span

    def span_close(self, run_id: Any, error: BaseException | None = None) -> dict[str, Any] | None:
        with self.lock:
            span = self.spans.get(str(run_id))
            if span is None:
                return None
            span["t1"] = time.time()
            span["status"] = "error" if error is not None else "completed"
            if error is not None:
                span["error"] = {"type": type(error).__name__, "message": clip_str(str(error), 2000)}
            return span

    # ----------------------------------------------------------------- chains
    def chain_start(self, run_id, parent_run_id, name, inputs, tags, metadata) -> None:
        io: dict[str, Any] = {}
        if isinstance(inputs, dict):
            io["input_keys"] = sorted(map(str, inputs))
            msgs = inputs.get("messages")
            if isinstance(msgs, (list, tuple)):
                io["n_input_messages"] = len(msgs)
        if self.options.capture_chain_io:
            io["input"] = to_json_safe(inputs, self._limit())
        span = self.span_open(run_id, parent_run_id, "chain", name, tags, metadata)
        span["io"] = io

    def chain_end(self, run_id, outputs) -> None:
        span = self.span_close(run_id)
        if span is None:
            return
        if isinstance(outputs, dict):
            span["io"]["output_keys"] = sorted(map(str, outputs))
        if self.options.capture_chain_io:
            span["io"]["output"] = to_json_safe(outputs, self._limit())

    # -------------------------------------------------------------------- llm
    def llm_start(self, run_id, parent_run_id, serialized, messages, tags, metadata, invocation_params) -> None:
        flat = [m for batch in (messages or []) for m in batch]
        limit = self._limit()
        params = dict(to_json_safe(invocation_params or {}, limit))
        tools = params.pop("tools", None)
        tools_hash = None
        if isinstance(tools, list) and tools:
            tools_hash = hashlib.sha1(json.dumps(tools, sort_keys=True, default=str).encode()).hexdigest()[:12]
            with self.lock:
                self.tool_schemas.setdefault(tools_hash, tools)
        marker = self.options.summary_marker
        first_human = next((message_text(m) for m in flat if getattr(m, "type", "") == "human"), "")
        purpose = "summary" if marker and marker in first_human and len(flat) <= 2 else "agent"
        md = to_json_safe(metadata or {}, limit)
        span = self.span_open(run_id, parent_run_id, "llm", (serialized or {}).get("name") or params.get("model") or "llm",
                              tags, metadata)
        serialized_id = (serialized or {}).get("id")
        entry = {
            "span_id": str(run_id), "purpose": purpose, "metadata": md, "invocation_params": params,
            "tools_hash": tools_hash, "tool_names": _tool_names(tools or []),
            "model": {"requested": params.get("model") or params.get("model_name") or md.get("ls_model_name"),
                      "provider": md.get("ls_provider"), "class": ".".join(serialized_id) if isinstance(serialized_id, list) else None},
            "request": {"n_messages": len(flat), "chars": sum(len(message_text(m)) for m in flat),
                        "messages": [serialize_message(m, limit) for m in flat]},
            "t_first_token": None, "n_stream_chunks": 0, "response": None, "error": None, "retries": [],
        }
        with self.lock:
            self.llm[str(run_id)] = entry
        span["ref"] = {"llm_call_id": str(run_id)}

    def llm_token(self, run_id) -> None:
        with self.lock:
            entry = self.llm.get(str(run_id))
            if entry is not None:
                entry["n_stream_chunks"] += 1
                if entry["t_first_token"] is None:
                    entry["t_first_token"] = time.time()

    def llm_end(self, run_id, response) -> None:
        span = self.span_close(run_id)
        with self.lock:
            entry = self.llm.get(str(run_id))
        if entry is None or span is None:
            return
        limit = self._limit()
        gen = response.generations[0][0] if getattr(response, "generations", None) and response.generations[0] else None
        msg = getattr(gen, "message", None)
        rm = dict(getattr(msg, "response_metadata", None) or {})
        entry["response"] = {
            "message": serialize_message(msg, limit) if msg is not None else None,
            "text": clip_str(message_text(msg) if msg is not None else (getattr(gen, "text", "") or ""), limit),
            "tool_calls": to_json_safe(list(getattr(msg, "tool_calls", None) or []), limit),
            "finish_reason": rm.get("finish_reason") or rm.get("stop_reason"),
            "response_id": getattr(msg, "id", None) or rm.get("id"),
            "system_fingerprint": rm.get("system_fingerprint"), "service_tier": rm.get("service_tier"),
            "model_returned": rm.get("model_name") or rm.get("model") or rm.get("model_id"),
            "response_metadata": to_json_safe(rm, limit),
            "llm_output": to_json_safe(getattr(response, "llm_output", None), limit),
            "generation_info": to_json_safe(getattr(gen, "generation_info", None), limit),
        }

    def llm_error(self, run_id, error) -> None:
        self.span_close(run_id, error)
        with self.lock:
            entry = self.llm.get(str(run_id))
        if entry is not None:
            entry["error"] = {"type": type(error).__name__, "message": clip_str(str(error), 4000)}

    def llm_retry(self, run_id, retry_state) -> None:
        outcome = getattr(retry_state, "outcome", None)
        exc = outcome.exception() if outcome is not None and getattr(outcome, "failed", False) else None
        item = {"at": time.time(), "attempt": getattr(retry_state, "attempt_number", None),
                "error": f"{type(exc).__name__}: {exc}"[:500] if exc else None}
        with self.lock:
            entry = self.llm.get(str(run_id))
            (entry["retries"] if entry is not None else self.retries).append(item)
            self.retries.append({**item, "span_id": str(run_id)})

    # ------------------------------------------------------------------ tools
    def tool_start(self, run_id, parent_run_id, name, input_str, inputs, tool_call_id, tags, metadata) -> None:
        limit = self._limit()
        args = inputs if isinstance(inputs, dict) else {}
        if not args and input_str:
            try:
                parsed = json.loads(input_str)
                args = parsed if isinstance(parsed, dict) else {"input": parsed}
            except ValueError:
                args = {"input": input_str}
        span = self.span_open(run_id, parent_run_id, "tool", name, tags, metadata)
        entry = {
            "span_id": str(run_id), "tool_call_id": str(tool_call_id or run_id), "name": name or "?",
            "input": to_json_safe(args, limit), "input_str": clip_str(str(input_str or ""), limit),
            "metadata": to_json_safe(metadata or {}, limit), "output": None, "error": None,
            "_raw_args": args,
        }
        with self.lock:
            self.tools[str(run_id)] = entry
        span["ref"] = {"tool_call_id": entry["tool_call_id"]}

    def tool_end(self, run_id, output) -> None:
        span = self.span_close(run_id)
        with self.lock:
            entry = self.tools.get(str(run_id))
        if entry is None or span is None:
            return
        out = serialize_tool_output(output, self._limit())
        entry["output"] = out
        if out.get("is_error"):
            span["status"] = "error"
            entry["error"] = {"type": "ToolError", "message": clip_str(out.get("text", ""), 2000)}

    def tool_error(self, run_id, error) -> None:
        self.span_close(run_id, error)
        with self.lock:
            entry = self.tools.get(str(run_id))
        if entry is not None:
            entry["error"] = {"type": type(error).__name__, "message": clip_str(str(error), 4000)}

    # ----------------------------------------------------------------- eventos
    def add_event(self, event: Any) -> None:
        try:
            data = event.to_dict()
        except Exception as e:
            self.note_error("event.to_dict", e)
            return
        with self.lock:
            self.events.append(data)

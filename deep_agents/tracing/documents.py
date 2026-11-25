"""Monta os documentos JSON de um run (spans, llm_calls, tool_calls, subagents, response, ...) a partir do `RunCollector`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from deep_agents.streaming.actions.classifier import classify
from deep_agents.tracing.collector import RunCollector
from deep_agents.tracing.serialize import clip_str, iso, message_text, to_json_safe
from deep_agents.tracing.store import SCHEMA_VERSION

_METRIC_KEYS = ("input_tokens", "output_tokens", "total_tokens", "cache_read_tokens", "cache_creation_tokens",
                "reasoning_tokens", "audio_in_tokens", "audio_out_tokens", "usage_source")


@dataclass
class EndInfo:
    status: str                                    # completed | error | cancelled
    ended_at: float
    answer: str = ""
    state: dict | None = None
    report: Any = None                             # RunReport
    stats: Any = None                              # RunStats
    sources: list[dict] = field(default_factory=list)
    publications: list[dict] = field(default_factory=list)
    error: BaseException | None = None
    error_traceback: str | None = None


def _r(x: float | None, n: int = 4) -> float | None:
    return None if x is None else round(x, n)


class _Builder:
    def __init__(self, c: RunCollector, end: EndInfo) -> None:
        self.c, self.end = c, end
        with c.lock:
            self.spans = sorted((dict(s) for s in c.spans.values()), key=lambda s: s["seq"])
            self.llm = {k: dict(v) for k, v in c.llm.items()}
            self.tools = {k: dict(v) for k, v in c.tools.items()}
            self.events = list(c.events)
            self.tool_schemas = dict(c.tool_schemas)
            self.retries = list(c.retries)
            self.cb_errors = list(c.callback_errors)
        self.span_by_id = {s["span_id"]: s for s in self.spans}
        self.metrics = {m.run_id: m for m in (getattr(end.report, "calls", None) or [])}
        self.t0 = c.t0

    # -- util --
    def off(self, ts: float | None) -> float | None:
        return None if ts is None else round(ts - self.t0, 4)

    def status_of(self, span: dict) -> str:
        return "unfinished" if span["status"] == "running" else span["status"]

    def enclosing_tasks(self, span: dict) -> list[str]:
        """Spans (tools `task`) que envolvem este span, do mais interno ao mais externo."""
        out, seen, pid = [], set(), span.get("parent_id")
        while pid and pid not in seen:
            seen.add(pid)
            tool = self.tools.get(pid)
            if tool is not None and tool["name"] == "task":
                out.append(pid)
            pid = (self.span_by_id.get(pid) or {}).get("parent_id")
        return out

    def agent_of(self, span: dict) -> tuple[str, str | None, list[str]]:
        tasks = self.enclosing_tasks(span)
        if tasks:
            tool = self.tools[tasks[0]]
            stype = (tool.get("_raw_args") or {}).get("subagent_type")
            return span.get("lc_agent_name") or stype or "subagent", tool["tool_call_id"], tasks
        return span.get("lc_agent_name") or "main", None, tasks

    # -- documentos --
    def llm_calls(self) -> list[dict[str, Any]]:
        calls = []
        for span in self.spans:
            e = self.llm.get(span["span_id"])
            if e is None:
                continue
            agent, agent_id, tasks = self.agent_of(span)
            m = self.metrics.get(span["span_id"])
            resp = e.get("response") or {}
            usage = {k: getattr(m, k, None) for k in _METRIC_KEYS} if m is not None else {}
            if m is None and resp.get("message"):
                um = resp["message"].get("usage_metadata") or {}
                usage = {"input_tokens": um.get("input_tokens", 0), "output_tokens": um.get("output_tokens", 0),
                         "total_tokens": um.get("total_tokens", 0), "usage_source": "usage_metadata" if um else "none"}
            latency = (span["t1"] - span["t0"]) if span["t1"] else None
            ttft = (e["t_first_token"] - span["t0"]) if e.get("t_first_token") else getattr(m, "time_to_first_token_s", None)
            model = dict(e["model"])
            model["returned"] = resp.get("model_returned") or getattr(m, "model_returned", None)
            calls.append({
                "llm_call_id": span["span_id"], "span_id": span["span_id"], "parent_span_id": span["parent_id"], "seq": span["seq"],
                "status": self.status_of(span), "purpose": e["purpose"], "agent": agent, "agent_id": agent_id, "ns": span["ns"],
                "node": span["node"], "step": span["step"], "parent_tool_call_id": self.tools[tasks[0]]["tool_call_id"] if tasks else None,
                "caused_tool_call_ids": [tc.get("id") for tc in (resp.get("tool_calls") or []) if isinstance(tc, dict)],
                "model": model, "invocation_params": e["invocation_params"], "tools_hash": e["tools_hash"],
                "tool_names": e["tool_names"], "tags": span["tags"], "metadata": e["metadata"],
                "started_at": iso(span["t0"]), "ended_at": iso(span["t1"]), "start_offset_s": self.off(span["t0"]),
                "latency_s": _r(latency), "ttft_s": _r(ttft), "n_stream_chunks": e["n_stream_chunks"],
                "streamed": e["n_stream_chunks"] > 0,
                "request": e["request"], "response": resp or None, "usage": usage,
                "cost_usd": getattr(m, "cost_usd", None), "tokens_per_second": getattr(m, "tokens_per_second", None),
                "retries": e["retries"], "error": e["error"],
            })
        return calls

    def tool_calls(self, llm_calls: list[dict]) -> list[dict[str, Any]]:
        caused = {}
        for call in llm_calls:
            for tid in call["caused_tool_call_ids"]:
                caused[tid] = call["llm_call_id"]
        calls = []
        for span in self.spans:
            e = self.tools.get(span["span_id"])
            if e is None:
                continue
            agent, agent_id, tasks = self.agent_of(span)
            kind, _vis, data = classify(e["name"], e.get("_raw_args"), description_chars=100_000)
            calls.append({
                "tool_call_id": e["tool_call_id"], "span_id": span["span_id"], "parent_span_id": span["parent_id"], "seq": span["seq"],
                "name": e["name"], "kind": str(kind.value), "status": self.status_of(span), "agent": agent, "agent_id": agent_id,
                "ns": span["ns"], "parent_tool_call_id": self.tools[tasks[0]]["tool_call_id"] if tasks else None,
                "caused_by_llm_call_id": caused.get(e["tool_call_id"]),
                "started_at": iso(span["t0"]), "ended_at": iso(span["t1"]), "start_offset_s": self.off(span["t0"]),
                "duration_s": _r((span["t1"] - span["t0"]) if span["t1"] else None),
                "input": e["input"], "input_str": e["input_str"], "output": e["output"],
                "output_chars": len((e["output"] or {}).get("text") or ""), "error": e["error"], "tags": span["tags"],
                "metadata": e["metadata"], "data": to_json_safe(data, 100_000),
            })
        return calls

    def spans_doc(self) -> dict[str, Any]:
        children: dict[str, list[str]] = {}
        for s in self.spans:
            if s["parent_id"] in self.span_by_id:
                children.setdefault(s["parent_id"], []).append(s["span_id"])
        out = []
        for s in self.spans:
            agent, agent_id, tasks = self.agent_of(s)
            item = {
                "span_id": s["span_id"], "parent_id": s["parent_id"] if s["parent_id"] in self.span_by_id else None,
                "children": children.get(s["span_id"], []), "type": s["type"], "name": s["name"], "seq": s["seq"],
                "status": self.status_of(s), "node": s["node"], "step": s["step"], "agent": agent, "agent_id": agent_id,
                "ns": s["ns"], "depth": len(tasks), "started_at": iso(s["t0"]), "ended_at": iso(s["t1"]),
                "start_offset_s": self.off(s["t0"]), "duration_s": _r((s["t1"] - s["t0"]) if s["t1"] else None),
                "tags": s["tags"], "error": s["error"], "io": s["io"],
            }
            if s.get("ref"):
                item["ref"] = s["ref"]
            out.append(item)
        roots = [s["span_id"] for s in out if s["parent_id"] is None]
        return {"schema_version": SCHEMA_VERSION, "run_id": self.c.run_id, "root_ids": roots, "spans": out}

    def subagents_doc(self, llm_calls: list[dict], tool_calls: list[dict]) -> dict[str, Any]:
        delegations: list[dict[str, Any]] = []

        def totals(task_tool_call_id: str | None) -> dict[str, Any]:
            mine_l = [c for c in llm_calls if task_tool_call_id and (c["parent_tool_call_id"] == task_tool_call_id
                      or task_tool_call_id in self._ancestors(c["span_id"]))]
            return {"llm_calls": len(mine_l), "input_tokens": sum(c["usage"].get("input_tokens") or 0 for c in mine_l),
                    "output_tokens": sum(c["usage"].get("output_tokens") or 0 for c in mine_l),
                    "cost_usd": round(sum(c["cost_usd"] or 0 for c in mine_l), 6)}

        for tc in tool_calls:
            if tc["name"] == "task":
                tid = tc["tool_call_id"]
                inner_l = [c["llm_call_id"] for c in llm_calls if tid in self._ancestors(c["span_id"])]
                inner_t = [t["tool_call_id"] for t in tool_calls if t is not tc and tid in self._ancestors(t["span_id"])]
                args = tc["input"] if isinstance(tc["input"], dict) else {}
                t = totals(tid)
                t["tool_calls"] = len(inner_t)
                delegations.append({
                    "id": tid, "type": "static", "subagent_type": args.get("subagent_type"), "description": args.get("description"),
                    "status": tc["status"], "started_at": tc["started_at"], "ended_at": tc["ended_at"], "start_offset_s": tc["start_offset_s"],
                    "duration_s": tc["duration_s"], "result": (tc["output"] or {}).get("text"), "error": tc["error"],
                    "parent_id": tc["parent_tool_call_id"], "llm_call_ids": inner_l, "tool_call_ids": inner_t, "totals": t,
                })
        dyn: dict[str, dict[str, Any]] = {}
        for ev in self.events:
            if ev.get("kind") != "subagent_dynamic":
                continue
            d = dyn.setdefault(ev["id"], {"id": ev["id"], "type": "dynamic", "subagent_type": ev.get("name"), "description": None,
                                          "status": "running", "started_at": None, "ended_at": None, "duration_s": None,
                                          "result": None, "error": None, "parent_id": ev.get("parent_id"), "llm_call_ids": [],
                                          "tool_call_ids": [], "totals": {}})
            data = ev.get("data") or {}
            if ev["phase"] == "start":
                d["started_at"] = iso(ev["ts"])
                d["description"] = data.get("description") or ev.get("label")
                d["subagent_type"] = ev.get("name") or d["subagent_type"]
            elif ev["phase"] in ("end", "error"):
                d["ended_at"] = iso(ev["ts"])
                d["duration_s"] = ev.get("duration_s")
                d["status"] = "error" if ev["phase"] == "error" else "completed"
                d["error"] = ev.get("error")
        delegations.extend(dyn.values())
        for tc in tool_calls:
            if tc["kind"] == "async_task":
                delegations.append({
                    "id": tc["tool_call_id"], "type": "async", "subagent_type": (tc["input"] or {}).get("subagent_type"),
                    "description": (tc["input"] or {}).get("description"), "status": tc["status"], "started_at": tc["started_at"],
                    "ended_at": tc["ended_at"], "duration_s": tc["duration_s"], "result": (tc["output"] or {}).get("text"),
                    "error": tc["error"], "parent_id": tc["parent_tool_call_id"], "llm_call_ids": [], "tool_call_ids": [],
                    "totals": {}, "action": (tc["data"] or {}).get("action"),
                })
        return {"schema_version": SCHEMA_VERSION, "run_id": self.c.run_id, "delegations": delegations}

    def _ancestors(self, span_id: str) -> set[str]:
        """tool_call_ids das `task` que envolvem o span."""
        span = self.span_by_id.get(span_id)
        return {self.tools[t]["tool_call_id"] for t in self.enclosing_tasks(span)} if span else set()

    def response_doc(self) -> dict[str, Any]:
        segs: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        reasoning, n_reason = [], 0
        for ev in self.events:
            if ev.get("agent") not in (None, "main"):
                continue
            if ev["kind"] == "response":
                mid = (ev.get("data") or {}).get("message_id") or ev["id"]
                if mid not in segs:
                    segs[mid] = {"message_id": mid, "final": None, "text": "", "n_deltas": 0, "first_delta_at": None, "last_delta_at": None}
                    order.append(mid)
                s = segs[mid]
                if ev["phase"] == "delta":
                    s["text"] += (ev.get("data") or {}).get("text", "")
                    s["n_deltas"] += 1
                    s["first_delta_at"] = s["first_delta_at"] or iso(ev["ts"])
                    s["last_delta_at"] = iso(ev["ts"])
                    s.setdefault("_first_ts", ev["ts"])
                    s["_last_ts"] = ev["ts"]
                elif ev["phase"] == "end":
                    s["final"] = (ev.get("data") or {}).get("final")
                    if (ev.get("data") or {}).get("text"):
                        s["text"] = ev["data"]["text"]
            elif ev["kind"] == "reasoning" and ev["phase"] == "delta":
                reasoning.append((ev.get("data") or {}).get("text", ""))
                n_reason += 1
        segments = [segs[m] for m in order]
        firsts = [s["_first_ts"] for s in segments if "_first_ts" in s]
        lasts = [s["_last_ts"] for s in segments if "_last_ts" in s]
        for s in segments:
            s.pop("_first_ts", None)
            s.pop("_last_ts", None)
        self.ttfr = _r(min(firsts) - self.t0) if firsts else None
        self.stream_s = _r(max(lasts) - min(firsts)) if firsts and lasts else None
        self.n_deltas = sum(s["n_deltas"] for s in segments)
        return {
            "schema_version": SCHEMA_VERSION, "run_id": self.c.run_id, "answer": self.end.answer, "segments": segments,
            "intermediate_texts": [s["text"] for s in segments if s["final"] is False and s["text"].strip()],
            "reasoning": {"text": "".join(reasoning), "n_deltas": n_reason},
            "timing": {"time_to_first_response_delta_s": self.ttfr, "response_stream_s": self.stream_s, "n_response_deltas": self.n_deltas},
        }

    def conversation_doc(self) -> dict[str, Any]:
        limit = self.c.options.max_str_chars
        state = self.end.state if isinstance(self.end.state, dict) else {}
        files = {}
        for path, f in (state.get("files") or {}).items():
            content = f.get("content") if isinstance(f, dict) else f
            text = "\n".join(content) if isinstance(content, list) else str(content)
            files[str(path)] = {"chars": len(text), "content": clip_str(text, limit)}
        return {
            "schema_version": SCHEMA_VERSION, "run_id": self.c.run_id,
            "input_messages": self.c.meta.get("input_messages", []),
            "final_messages": to_json_safe(list(state.get("messages") or []), limit),
            "todos": to_json_safe(state.get("todos") or [], limit), "files": files, "state_keys": sorted(map(str, state)),
        }

    def errors_doc(self, llm_calls: list[dict], tool_calls: list[dict]) -> dict[str, Any]:
        errors = []
        for c in llm_calls:
            if c["error"]:
                errors.append({"where": "llm", "name": c["model"].get("requested"), "span_id": c["span_id"], "at": c["ended_at"], **c["error"]})
        for t in tool_calls:
            if t["error"]:
                errors.append({"where": "tool", "name": t["name"], "span_id": t["span_id"], "at": t["ended_at"], **t["error"]})
        for s in self.spans:
            if s["type"] == "chain" and s["error"]:
                errors.append({"where": "chain", "name": s["name"], "span_id": s["span_id"], "at": iso(s["t1"]), **s["error"]})
        if self.end.error is not None:
            errors.append({"where": "run", "name": None, "span_id": None, "at": iso(self.end.ended_at),
                           "type": type(self.end.error).__name__, "message": str(self.end.error)[:4000],
                           "traceback": self.end.error_traceback})
        warnings = []
        for ev in self.events:
            if ev["kind"] == "notice":
                warnings.append({"type": "notice", "message": (ev.get("data") or {}).get("message"), "at": iso(ev["ts"])})
        for m in (self.end.state or {}).get("messages", []) if isinstance(self.end.state, dict) else []:
            text = message_text(m)
            if "limits exceeded" in text.lower() and getattr(m, "type", "") == "ai":
                warnings.append({"type": "model_call_limit", "message": clip_str(text, 500), "at": None})
        for e in self.cb_errors:
            warnings.append({"type": "tracing_callback_error", "message": f"{e['where']}: {e['type']}: {e['message']}", "at": iso(e["at"])})
        return {"schema_version": SCHEMA_VERSION, "run_id": self.c.run_id, "errors": errors, "retries": self.retries, "warnings": warnings}

    def run_doc(self, llm_calls, tool_calls, delegations) -> dict[str, Any]:
        c, end, meta = self.c, self.end, self.c.meta
        report = end.report
        by_agent: dict[str, dict[str, Any]] = {}
        for call in llm_calls:
            a = by_agent.setdefault(call["agent"], {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": None, "tool_calls": 0, "llm_time_s": 0.0})
            a["llm_calls"] += 1
            a["input_tokens"] += call["usage"].get("input_tokens") or 0
            a["output_tokens"] += call["usage"].get("output_tokens") or 0
            if call["cost_usd"] is not None:   # sem preço configurado o custo fica nulo (não 0.0)
                a["cost_usd"] = round((a["cost_usd"] or 0) + call["cost_usd"], 6)
            a["llm_time_s"] = round(a["llm_time_s"] + (call["latency_s"] or 0), 4)
        for t in tool_calls:
            by_agent.setdefault(t["agent"], {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": None, "tool_calls": 0, "llm_time_s": 0.0})["tool_calls"] += 1
        by_tool: dict[str, dict[str, Any]] = {}
        for t in tool_calls:
            b = by_tool.setdefault(t["name"], {"calls": 0, "errors": 0, "total_s": 0.0, "max_s": 0.0})
            b["calls"] += 1
            b["errors"] += 1 if t["error"] else 0
            b["total_s"] = round(b["total_s"] + (t["duration_s"] or 0), 4)
            b["max_s"] = max(b["max_s"], t["duration_s"] or 0)
        for b in by_tool.values():
            b["avg_s"] = round(b["total_s"] / b["calls"], 4) if b["calls"] else 0.0

        def tot(key: str) -> int:
            return sum(call["usage"].get(key) or 0 for call in llm_calls)

        costs = [call["cost_usd"] for call in llm_calls if call["cost_usd"] is not None]
        wall = getattr(report, "wall_time_s", None) or (end.ended_at - c.t0)
        first_llm = next((x for x in llm_calls if x["purpose"] == "agent" and x["agent"] == "main"), None)
        ttft_abs = _r((first_llm["start_offset_s"] or 0) + first_llm["ttft_s"]) if first_llm and first_llm["ttft_s"] is not None else None
        files_touched: dict[str, list[str]] = {}
        for t in tool_calls:
            if t["kind"] == "file" and (t["data"] or {}).get("path"):
                files_touched.setdefault(t["data"]["path"], [])
                if t["data"]["op"] not in files_touched[t["data"]["path"]]:
                    files_touched[t["data"]["path"]].append(t["data"]["op"])
        skills = []
        for t in tool_calls:
            s = (t["data"] or {}).get("skill")
            if t["kind"] == "skill" and s and s not in skills:
                skills.append(s)
        model = dict(meta.get("model") or {})
        model["models_used"] = sorted({(x["model"].get("returned") or x["model"].get("requested") or "?") for x in llm_calls})
        totals = {
            "llm_calls": len(llm_calls), "main_llm_calls": sum(1 for x in llm_calls if x["agent"] == "main" and x["purpose"] == "agent"),
            "subagent_llm_calls": sum(1 for x in llm_calls if x["agent"] != "main"),
            "summary_llm_calls": sum(1 for x in llm_calls if x["purpose"] == "summary"),
            "input_tokens": tot("input_tokens"), "output_tokens": tot("output_tokens"), "total_tokens": tot("total_tokens"),
            "cache_read_tokens": tot("cache_read_tokens"), "cache_creation_tokens": tot("cache_creation_tokens"),
            "reasoning_tokens": tot("reasoning_tokens"), "cost_usd": round(sum(costs), 6) if costs else None,
            "tool_calls": len(tool_calls), "subagent_calls": sum(1 for d in delegations if d["type"] == "static"),
            "dynamic_subagents": sum(1 for d in delegations if d["type"] == "dynamic"),
            "errors": sum(1 for x in llm_calls if x["error"]) + sum(1 for x in tool_calls if x["error"]) + (1 if end.error else 0),
        }
        answer = end.answer or ""
        index_entry = {
            "run_id": c.run_id, "session_id": meta.get("session_id"), "turn": meta.get("turn"), "origin": meta.get("origin"),
            "status": end.status, "started_at": iso(c.t0), "duration_s": _r(wall), "user_message": clip_str(meta.get("user_message", ""), 200),
            "answer_preview": clip_str(" ".join(answer.split()), 200), "model": model.get("spec"), "config_hash": meta.get("config_hash"),
            "input_tokens": totals["input_tokens"], "output_tokens": totals["output_tokens"], "cost_usd": totals["cost_usd"],
            "llm_calls": totals["llm_calls"], "tool_calls": totals["tool_calls"],
            "subagent_calls": totals["subagent_calls"] + totals["dynamic_subagents"], "errors": totals["errors"],
            "path": f"runs/{c.run_id}",
        }
        return {
            "schema_version": SCHEMA_VERSION, "run_id": c.run_id, "label": meta.get("label"), "session_id": meta.get("session_id"),
            "turn": meta.get("turn"), "origin": meta.get("origin"), "status": end.status, "started_at": iso(c.t0),
            "ended_at": iso(end.ended_at), "duration_s": _r(wall),
            "input": {"user_message": meta.get("user_message"), "history_messages": meta.get("history_messages"),
                      "history_chars": meta.get("history_chars")},
            "output": {"answer": answer, "answer_chars": len(answer), "n_sources": len(end.sources)},
            "model": model, "config_hash": meta.get("config_hash"),
            "config_path": f"configs/{meta['config_hash']}.json" if meta.get("config_hash") else None,
            "totals": totals,
            "timing": {"wall_time_s": _r(wall), "llm_time_s": _r(sum(x["latency_s"] or 0 for x in llm_calls)),
                       "tool_time_s": _r(sum(t["duration_s"] or 0 for t in tool_calls if t["kind"] not in ("subagent", "code_eval"))),
                       "time_to_first_llm_token_s": ttft_abs, "time_to_first_response_delta_s": self.ttfr,
                       "response_stream_s": self.stream_s, "n_response_deltas": self.n_deltas},
            "by_agent": by_agent, "by_tool": by_tool, "skills_used": skills,
            "files_touched": [{"path": p, "ops": ops} for p, ops in files_touched.items()],
            "report_summary": to_json_safe(report.summary()) if report is not None else None,
            "stats": to_json_safe(end.stats.to_dict()) if end.stats is not None else None,
            "error": ({"type": type(end.error).__name__, "message": str(end.error)[:4000], "traceback": end.error_traceback}
                      if end.error is not None else None),
            "environment": meta.get("environment"), "tags": [], "annotations": {},
            "index_entry": index_entry,
        }


def build_documents(c: RunCollector, end: EndInfo) -> dict[str, Any]:
    """Todos os documentos do run, por nome de arquivo (o `run.json` inclui `index_entry` e fica sem `files`)."""
    b = _Builder(c, end)
    llm_calls = b.llm_calls()
    tool_calls = b.tool_calls(llm_calls)
    subagents = b.subagents_doc(llm_calls, tool_calls)
    response = b.response_doc()     # antes do run.json: calcula ttfr/stream_s/n_deltas
    docs = {
        "spans.json": b.spans_doc(),
        "llm_calls.json": {"schema_version": SCHEMA_VERSION, "run_id": c.run_id, "tool_schemas": b.tool_schemas, "calls": llm_calls},
        "tool_calls.json": {"schema_version": SCHEMA_VERSION, "run_id": c.run_id, "calls": tool_calls},
        "subagents.json": subagents,
        "events.json": {"schema_version": SCHEMA_VERSION, "run_id": c.run_id, "count": len(b.events), "events": b.events},
        "response.json": response,
        "sources.json": {"schema_version": SCHEMA_VERSION, "run_id": c.run_id, "sources": end.sources, "publications": end.publications},
        "errors.json": b.errors_doc(llm_calls, tool_calls),
        "conversation.json": b.conversation_doc(),
    }
    docs["run.json"] = b.run_doc(llm_calls, tool_calls, subagents["delegations"])
    return docs

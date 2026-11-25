"""Tracer com o agente REAL (create_deep_agent + middlewares) e modelo falso com tokens: confere os JSONs gravados."""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import AIMessage

from deep_agents.bootstrap import STREAMING, SUBAGENTS, TOOLKIT
from deep_agents.model.model_config import ModelConfig
from deep_agents.streaming import AgentStreamer
from deep_agents.tracing import TraceOptions, Tracer, build_config_snapshot
from deep_agents.tracing.serialize import clip_str, to_json_safe
from tests.fakes import search, tool_round
from tests.fakes_stream import StreamingScriptedChat
from tests.test_streaming_e2e import ANSWER, USER, Boom, DelegatingStream, Slow, build, run

ALL_FILES = {"run.json", "conversation.json", "spans.json", "llm_calls.json", "tool_calls.json", "subagents.json",
             "events.json", "response.json", "sources.json", "errors.json"}


def make_tracer(tmp_path: Path, **opts) -> Tracer:
    snap = lambda cfg: build_config_snapshot(cfg, toolkit=TOOLKIT, subagents=SUBAGENTS, dynamic={"enabled": False}, streaming=STREAMING)  # noqa: E731
    return Tracer(TraceOptions(base_dir=tmp_path / "tracing", **opts), config_snapshot=snap, session_provider=lambda: "sess-1")


def load(tracer: Tracer, run_id: str) -> dict:
    return tracer.load_run(run_id)


def test_tool_run_writes_every_file(tmp_path):
    tracer = make_tracer(tmp_path)
    agent, gw = build(StreamingScriptedChat(script=[tool_round(search("real madrid")), AIMessage(ANSWER)]))
    handle, events = run(AgentStreamer(agent, gw, tracer=tracer, origin="cli"))
    rid = handle.run_id
    docs = load(tracer, rid)

    assert set(docs) == ALL_FILES                         # gravados ANTES de o iterador terminar
    runj = docs["run.json"]
    assert runj["status"] == "completed" and runj["origin"] == "cli" and runj["session_id"] == "sess-1"
    assert runj["input"]["user_message"] == "oi" and runj["output"]["answer"] == ANSWER
    assert runj["model"]["spec"] == "openai:gpt-6.1-sol" and runj["config_hash"]
    assert runj["totals"]["llm_calls"] == 2 and runj["totals"]["input_tokens"] == 20 and runj["totals"]["tool_calls"] == 1
    assert runj["by_tool"]["internet_search"]["calls"] == 1
    assert runj["timing"]["wall_time_s"] and runj["timing"]["n_response_deltas"] > 0
    assert runj["environment"]["python"] and "files" in runj and runj["files"]["llm_calls.json"]["bytes"] > 0

    llm = docs["llm_calls.json"]
    first, second = llm["calls"]
    assert first["request"]["messages"][0]["type"] == "system" and first["request"]["messages"][0]["content"]
    assert first["request"]["messages"][-1]["content"] == "oi"
    assert [c["name"] for c in first["response"]["tool_calls"]] == ["internet_search"]
    assert first["tools_hash"] is None or first["tools_hash"] in llm["tool_schemas"]   # o modelo falso não repassa os schemas
    assert any(m["type"] == "tool" for m in second["request"]["messages"])      # o resultado da tool voltou ao modelo
    assert second["response"]["text"].strip() == ANSWER and second["usage"]["input_tokens"] == 10
    assert first["streamed"] and first["status"] == "completed" and first["latency_s"] is not None
    assert first["agent"] == "main" and first["purpose"] == "agent"

    tool = docs["tool_calls.json"]["calls"][0]
    assert tool["name"] == "internet_search" and tool["input"]["query"] == "real madrid"
    assert tool["output"]["text"] and tool["caused_by_llm_call_id"] == first["llm_call_id"]
    assert tool["kind"] == "tool" and tool["duration_s"] is not None

    spans = docs["spans.json"]
    ids = {s["span_id"] for s in spans["spans"]}
    assert spans["root_ids"] and {first["span_id"], tool["span_id"]} <= ids
    assert all(c in ids for s in spans["spans"] for c in s["children"])

    assert docs["events.json"]["count"] == len(events) and docs["response.json"]["answer"] == ANSWER
    assert docs["conversation.json"]["input_messages"][0]["content"] == "oi"
    assert docs["conversation.json"]["final_messages"]

    index = tracer.list_runs()
    assert index[0]["run_id"] == rid and index[0]["status"] == "completed" and index[0]["llm_calls"] == 2
    sessions = json.loads((tmp_path / "tracing" / "sessions.json").read_text(encoding="utf-8"))
    assert sessions["sessions"]["sess-1"]["run_ids"] == [rid] and sessions["sessions"]["sess-1"]["totals"]["llm_calls"] == 2
    cfg = json.loads((tmp_path / "tracing" / "configs" / f"{runj['config_hash']}.json").read_text(encoding="utf-8"))
    assert cfg["prompts"]["system_prompt"] and cfg["limits"]["model_call_limit"] and cfg["subagents"]["pesquisador"]["enabled"]


def test_subagent_attribution(tmp_path):
    tracer = make_tracer(tmp_path)
    agent, gw = build(DelegatingStream(), subagents=True)
    handle, _ = run(AgentStreamer(agent, gw, tracer=tracer, origin="web"))
    docs = load(tracer, handle.run_id)

    tools = docs["tool_calls.json"]["calls"]
    task = next(t for t in tools if t["name"] == "task")
    inner = next(t for t in tools if t["name"] == "internet_search")
    assert task["kind"] == "subagent" and task["agent"] == "main"
    assert inner["agent"] == "pesquisador" and inner["parent_tool_call_id"] == task["tool_call_id"]
    llm = docs["llm_calls.json"]["calls"]
    assert any(c["agent"] == "pesquisador" and c["parent_tool_call_id"] == task["tool_call_id"] for c in llm)

    (deleg,) = docs["subagents.json"]["delegations"]
    assert deleg["type"] == "static" and deleg["subagent_type"] == "pesquisador" and deleg["description"] == "Ângulo A"
    assert deleg["result"] and inner["tool_call_id"] in deleg["tool_call_ids"] and deleg["totals"]["llm_calls"] >= 1
    assert "pesquisador" in docs["run.json"]["by_agent"] and docs["run.json"]["totals"]["subagent_calls"] == 1
    assert docs["run.json"]["totals"]["subagent_llm_calls"] >= 1
    spans = {s["span_id"]: s for s in docs["spans.json"]["spans"]}
    assert spans[inner["span_id"]]["depth"] >= 1


def test_error_run_is_recorded(tmp_path):
    tracer = make_tracer(tmp_path)
    agent, gw = build(Boom())
    handle, _ = run(AgentStreamer(agent, gw, tracer=tracer))
    docs = load(tracer, handle.run_id)

    assert docs["run.json"]["status"] == "error" and "falha do provedor" in docs["run.json"]["error"]["message"]
    assert "Traceback" in docs["run.json"]["error"]["traceback"]
    errs = docs["errors.json"]["errors"]
    assert any(e["where"] == "run" for e in errs)
    assert tracer.list_runs()[0]["status"] == "error"


def test_cancelled_run_is_recorded(tmp_path):
    from deep_agents.streaming import EventKind, Phase
    tracer = make_tracer(tmp_path)
    agent, gw = build(Slow())
    handle = AgentStreamer(agent, gw, tracer=tracer).start(USER)
    for ev in handle:
        if ev.kind is EventKind.RESPONSE and ev.phase is Phase.DELTA:
            handle.cancel()
    handle.join(10)
    assert tracer.load_run(handle.run_id)["run.json"]["status"] == "cancelled"


def test_disabled_writes_nothing_and_never_breaks_the_run(tmp_path):
    tracer = make_tracer(tmp_path, enabled=False)
    agent, gw = build(StreamingScriptedChat(script=[AIMessage(ANSWER)]))
    handle, _ = run(AgentStreamer(agent, gw, tracer=tracer))
    assert handle.result.answer == ANSWER and not (tmp_path / "tracing").exists()


def test_broken_store_does_not_break_the_run(tmp_path):
    blocker = tmp_path / "tracing"
    blocker.write_text("sou um arquivo, não uma pasta")       # mkdir falha
    tracer = make_tracer(tmp_path)
    agent, gw = build(StreamingScriptedChat(script=[AIMessage(ANSWER)]))
    handle, events = run(AgentStreamer(agent, gw, tracer=tracer))
    assert handle.result.answer == ANSWER and events[-1].phase.value == "end"


def test_rebuild_index_from_run_files(tmp_path):
    tracer = make_tracer(tmp_path)
    agent, gw = build(StreamingScriptedChat(script=[AIMessage(ANSWER)] * 2))
    ids = [run(AgentStreamer(agent, gw, tracer=tracer))[0].run_id for _ in range(2)]
    (tmp_path / "tracing" / "index.json").unlink()
    index = tracer.rebuild_index()
    assert {r["run_id"] for r in index["runs"]} == set(ids)
    assert len(tracer.list_runs(session_id="sess-1")) == 2


def test_secrets_are_redacted_and_long_text_clipped():
    safe = to_json_safe({"api_key": "sk-123", "max_tokens": 50, "headers": {"Authorization": "Bearer x"},
                         "nested": {"password": "p", "ok": 1}, "texto": "a" * 50}, limit=10)
    assert safe["api_key"] == "[redacted]" and safe["headers"] == "[redacted]" and safe["nested"]["password"] == "[redacted]"
    assert safe["max_tokens"] == 50 and safe["nested"]["ok"] == 1
    assert safe["texto"].startswith("a" * 10) and "+40 chars truncados" in safe["texto"]
    assert clip_str("abc", 10) == "abc"


def test_run_files_have_no_secret_like_values(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-value")
    tracer = make_tracer(tmp_path)
    agent, gw = build(StreamingScriptedChat(script=[AIMessage(ANSWER)]))
    handle, _ = run(AgentStreamer(agent, gw, tracer=tracer))
    blob = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "tracing").rglob("*.json"))
    assert "sk-super-secret-value" not in blob and handle.run_id in blob


def test_tool_schemas_are_pooled_by_hash(tmp_path):
    from uuid import uuid4

    from langchain_core.messages import HumanMessage, SystemMessage

    from deep_agents.tracing.collector import RunCollector
    from deep_agents.tracing.documents import EndInfo, build_documents
    import time

    c = RunCollector("r1", TraceOptions(base_dir=tmp_path), {"user_message": "oi"})
    schema = [{"type": "function", "function": {"name": "internet_search", "description": "busca", "parameters": {}}}]
    for _ in range(2):   # duas chamadas com as mesmas tools: um só schema no pool
        rid = uuid4()
        c.llm_start(rid, None, {"id": ["x", "FakeChat"]}, [[SystemMessage(content="sys"), HumanMessage(content="oi")]], [], {},
                    {"model": "m", "api_key": "sk-x", "tools": schema})
    docs = build_documents(c, EndInfo(status="completed", ended_at=time.time()))
    llm = docs["llm_calls.json"]
    assert len(llm["tool_schemas"]) == 1 and all(call["tool_names"] == ["internet_search"] for call in llm["calls"])
    assert llm["calls"][0]["invocation_params"]["api_key"] == "[redacted]" and "tools" not in llm["calls"][0]["invocation_params"]

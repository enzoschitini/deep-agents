"""Testes offline do ActionTracker (callbacks, classificador, parsers de updates/custom, labels, to_jsonable)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from enum import Enum

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langgraph.types import Command, Interrupt

from deep_agents.streaming.actions import ActionTracker
from deep_agents.streaming.actions.classifier import classify
from deep_agents.streaming.actions.labels import label
from deep_agents.streaming.actions.summarize import clip, safe_repr, to_jsonable
from deep_agents.streaming.bus import EventBus
from deep_agents.streaming.events import EventKind, Phase, StreamEvent, Visibility
from deep_agents.streaming.options import StreamOptions
from deep_agents.streaming.registry import RunRegistry


def make(options: StreamOptions | None = None):
    bus = EventBus("run-1")
    registry = RunRegistry()
    tracker = ActionTracker(bus, registry, options or StreamOptions(summary_marker="Resuma a conversa"))
    events: list[StreamEvent] = []
    bus.add_sink(events.append)
    return tracker, registry, events


def md(ns: str = "tools:A", agent: str | None = None) -> dict:
    return {"langgraph_checkpoint_ns": ns, "lc_agent_name": agent}


def tool(tracker, name, args, *, ns="tools:A", agent=None, call_id=None, output="ok", error=None):
    run_id, call_id = uuid.uuid4(), call_id or f"call-{uuid.uuid4().hex[:6]}"
    h = tracker.handler
    h.on_tool_start({"name": name}, str(args), run_id=run_id, metadata=md(ns, agent), inputs=args, tool_call_id=call_id)
    if error is not None:
        h.on_tool_error(error, run_id=run_id)
    else:
        h.on_tool_end(output, run_id=run_id)
    return call_id


def llm(tracker, msg: AIMessage | None, *, ns="model:M", agent=None, human="ciao", fail=None):
    run_id = uuid.uuid4()
    h = tracker.handler
    h.on_chat_model_start({"name": "Fake"}, [[HumanMessage(human)]], run_id=run_id, metadata=md(ns, agent),
                          invocation_params={"model": "fake-model"})
    if fail is not None:
        h.on_llm_error(fail, run_id=run_id)
    else:
        h.on_llm_end(LLMResult(generations=[[ChatGeneration(message=msg)]]), run_id=run_id)
    return run_id


# ----------------------------------------------------------------- classify
@pytest.mark.parametrize("name,args,kind,vis", [
    ("task", {"subagent_type": "pesquisador", "description": "x"}, EventKind.SUBAGENT, Visibility.PRIMARY),
    ("eval", {"code": "1+1"}, EventKind.CODE_EVAL, Visibility.SECONDARY),
    ("write_todos", {"todos": [{"content": "a", "status": "completed"}, {"content": "b", "status": "pending"}]}, EventKind.TODOS, Visibility.PRIMARY),
    ("read_file", {"file_path": "/prompts/skills/busca-na-web/SKILL.md"}, EventKind.SKILL, Visibility.PRIMARY),
    ("read_file", {"file_path": "/workspace/a.md"}, EventKind.FILE, Visibility.SECONDARY),
    ("ls", {"path": "/"}, EventKind.FILE, Visibility.SECONDARY),
    ("write_file", {"file_path": "/a"}, EventKind.FILE, Visibility.SECONDARY),
    ("edit_file", {"file_path": "/a"}, EventKind.FILE, Visibility.SECONDARY),
    ("glob", {"pattern": "*.md"}, EventKind.FILE, Visibility.SECONDARY),
    ("grep", {"pattern": "x"}, EventKind.FILE, Visibility.SECONDARY),
    ("start_async_task", {"description": "d", "subagent_type": "s"}, EventKind.ASYNC_TASK, Visibility.PRIMARY),
    ("check_async_task", {"task_id": "t"}, EventKind.ASYNC_TASK, Visibility.PRIMARY),
    ("update_async_task", {"task_id": "t"}, EventKind.ASYNC_TASK, Visibility.PRIMARY),
    ("cancel_async_task", {"task_id": "t"}, EventKind.ASYNC_TASK, Visibility.PRIMARY),
    ("list_async_tasks", {}, EventKind.ASYNC_TASK, Visibility.PRIMARY),
    ("internet_search", {"query": "q"}, EventKind.TOOL, Visibility.PRIMARY),
])
def test_classify(name, args, kind, vis):
    got_kind, got_vis, _ = classify(name, args)
    assert (got_kind, got_vis) == (kind, vis)


def test_classify_data():
    assert classify("write_todos", {"todos": [{"status": "completed"}, {"status": "pending"}]})[2]["done"] == 1
    assert classify("write_todos", {"todos": [{"status": "completed"}, {"status": "pending"}]})[2]["total"] == 2
    assert classify("read_file", {"file_path": "/prompts/skills/busca-na-web/SKILL.md"})[2]["skill"] == "busca-na-web"
    assert classify("ls", {"path": "/x"})[2] == {"op": "ls", "path": "/x"}
    assert classify("cancel_async_task", {"task_id": "t"})[2]["action"] == "cancel"
    assert classify("task", {"subagent_type": "p", "description": "d" * 1000}, description_chars=50)[2]["description"].endswith("…")


# ----------------------------------------------------------------- handler: tools
def test_tool_start_end_with_duration_and_label():
    tracker, _, events = make()
    tool(tracker, "internet_search", {"query": "ia"}, call_id="c1", ns="tools:A", output="risultati")
    start, end = events
    assert (start.kind, start.phase, start.id) == (EventKind.TOOL, Phase.START, "c1")
    assert start.label == "Consulto lo strumento internet_search «ia»…"
    assert start.args == {"query": "ia"} and start.parent_id is None and start.agent == "main" and start.depth == 0
    assert end.phase == Phase.END and end.id == "c1" and end.summary == "risultati" and end.duration_s >= 0


def test_tool_error_and_error_detection():
    tracker, _, events = make()
    tool(tracker, "internet_search", {"query": "x"}, error=RuntimeError("boom"))
    err = events[-1]
    assert err.phase == Phase.ERROR and "RuntimeError: boom" in err.error and err.visibility == Visibility.PRIMARY
    tool(tracker, "read_file", {"file_path": "/x"}, output="Error: File '/x' not found")
    assert events[-1].phase == Phase.ERROR and events[-1].visibility == Visibility.PRIMARY
    tool(tracker, "foo", {}, output=ToolMessage("falhou", tool_call_id="1", status="error"))
    assert events[-1].phase == Phase.ERROR
    assert tracker.stats().errors == 3


def test_tool_output_command_and_toolmessage():
    tracker, _, events = make()
    cmd = Command(update={"messages": [ToolMessage("relatorio do subagent", tool_call_id="t1")]})
    tool(tracker, "task", {"subagent_type": "pesquisador", "description": "d"}, ns="tools:X", output=cmd)
    assert events[-1].summary == "relatorio do subagent"
    tool(tracker, "foo", {}, output=ToolMessage("conteudo", tool_call_id="1"))
    assert events[-1].summary == "conteudo"


def test_capture_raw():
    tracker, _, events = make(StreamOptions(capture_raw=True))
    tool(tracker, "foo", {}, output="bruto")
    assert events[-1].raw == "bruto"
    tracker2, _, events2 = make()
    tool(tracker2, "foo", {}, output="bruto")
    assert events2[-1].raw is None


def test_summary_chars_and_arg_chars():
    tracker, _, events = make(StreamOptions(summary_chars=20, arg_chars=10))
    tool(tracker, "foo", {"q": "a" * 100}, output="b" * 100)
    assert len(events[0].args["q"]) == 10 and len(events[-1].summary) == 20


def test_task_subagent_hierarchy():
    """`task` registra o ns do subagent; tools e LLM dentro dele ganham parent_id/agent/depth corretos."""
    tracker, registry, events = make()
    h = tracker.handler
    rid = uuid.uuid4()
    h.on_tool_start({"name": "task"}, "", run_id=rid, metadata=md("tools:X"), inputs={"subagent_type": "pesquisador", "description": "pesquisar ia"},
                    tool_call_id="call-task")
    sub = events[0]
    assert sub.kind == EventKind.SUBAGENT and sub.name == "pesquisador" and sub.id == "call-task" and sub.depth == 0
    assert sub.label == "Consulto il subagent pesquisador «pesquisar ia»…" and sub.data["description"] == "pesquisar ia"
    assert registry.parent_for("tools:X") == "call-task"

    tool(tracker, "internet_search", {"query": "q"}, ns="tools:X|tools:Y", agent="pesquisador", call_id="c-inner")
    inner = events[1]
    assert inner.parent_id == "call-task" and inner.agent == "pesquisador" and inner.agent_id == "call-task"
    assert inner.depth == 1 and inner.ns == ("tools:X",)

    llm(tracker, AIMessage("ok"), ns="tools:X|model:Z", agent="pesquisador")
    call = events[3]
    assert call.kind == EventKind.MODEL_CALL and call.parent_id == "call-task" and call.visibility == Visibility.DEBUG

    h.on_tool_end(Command(update={"messages": [ToolMessage("relatorio", tool_call_id="call-task")]}), run_id=rid)
    assert events[-1].phase == Phase.END and events[-1].summary == "relatorio" and events[-1].kind == EventKind.SUBAGENT
    stats = tracker.stats()
    assert stats.n_subagents == 1 and stats.n_tools == 2 and stats.tools == {"task": 1, "internet_search": 1} and stats.n_llm_calls == 1


def test_nested_subagent_depth():
    tracker, registry, events = make()
    tracker.handler.on_tool_start({"name": "task"}, "", run_id=uuid.uuid4(), metadata=md("tools:A|tools:B", "pai"),
                                  inputs={"subagent_type": "filho", "description": "d"}, tool_call_id="c-b")
    registry.register_subagent_ns("tools:A", tool_call_id="c-a", name="pai")
    tool(tracker, "foo", {}, ns="tools:A|tools:B|tools:C", agent="filho", call_id="c-c")
    # `task` aninhada: ns do agente = tools:A (pai)
    assert events[0].ns == ("tools:A",) and events[0].depth == 1


def test_skill_todos_file_eval_async():
    tracker, _, events = make()
    tool(tracker, "read_file", {"file_path": "/prompts/skills/busca-na-web/SKILL.md"})
    assert events[-1].kind == EventKind.SKILL and events[0].label == "Leggo la skill busca-na-web"
    tool(tracker, "write_todos", {"todos": [{"content": "a", "status": "completed"}, {"content": "b", "status": "pending"}]})
    assert events[-2].label == "Aggiorno il piano (1/2)"
    tool(tracker, "write_file", {"file_path": "/workspace/x.md"})
    assert events[-2].kind == EventKind.FILE and events[-2].label == "Scrivo «/workspace/x.md»" and events[-2].visibility == Visibility.SECONDARY
    tool(tracker, "eval", {"code": "await task()"})
    assert events[-2].label == "Eseguo codice nel REPL (eval)"
    tool(tracker, "start_async_task", {"description": "d", "subagent_type": "s"})
    assert events[-2].label == "Avvio un subagent asincrono…"
    stats = tracker.stats()
    assert stats.skills == ["busca-na-web"] and stats.files == ["/workspace/x.md"] and stats.todos_updates == 1


# ----------------------------------------------------------------- handler: LLM
def test_llm_call_decision_and_usage():
    tracker, registry, events = make()
    msg = AIMessage("", tool_calls=[{"id": "c1", "name": "internet_search", "args": {"query": "ia"}, "type": "tool_call"}],
                    usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                    response_metadata={"finish_reason": "tool_calls"})
    rid = llm(tracker, msg, ns="model:M")
    start, end = events
    assert start.kind == EventKind.MODEL_CALL and start.phase == Phase.START and start.visibility == Visibility.SECONDARY
    assert start.data["model"] == "fake-model" and start.data["n_messages"] == 1 and start.label == "Interrogo il modello…"
    assert end.id == str(rid) and end.data["usage"]["total_tokens"] == 15 and end.data["finish_reason"] == "tool_calls"
    assert end.data["decision"]["tool_calls"] == [{"id": "c1", "name": "internet_search", "args": {"query": "ia"}}]
    assert end.data["decision"]["has_text"] is False and end.data["latency_s"] >= 0
    assert registry.llm_purpose(f"lc_run--{rid}") == "agent"


def test_llm_summary_purpose_and_events():
    tracker, registry, events = make()
    rid = llm(tracker, AIMessage("resumo ok"), human="Resuma a conversa abaixo: ...")
    kinds = [(e.kind, e.phase) for e in events]
    assert (EventKind.SUMMARIZATION, Phase.START) in kinds and (EventKind.SUMMARIZATION, Phase.END) in kinds
    assert registry.llm_purpose(str(rid)) == "summary"
    assert events[-1].label == "Contesto riassunto"


def test_llm_error_is_primary():
    tracker, _, events = make()
    llm(tracker, None, fail=ValueError("rate limit"))
    err = events[-1]
    assert err.phase == Phase.ERROR and err.visibility == Visibility.PRIMARY and "rate limit" in err.error
    assert tracker.stats().errors == 1


def test_handler_never_raises():
    tracker, _, events = make()
    h = tracker.handler
    h.on_tool_start(None, None, run_id=uuid.uuid4(), metadata=object())   # entrada inválida
    h.on_llm_end(object(), run_id=uuid.uuid4())
    h.on_tool_end("x", run_id=uuid.uuid4())                                # run desconhecido
    assert h.raise_error is False


# ----------------------------------------------------------------- parse_custom
def dyn(phase, **kw):
    return {"type": "subagent", "phase": phase, "id": "abc", "eval_id": "ev1", "subagent_type": "redator",
            "label": "redator", "description": "escrever", **kw}


def test_parse_custom_dynamic_phases_and_replay():
    tracker, registry, _ = make()
    start = tracker.parse_custom((), dyn("start"))[0]
    assert (start.kind, start.phase, start.id, start.parent_id, start.name) == (EventKind.SUBAGENT_DYNAMIC, Phase.START, "dyn-abc", "ev1", "redator")
    assert start.visibility == Visibility.PRIMARY and start.label == "Avvio il subagent dinamico redator «escrever»…"
    end = tracker.parse_custom((), dyn("complete", duration_ms=1500))[0]
    assert end.phase == Phase.END and end.duration_s == 1.5 and end.id == "dyn-abc"
    err = tracker.parse_custom((), dyn("error", error="boom"))[0]
    assert err.phase == Phase.ERROR and err.error == "boom"
    replay = tracker.parse_custom((), dyn("start"))[0]
    assert replay.phase == Phase.START and replay.id == "dyn-abc" and replay.data["replay"] is True
    assert tracker.stats().n_dynamic_subagents == 1


def test_parse_custom_unknown_phase_and_other_payload():
    tracker, _, _ = make()
    unk = tracker.parse_custom((), dyn("boh"))[0]
    assert unk.kind == EventKind.SUBAGENT_DYNAMIC and unk.phase == Phase.INFO
    other = tracker.parse_custom((), {"progress": 3, "message": "meta"})[0]
    assert other.kind == EventKind.CUSTOM and other.data["progress"] == 3 and other.summary == "meta"
    plain = tracker.parse_custom((), "texto")[0]
    assert plain.kind == EventKind.CUSTOM and plain.data == {"value": "texto"}
    json.dumps(unk.to_dict())


def test_parse_custom_inside_subagent_ns():
    tracker, registry, _ = make()
    registry.register_subagent_ns("tools:X", tool_call_id="call-task", name="pesquisador")
    ev = tracker.parse_custom(("tools:X",), {"foo": 1})[0]
    assert ev.agent == "pesquisador" and ev.parent_id == "call-task" and ev.depth == 1


# ----------------------------------------------------------------- parse_update
def test_parse_update_interrupt():
    tracker, _, _ = make()
    evs = tracker.parse_update((), {"__interrupt__": (Interrupt(value={"action": "approve"}, id="i1"),)})
    assert len(evs) == 1 and evs[0].kind == EventKind.INTERRUPT and evs[0].id == "i1" and evs[0].visibility == Visibility.PRIMARY
    assert evs[0].data["value"] == {"action": "approve"}
    json.dumps(evs[0].to_dict())


def test_parse_update_summarization_event_and_graph_steps():
    tracker, _, _ = make()
    update = {"model": {"_summarization_event": {"cutoff_index": 4, "summary_message": HumanMessage("riassunto lungo")},
                        "messages": [AIMessage("x")]}}
    evs = tracker.parse_update((), update)
    assert [e.kind for e in evs] == [EventKind.SUMMARIZATION] and evs[0].phase == Phase.INFO
    assert evs[0].data["cutoff_index"] == 4 and evs[0].summary == "riassunto lungo"
    assert tracker.parse_update((), {"model": {"messages": []}, "tools": None}) == []
    dbg, _, _ = make(StreamOptions(emit_graph_steps=True))
    steps = dbg.parse_update((), {"model": {"messages": []}, "tools": None})
    assert [(e.kind, e.data["node"], e.visibility) for e in steps] == [(EventKind.GRAPH_STEP, "model", Visibility.DEBUG), (EventKind.GRAPH_STEP, "tools", Visibility.DEBUG)]


# ----------------------------------------------------------------- labels / summarize
def test_labels_italian():
    assert label(EventKind.TOOL, Phase.START, "internet_search", {"query": "x"}) == "Consulto lo strumento internet_search «x»…"
    assert label(EventKind.TOOL, Phase.START, "foo", {}) == "Consulto lo strumento foo…"
    assert label(EventKind.FILE, Phase.START, "read_file", data={"op": "read_file", "path": "/a"}) == "Leggo «/a»"
    assert label(EventKind.FILE, Phase.START, "edit_file", data={"op": "edit_file", "path": "/a"}) == "Modifico «/a»"
    assert label(EventKind.FILE, Phase.START, "ls", data={"op": "ls", "path": "/"}) == "Elenco «/»"
    assert label(EventKind.FILE, Phase.START, "grep", data={"op": "grep", "pattern": "x"}) == "Cerco «x»"
    assert label(EventKind.MODEL_CALL, Phase.START, "m", data={"purpose": "summary"}) == "Riassumo il contesto…"
    assert label(EventKind.MODEL_CALL, Phase.END, "m", data={"decision": {"tool_calls": [{"name": "a"}, {"name": "b"}]}}) == "Il modello decide: a, b"
    assert label(EventKind.SUBAGENT_DYNAMIC, Phase.END, "redator") == "Subagent dinamico redator completato"
    assert label("subagent", "start", "pesquisador", data={"description": "ia"}) == "Consulto il subagent pesquisador «ia»…"


@dataclass
class Dc:
    a: int
    b: tuple


class Color(Enum):
    RED = "red"


def test_to_jsonable_wide_coverage():
    class Weird:
        def __repr__(self):
            return "<Weird!>"

    class BadRepr:
        def __repr__(self):
            raise RuntimeError("x")

    uid = uuid.uuid4()
    obj = {
        "msg": AIMessage("oi", tool_calls=[{"id": "1", "name": "t", "args": {}, "type": "tool_call"}]),
        "tool": ToolMessage("r", tool_call_id="1"),
        "cmd": Command(update={"messages": [ToolMessage("r", tool_call_id="1")]}),
        "exc": ValueError("ops"), "uuid": uid, "dc": Dc(1, (1, 2)), "enum": Color.RED, "tuple": (1, 2),
        "bytes": b"abc", "set": {1}, "weird": Weird(), "bad": BadRepr(), "nan": float("nan"), 3: "chave int", "none": None,
        "event_kind": EventKind.TOOL,
    }
    out = to_jsonable(obj)
    json.dumps(out)
    assert out["msg"]["content"] == "oi" and out["msg"]["tool_calls"][0]["name"] == "t"
    assert out["cmd"]["update"]["messages"][0]["content"] == "r"
    assert out["exc"] == {"type": "ValueError", "message": "ops"} and out["uuid"] == str(uid)
    assert out["dc"] == {"a": 1, "b": [1, 2]} and out["enum"] == "red" and out["bytes"] == "abc"
    assert out["weird"] == "<Weird!>" and out["tuple"] == [1, 2] and out["3"] == "chave int" and out["event_kind"] == "tool"
    assert isinstance(out["bad"], str) and out["nan"] == "nan"


def test_to_jsonable_cycle_and_helpers():
    a: list = []
    a.append(a)
    json.dumps(to_jsonable(a))
    assert clip("a   b\nc", 100) == "a b c" and clip("x" * 10, 5) == "xxxx…"
    assert safe_repr(object(), 10).endswith("…")


def test_stream_event_to_dict_roundtrip_uses_to_jsonable():
    tracker, _, events = make()
    tool(tracker, "foo", {"a": 1}, output="x")
    d = events[0].to_dict()
    json.dumps(d)
    assert StreamEvent.from_dict(d).id == events[0].id


# ----------------------------------------------------------------- stats
def test_stats_aggregate():
    tracker, _, _ = make()
    tool(tracker, "internet_search", {"query": "a"})
    tool(tracker, "internet_search", {"query": "b"})
    tool(tracker, "foo", {}, error=RuntimeError("x"))
    llm(tracker, AIMessage("a"))
    llm(tracker, AIMessage("b"))
    tracker.parse_custom((), dyn("start"))
    stats = tracker.stats()
    assert stats.n_tools == 3 and stats.tools == {"internet_search": 2, "foo": 1} and stats.n_llm_calls == 2
    assert stats.errors == 1 and stats.n_dynamic_subagents == 1
    json.dumps(stats.to_dict())

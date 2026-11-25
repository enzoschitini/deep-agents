"""Testes offline do parser de resposta (streaming/response) com AIMessageChunk sintéticos."""

from __future__ import annotations

from langchain_core.messages import AIMessage, AIMessageChunk

from deep_agents.streaming.bus import EventBus
from deep_agents.streaming.events import EventKind, Phase, Visibility
from deep_agents.streaming.options import StreamOptions
from deep_agents.streaming.registry import RunRegistry
from deep_agents.streaming.response import ResponseAccumulator, ResponseStreamer, WordCoalescer
from deep_agents.streaming.response.tokens import extract

MID = "lc_run--abc"


def make(**opts):
    bus, reg = EventBus("r1"), RunRegistry()
    return ResponseStreamer(bus, reg, StreamOptions(**opts)), reg


def feed(rs, chunks, ns=(), md=None, mid=MID):
    out = []
    for c in chunks:
        if isinstance(c, str):
            c = AIMessageChunk(content=c, id=mid)
        out += rs.feed_message(c, md or {}, ns)
    return out


def texts(evs, kind=EventKind.RESPONSE):
    return [e.data["text"] for e in evs if e.kind == kind and e.phase == Phase.DELTA]


def test_word_granularity_coalesces_and_flushes():
    rs, _ = make()
    evs = feed(rs, ["Ci", "ao ", "mon", "do", " bel", "lo"])
    assert texts(evs) == ["Ciao ", "mondo "]
    assert [e.data["index"] for e in evs] == [0, 1]
    assert all(e.visibility == Visibility.PRIMARY and e.id == MID and e.agent == "main" for e in evs)
    tail = rs.flush()
    assert texts(tail) == ["bello"]
    assert rs.flush() == []


def test_token_granularity_passes_through():
    rs, _ = make(granularity="token")
    assert texts(feed(rs, ["Ci", "ao", " "])) == ["Ci", "ao", " "]
    assert rs.flush() == []


def test_word_coalescer_unit():
    c = WordCoalescer("word")
    assert c.push("a") == []
    assert c.push("b c\nd") == ["ab c\n"]
    assert c.flush() == "d"
    assert WordCoalescer("token").push("x") == ["x"]


def test_tool_call_chunk_without_text_ignored_and_tool_args_option():
    ch = AIMessageChunk(content="", id=MID, tool_call_chunks=[{"name": "t", "args": '{"q"', "id": "c1", "index": 0}])
    rs, _ = make()
    assert rs.feed_message(ch, {}, ()) == []
    rs, _ = make(emit_tool_args_delta=True)
    evs = rs.feed_message(ch, {}, ())
    assert len(evs) == 1 and evs[0].kind == EventKind.TOOL_ARGS
    assert evs[0].visibility == Visibility.DEBUG and evs[0].data["args_delta"] == '{"q"' and evs[0].id == "c1"


def test_reasoning_blocks_and_option():
    ch = AIMessageChunk(content=[{"type": "reasoning", "reasoning": "penso "}, {"type": "text", "text": "ok "}], id=MID)
    rs, _ = make()
    evs = rs.feed_message(ch, {}, ())
    assert texts(evs, EventKind.REASONING) == ["penso "]
    assert [e for e in evs if e.kind == EventKind.REASONING][0].visibility == Visibility.SECONDARY
    assert texts(evs) == ["ok "]
    rs, _ = make(emit_reasoning=False)
    assert texts(rs.feed_message(ch, {}, ()), EventKind.REASONING) == []


def test_anthropic_thinking_block():
    ch = AIMessageChunk(content=[{"type": "thinking", "thinking": "hmm ", "index": 0}], id=MID)
    assert extract(ch) == ("", "hmm ")


def test_list_content_blocks_text():
    ch = AIMessageChunk(content=[{"type": "text", "text": "uno due ", "index": 0}], id=MID)
    rs, _ = make()
    assert texts(rs.feed_message(ch, {}, ())) == ["uno due "]


def test_subagent_ns_discarded_or_debug():
    rs, _ = make()
    assert feed(rs, ["ciao "], ns=("tools:X",)) == []
    rs, reg = make(emit_subagent_tokens=True)
    reg.register_subagent_ns("tools:X", tool_call_id="tc1", name="pesquisador")
    evs = feed(rs, ["ciao "], ns=("tools:X",), md={"lc_agent_name": "pesquisador"}, mid="lc_run--sub")
    assert len(evs) == 1 and evs[0].visibility == Visibility.DEBUG
    assert evs[0].agent == "pesquisador" and evs[0].agent_id == "tc1" and evs[0].ns == ("tools:X",)
    assert rs.final_text() == ""
    assert rs.on_model_update(("tools:X",), AIMessage(content="x", id="lc_run--sub")) == []


def test_summary_calls_discarded():
    rs, reg = make()
    reg.llm_started("abc", purpose="summary")
    assert feed(rs, ["Resumo ", "aqui "]) == []
    assert rs.flush() == []


def test_on_model_update_final_true_flushes_first():
    rs, _ = make()
    feed(rs, ["Ciao ", "mondo"])
    evs = rs.on_model_update((), AIMessage(content="Ciao mondo", id=MID))
    assert texts(evs) == ["mondo"]
    end = evs[-1]
    assert end.kind == EventKind.RESPONSE and end.phase == Phase.END and end.visibility == Visibility.PRIMARY
    assert end.data == {"message_id": MID, "final": True, "text": "Ciao mondo"}
    assert rs.final_text() == "Ciao mondo"
    assert rs.flush() == []


def test_on_model_update_final_false_with_tool_calls():
    rs, _ = make()
    feed(rs, ["Cerco "])
    msg = AIMessage(content="Cerco ", id=MID, tool_calls=[{"name": "t", "args": {}, "id": "c1"}])
    end = rs.on_model_update((), msg)[-1]
    assert end.data["final"] is False and end.data["text"] == "Cerco "
    assert rs.final_text() == ""
    # mensagem final posterior vence
    rs.on_model_update((), AIMessage(content="Fine", id="lc_run--2"))
    assert rs.final_text() == "Fine"


def test_model_update_without_streaming_covers_limit_message():
    rs, _ = make()
    evs = rs.on_model_update((), AIMessage(content=[{"type": "text", "text": "Limite raggiunto"}], id="m9"))
    assert evs[-1].data["text"] == "Limite raggiunto" and rs.final_text() == "Limite raggiunto"


def test_accumulator():
    a = ResponseAccumulator()
    a.add("m", "ab")
    a.add("m", "c")
    assert a.text_of("m") == "abc" and a.final_text() == ""
    a.close("m", "abc!", True)
    assert a.final_text() == "abc!"

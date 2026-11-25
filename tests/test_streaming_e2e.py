"""AgentStreamer com o agente REAL (create_deep_agent + middlewares) e modelo falso com tokens. Offline."""

from __future__ import annotations

import asyncio
import threading

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from deep_agents.agent import AgentBuilder
from deep_agents.memory import build_memory
from deep_agents.memory.build_memory import MemoryBuilder
from deep_agents.model.llm_gateway import LLMGateway
from deep_agents.model.model_config import ModelConfig
from deep_agents.streaming import AgentStreamer, EventKind, Phase, Visibility
from deep_agents.streaming.adapters import ListSink
from deep_agents.toolkit.build_toolkit import ToolkitBuilder
from deep_agents.toolkit.side_channel import SideChannel
from tests.fakes import FakeTavily, internet_search, read_skill, search, tool_call, tool_round
from tests.fakes_stream import StreamingScriptedChat

ANSWER = "Resposta final com alguns fatos importantes sobre o assunto."
USER = [{"role": "user", "content": "oi"}]


def build(fake, *, tools=None, subagents=False):
    config = ModelConfig.from_spec("openai:gpt-6.1-sol")
    memory = MemoryBuilder(database="fake_vectorial")
    builder = AgentBuilder(config, memory=memory)
    builder.gateway = LLMGateway(config, model=fake)
    if subagents:
        builder.toolkit = ToolkitBuilder(groups={"tavily": FakeTavily})
    else:
        builder.build_tools = lambda: tools if tools is not None else [internet_search]
    return builder.build()


def run(streamer, messages=None, **kw):
    handle = streamer.start(messages or USER, **kw)
    return handle, list(handle)


def kinds(events, kind, phase=None):
    return [e for e in events if e.kind is kind and (phase is None or e.phase is phase)]


def test_main_with_tool_and_streamed_answer():
    fake = StreamingScriptedChat(script=[tool_round(search("a")), AIMessage(ANSWER)])
    agent, gw = build(fake)
    handle, events = run(AgentStreamer(agent, gw))

    assert events[0].kind is EventKind.RUN and events[0].phase is Phase.START
    assert events[-1].kind is EventKind.RUN and events[-1].phase is Phase.END
    seqs = [e.seq for e in events]
    assert len(set(seqs)) == len(seqs)
    deltas = kinds(events, EventKind.RESPONSE, Phase.DELTA)
    assert deltas and all(e.agent == "main" for e in deltas)
    assert "".join(e.data["text"] for e in deltas).strip() == ANSWER
    tool = kinds(events, EventKind.TOOL)
    assert [e.phase for e in tool] == [Phase.START, Phase.END] and tool[0].name == "internet_search"
    res = handle.result
    assert res.answer == ANSWER and res.error is None and not res.cancelled
    assert res.state is not None and res.report is not None and res.report.wall_time_s is not None
    assert gw.history[-1] is res.report
    assert events[-1].data["answer"] == ANSWER and events[-1].data["stats"]["n_tools"] == 1
    assert res.stats.tools == {"internet_search": 1}


def test_skill_and_file_events():
    script = [
        tool_round(read_skill(), tool_call("ls", {"path": "/prompts/skills/"})),
        AIMessage(ANSWER),
    ]
    agent, gw = build(StreamingScriptedChat(script=script))
    handle, events = run(AgentStreamer(agent, gw))

    assert kinds(events, EventKind.SKILL, Phase.START)[0].data["skill"] == "busca-na-web"
    assert kinds(events, EventKind.FILE, Phase.START)[0].visibility is Visibility.SECONDARY
    assert handle.result.stats.skills == ["busca-na-web"]


class DelegatingStream(StreamingScriptedChat):
    """Decide pela situação (principal e subagents compartilham o modelo e rodam em paralelo)."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        system = str(messages[0].content) if messages and messages[0].type == "system" else ""
        is_researcher = "Você é um pesquisador" in system
        done = any(m.type == "tool" for m in messages)
        if is_researcher and not done:
            reply = tool_round(search("angulo"))
        elif is_researcher:
            reply = AIMessage("achado do subagent sobre o tema")
        elif not done:
            reply = tool_round(tool_call("task", {"description": "Ângulo A", "subagent_type": "pesquisador"}))
        else:
            reply = AIMessage(ANSWER)
        return ChatResult(generations=[ChatGeneration(message=reply)])


def test_subagent_events_and_tokens_stay_out_of_response():
    agent, gw = build(DelegatingStream(), subagents=True)
    handle, events = run(AgentStreamer(agent, gw))

    sub = kinds(events, EventKind.SUBAGENT, Phase.START)
    assert len(sub) == 1 and sub[0].name == "pesquisador" and sub[0].agent == "main"
    children = [e for e in kinds(events, EventKind.TOOL, Phase.START) if e.name == "internet_search"]
    assert len(children) == 1
    assert children[0].parent_id == sub[0].id and children[0].agent == "pesquisador" and children[0].depth >= 1
    assert kinds(events, EventKind.SUBAGENT, Phase.END)
    visible = [e for e in kinds(events, EventKind.RESPONSE, Phase.DELTA) if e.visibility is not Visibility.DEBUG]
    assert all(e.agent == "main" for e in visible)
    assert "subagent sobre" not in "".join(e.data["text"] for e in visible)
    assert handle.result.answer == ANSWER
    assert handle.result.stats.n_subagents == 1


def test_summary_tokens_do_not_leak(monkeypatch):
    monkeypatch.setattr(build_memory, "SUMMARY_TRIGGER_TOKENS", 200)
    fake = StreamingScriptedChat(script=[AIMessage(ANSWER)])
    agent, gw = build(fake)
    big = [{"role": "user", "content": "contexto " * 400}, {"role": "assistant", "content": "ok " * 400},
           {"role": "user", "content": "e agora?"}]
    handle, events = run(AgentStreamer(agent, gw), big)

    assert fake.calls("summary"), "o resumo deveria ter rodado"
    text = "".join(e.data["text"] for e in kinds(events, EventKind.RESPONSE, Phase.DELTA))
    assert "resumo curto" not in text
    assert handle.result.answer == ANSWER


class Boom(StreamingScriptedChat):
    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("falha do provedor")
        yield  # noqa: unreachable


def test_error_never_raises_in_iterator():
    agent, gw = build(Boom())
    handle, events = run(AgentStreamer(agent, gw))

    assert events[-1].kind is EventKind.RUN and events[-1].phase is Phase.ERROR
    assert "falha do provedor" in events[-1].error and events[-1].visibility is Visibility.PRIMARY
    assert isinstance(handle.result.error, RuntimeError)
    assert gw.history, "o relatório entra no histórico mesmo com erro"


class Slow(StreamingScriptedChat):
    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        for i in range(200):
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=f"p{i} "))
            if run_manager:
                run_manager.on_llm_new_token(f"p{i} ", chunk=chunk)
            yield chunk
            threading.Event().wait(0.02)


def test_cancel_emits_cancelled_and_closes():
    agent, gw = build(Slow())
    handle = AgentStreamer(agent, gw).start(USER)
    events = []
    for ev in handle:
        events.append(ev)
        if ev.kind is EventKind.RESPONSE and ev.phase is Phase.DELTA:
            handle.cancel()
    assert events[-1].kind is EventKind.RUN and events[-1].phase is Phase.CANCELLED
    assert handle.result.cancelled
    handle.join(10)
    assert handle.done
    assert gw.history


def test_sources_dedup_from_channel():
    channel = SideChannel()
    a = {"url": "https://a", "title": "A", "domain": "a"}
    b = {"url": "https://b", "title": "B", "domain": "b"}

    def internet_search_pub(query: str) -> str:
        """Busca falsa que publica fontes."""
        channel.publish("tavily", "internet_search", "sources", [a])
        channel.publish("tavily", "internet_search", "sources", [a, b])
        return "ok"

    internet_search_pub.__name__ = "internet_search"
    fake = StreamingScriptedChat(script=[tool_round(search("a")), AIMessage(ANSWER)])
    agent, gw = build(fake, tools=[internet_search_pub])
    handle, events = run(AgentStreamer(agent, gw, channel=channel))

    src = kinds(events, EventKind.SOURCES)
    assert len(src) == 1 and [s["url"] for s in src[0].data["sources"]] == ["https://a", "https://b"]
    assert events[-1].data["sources"] == handle.result.sources and len(handle.result.sources) == 2


def test_sinks_stream_and_astream():
    fake = StreamingScriptedChat(script=[AIMessage(ANSWER)] * 3)
    agent, gw = build(fake)
    sink = ListSink()
    streamer = AgentStreamer(agent, gw, sinks=[sink])

    evs = list(streamer.stream(USER))
    assert [e.seq for e in sink.events] == [e.seq for e in evs]

    async def collect():
        return [e async for e in streamer.astream(USER)]

    aevs = asyncio.run(collect())
    assert aevs[-1].phase is Phase.END and aevs[-1].data["answer"] == ANSWER

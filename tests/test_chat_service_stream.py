"""ChatService com o AgentStreamer substituído por um double que entrega uma sequência fabricada de StreamEvents."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from deep_agents.bootstrap import STREAMING
from deep_agents.server import chat_service
from deep_agents.server.chat_service import ChatService
from deep_agents.streaming.events import EventKind, Phase, StreamEvent, Visibility


def ev(kind, phase, seq=0, *, id="x", visibility=Visibility.PRIMARY, **kw) -> StreamEvent:
    return StreamEvent(seq=seq, ts=0.0, run_id="r1", id=id, kind=kind, phase=phase, visibility=visibility, **kw)


class FakeMemory:
    def __init__(self, fail_record=False):
        self.recorded, self.fail_record = [], fail_record

    def history(self):
        return []

    def record_turn(self, q, a):
        if self.fail_record:
            raise OSError("disco cheio")
        self.recorded.append((q, a))


def make_backend(memory=None):
    return SimpleNamespace(agent="AGENT", gateway=SimpleNamespace(config=SimpleNamespace(spec="fake:m")),
                           memory=memory or FakeMemory(), toolkit=SimpleNamespace(channel="CHANNEL"), tracer=None)


class _Handle:
    def __init__(self, it, result):
        self._it, self.result = it, result

    def __iter__(self):
        return self._it()


@pytest.fixture
def install(monkeypatch):
    """Instala o double do AgentStreamer; devolve `seen` (argumentos recebidos) e a função de configuração."""
    seen = {}
    monkeypatch.setattr(chat_service, "manage_result_json", lambda state: None)
    monkeypatch.setattr(chat_service, "format_metrics", lambda report, stats=None: f"metrics({report},{stats})")

    def setup(events, *, answer="risposta finale", error=None, gate=None):
        result = SimpleNamespace(state={"messages": []}, answer=answer, report="REPORT", stats="STATS",
                                 error=error, cancelled=False, sources=[{"url": "u", "title": "t", "domain": "d"}])

        class FakeStreamer:
            def __init__(self, agent, gateway=None, *, options=None, channel=None, sinks=(), tracer=None, origin=None):
                seen.update(agent=agent, gateway=gateway, options=options, channel=channel, tracer=tracer, origin=origin)

            def start(self, messages, **kw):
                seen["messages"] = list(messages)

                def it():
                    if gate:
                        gate.wait(5)
                    yield from events
                return _Handle(it, result)

        monkeypatch.setattr(chat_service, "AgentStreamer", FakeStreamer)
        return result

    return seen, setup


def run(service, text="ciao", **kw):
    it = service.send(text, **kw)
    assert it is not None
    return list(it)


HAPPY = [
    ev(EventKind.RUN, Phase.START, 0),
    ev(EventKind.TOOL, Phase.START, 1, id="t1", name="internet_search", label="Consulto lo strumento"),
    ev(EventKind.FILE, Phase.START, 2, id="f1", visibility=Visibility.SECONDARY),
    ev(EventKind.GRAPH_STEP, Phase.INFO, 3, id="g1", visibility=Visibility.DEBUG),
    ev(EventKind.TOOL, Phase.END, 4, id="t1", name="internet_search", duration_s=1.0),
    ev(EventKind.RESPONSE, Phase.DELTA, 5, id="m1", data={"text": "risposta "}),
    ev(EventKind.RESPONSE, Phase.DELTA, 6, id="m1", data={"text": "finale"}),
    ev(EventKind.RESPONSE, Phase.END, 7, id="m1", data={"final": True, "text": "risposta finale", "message_id": "m1"}),
    ev(EventKind.RUN, Phase.END, 8, id="r1", data={"answer": "provvisoria", "stats": {}}),
]


def test_happy_path_forwards_events_and_enriches_run_end(install):
    seen, setup = install
    setup(HAPPY)
    backend = make_backend()
    service = ChatService(backend)
    events = run(service)

    kinds = [(e["kind"], e["phase"]) for e in events]
    assert ("run", "start") not in kinds
    assert kinds[:2] == [("tool", "start"), ("file", "start")]      # PRIMARY e SECONDARY passam
    assert ("graph_step", "info") not in kinds                      # DEBUG fica de fora por padrão
    assert kinds[-1] == ("run", "end")                              # o fim sai por último
    assert all("type" not in e for e in events)                     # sem o formato antigo (step/answer)
    end = events[-1]["data"]
    assert end["answer"] == "risposta finale"                       # res.answer é a verdade, não o provisório
    assert end["sources"] == [{"url": "u", "title": "t", "domain": "d"}]
    assert end["metrics"] == "metrics(REPORT,STATS)"
    assert seen["options"] is STREAMING and seen["channel"] == "CHANNEL" and seen["agent"] == "AGENT"
    assert seen["messages"] == [{"role": "user", "content": "ciao"}]
    assert service.messages == [{"role": "user", "content": "ciao"}, {"role": "assistant", "content": "risposta finale"}]
    assert backend.memory.recorded == [("ciao", "risposta finale")]
    assert service._busy.acquire(blocking=False)   # liberado ao fim


def test_debug_flag_includes_debug_events(install):
    _, setup = install
    setup(HAPPY)
    events = run(ChatService(make_backend()), debug=True)
    assert ("graph_step", "info") in [(e["kind"], e["phase"]) for e in events]


def test_events_are_json_safe(install):
    _, setup = install
    setup(HAPPY)
    json.dumps(run(ChatService(make_backend())))


def test_run_error_becomes_error_event_and_history_is_rolled_back(install):
    _, setup = install
    setup([ev(EventKind.RUN, Phase.START), ev(EventKind.RUN, Phase.ERROR, 1, error="boom")], error=ValueError("boom"))
    backend = make_backend()
    service = ChatService(backend)
    events = run(service)
    assert events[-1]["kind"] == "run" and events[-1]["phase"] == "error"
    assert events[-1]["error"] == "ValueError: boom"
    assert not any(e["phase"] == "end" for e in events)
    assert service.messages == [] and backend.memory.recorded == []
    assert service._busy.acquire(blocking=False)


def test_empty_answer_is_an_error(install):
    _, setup = install
    setup(HAPPY, answer="  ")
    service = ChatService(make_backend())
    events = run(service)
    assert events[-1]["phase"] == "error" and "nessuna risposta" in events[-1]["error"]
    assert service.messages == []


def test_record_failure_is_a_notice_before_run_end(install):
    _, setup = install
    setup(HAPPY)
    service = ChatService(make_backend(FakeMemory(fail_record=True)))
    events = run(service)
    assert events[-1]["kind"] == "run" and events[-1]["phase"] == "end"
    notices = [e for e in events if e["kind"] == "notice"]
    assert len(notices) == 1 and "salvataggio non riuscito" in notices[0]["data"]["message"]
    assert events.index(notices[0]) < len(events) - 1
    assert len(service.messages) == 2   # a resposta continua valendo


def test_one_turn_at_a_time(install):
    _, setup = install
    gate = threading.Event()
    setup(HAPPY, gate=gate)
    service = ChatService(make_backend())
    first = service.send("um")
    assert first is not None
    assert service.send("dois") is None          # ocupado
    gate.set()
    list(first)
    assert service.send("tre") is not None       # liberado


def test_missing_run_end_is_synthesized(install):
    _, setup = install
    setup([ev(EventKind.RUN, Phase.START)])
    events = run(ChatService(make_backend()))
    assert events[-1]["kind"] == "run" and events[-1]["phase"] == "end"
    assert events[-1]["data"]["answer"] == "risposta finale"

import threading

import pytest

from deep_agents.toolkit.build_toolkit import ToolkitBuilder
from deep_agents.toolkit.side_channel import SideChannel
from deep_agents.toolkit.tools.tavily import TavilyTools


class FakeTavily:
    def __init__(self, results=None, error=None):
        self.results, self.error = results or [], error

    def search(self, query, **kwargs):
        if self.error:
            raise self.error
        return {"results": self.results}


RESULTS = [
    {"title": "A", "url": "https://www.a.com/x", "content": "texto a"},
    {"title": "B", "url": "https://b.org/y", "content": "texto b"},
]


# ------------------------------------------------------------------ SideChannel
def test_publish_and_query_filters():
    session = {"id": "s1"}
    ch = SideChannel(lambda: session["id"])
    ch.begin_turn()
    ch.publish("tavily", "internet_search", "sources", [1])
    session["id"] = "s2"
    ch.begin_turn()
    ch.publish("tavily", "internet_search", "sources", [2])
    ch.publish("table", "read", "rows", [3])

    assert len(ch.query()) == 3
    assert [p.payload for p in ch.query(session_id="s1")] == [[1]]
    assert [p.payload for p in ch.query(turn=2, toolkit="tavily")] == [[2]]
    assert [p.payload for p in ch.query(kind="rows")] == [[3]]


def test_subscribe_receives_publication():
    ch, seen = SideChannel(), []
    ch.subscribe(seen.append)
    pub = ch.publish("t", "x", "k", {"a": 1})
    assert seen == [pub]


def test_publish_is_thread_safe():
    ch = SideChannel()
    threads = [threading.Thread(target=lambda: [ch.publish("t", "x", "k", 0) for _ in range(100)]) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(ch.query()) == 800
    assert len({p.id for p in ch.query()}) == 800


# ------------------------------------------------------------------ TavilyTools
def test_internet_search_returns_text_and_publishes_sources():
    ch = SideChannel()
    ch.begin_turn()
    out = TavilyTools(ch, client=FakeTavily(RESULTS)).internet_search("q")

    assert "[1] A" in out and "https://b.org/y" in out and "texto b" in out
    (pub,) = ch.query(toolkit="tavily", tool="internet_search", kind="sources")
    assert pub.payload == [
        {"domain": "www.a.com", "title": "A", "url": "https://www.a.com/x"},
        {"domain": "b.org", "title": "B", "url": "https://b.org/y"},
    ]


def test_internet_search_error_goes_to_model_and_publishes_nothing():
    ch = SideChannel()
    out = TavilyTools(ch, client=FakeTavily(error=RuntimeError("boom"))).internet_search("q")
    assert "boom" in out
    assert ch.query() == []


def test_internet_search_without_results():
    ch = SideChannel()
    assert TavilyTools(ch, client=FakeTavily([])).internet_search("q") == "Nenhum resultado encontrado."


# ------------------------------------------------------------------ ToolkitBuilder
def test_builder_enabled_and_disabled():
    on = ToolkitBuilder({"tavily": {"enabled": True}}).build()
    off = ToolkitBuilder({"tavily": {"enabled": False}}).build()
    assert [t.__name__ for t in on] == ["internet_search"]
    assert off == []


def test_builder_tool_selection():
    assert ToolkitBuilder({"tavily": {"tools": []}}).build() == []
    assert len(ToolkitBuilder({"tavily": {"tools": ["internet_search"]}}).build()) == 1


def test_builder_rejects_unknown_names():
    with pytest.raises(ValueError, match="Grupo"):
        ToolkitBuilder({"nope": {"enabled": True}}).build()
    with pytest.raises(ValueError, match="Tools desconhecidas"):
        ToolkitBuilder({"tavily": {"tools": ["nope"]}}).build()


def test_builder_tools_publish_to_builder_channel():
    ch = SideChannel()
    builder = ToolkitBuilder({"tavily": {}}, channel=ch)
    assert builder.channel is ch
    assert builder.build()[0].__self__.channel is ch


# ------------------------------------------------------------------ feedback na CLI
from types import SimpleNamespace  # noqa: E402

from rich.console import Console  # noqa: E402

from deep_agents.cli.renderer import Renderer, tools_used  # noqa: E402


def _report(*runs):
    return SimpleNamespace(tool_runs=list(runs))


def test_tools_used_filters_to_toolkit_and_summarizes_query():
    report = _report(
        {"name": "read_file", "input": "{'file_path': '/x'}", "duration_s": 0.0, "error": None},
        {"name": "internet_search", "input": "{'query': 'deep agents', 'max_results': 3}", "duration_s": 1.2, "error": None},
        {"name": "internet_search", "input": "{'query': 'truncada", "duration_s": 0.5, "error": "Boom"},
    )
    runs = tools_used(report, {"internet_search"})
    assert [r["summary"] for r in runs] == ["«deep agents»", ""]
    assert runs[1]["error"] == "Boom"


def test_renderer_draws_tools_and_sources_deduplicated():
    ch = SideChannel()
    turn = ch.begin_turn()
    TavilyTools(ch, client=FakeTavily(RESULTS)).internet_search("q")
    TavilyTools(ch, client=FakeTavily(RESULTS[:1])).internet_search("q2")  # URL repetida
    console = Console(record=True, width=100)
    view = Renderer(console, "agent")
    view.tools(tools_used(_report({"name": "internet_search", "input": "{'query': 'q'}", "duration_s": 1.0, "error": None}), {"internet_search"}))
    view.sources(ch.query(turn=turn, kind="sources"))
    out = console.export_text()
    assert "strumento in uso: internet_search" in out and "«q»" in out
    assert "Fonti (2)" in out and "b.org" in out and out.count("https://www.a.com/x") == 1


def test_renderer_draws_nothing_without_tools_or_sources():
    console = Console(record=True)
    view = Renderer(console, "agent")
    view.tools([])
    view.sources([])
    assert console.export_text() == ""

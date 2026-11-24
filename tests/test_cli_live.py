"""LiveTurn: desenho de um turno a partir de uma sequência FABRICADA de StreamEvent (sem agente nem rede)."""

from __future__ import annotations

from types import SimpleNamespace

from rich.console import Console

from deep_agents.cli.renderer import Renderer, format_metrics
from deep_agents.streaming.events import EventKind, Phase, RunStats, StreamEvent, Visibility


class Seq:
    """Fábrica de eventos com seq crescente."""

    def __init__(self) -> None:
        self.n = 0

    def ev(self, kind: EventKind, phase: Phase, id: str = "x", **kw) -> StreamEvent:
        self.n += 1
        kw.setdefault("visibility", Visibility.PRIMARY)
        return StreamEvent(seq=self.n, ts=0.0, run_id="r", id=id, kind=kind, phase=phase, **kw)


def make_view() -> tuple[Renderer, Console]:
    console = Console(record=True, width=100, force_terminal=False)
    return Renderer(console, "agente"), console


def play(events: list[StreamEvent], verbosity: str = "off"):
    view, console = make_view()
    with view.live_turn(verbosity) as live:
        for ev in events:
            live.handle(ev)
    return live, console.export_text()


def scenario(s: Seq, *, final_text: str = "Ecco la risposta finale.", sources: bool = True) -> list[StreamEvent]:
    E, P = EventKind, Phase
    events = [
        s.ev(E.RUN, P.START, "r"),
        s.ev(E.TOOL, P.START, "t1", name="internet_search", args={"query": "ia news"}, label="Consulto lo strumento internet_search…"),
        s.ev(E.TOOL, P.END, "t1", name="internet_search", args={"query": "ia news"}, duration_s=1.2),
        s.ev(E.SUBAGENT, P.START, "task1", name="pesquisador", args={"description": "cercare notizie"}, label="Consulto il subagent pesquisador…"),
        s.ev(E.TOOL, P.START, "t2", name="internet_search", args={"query": "angolo uno"}, parent_id="task1", agent="pesquisador", depth=1),
        s.ev(E.TOOL, P.END, "t2", name="internet_search", args={"query": "angolo uno"}, parent_id="task1", agent="pesquisador", depth=1, duration_s=0.8),
        s.ev(E.SUBAGENT, P.END, "task1", name="pesquisador", duration_s=2.5),
        s.ev(E.SKILL, P.END, "sk", name="read_file", data={"skill": "busca-na-web"}),
        # texto intermediário (pensiero) antes da chamada final
        s.ev(E.RESPONSE, P.DELTA, "m1", data={"text": "Vediamo "}),
        s.ev(E.RESPONSE, P.DELTA, "m1", data={"text": "i risultati."}),
        s.ev(E.RESPONSE, P.END, "m1", data={"final": False, "text": "Vediamo i risultati.", "message_id": "m1"}),
    ]
    for i, word in enumerate(final_text.split(" ")):
        events.append(s.ev(E.RESPONSE, P.DELTA, "m2", data={"text": word + " ", "index": i}))
    events.append(s.ev(E.RESPONSE, P.END, "m2", data={"final": True, "text": final_text, "message_id": "m2"}))
    if sources:
        events.append(s.ev(E.SOURCES, P.INFO, "src", data={"sources": [
            {"domain": "example.com", "title": "Esempio", "url": "https://example.com/a"},
        ]}))
    events.append(s.ev(E.RUN, P.END, "r", data={"answer": final_text, "metrics": "[token in: 1 | out: 2]"}))
    return events


def test_full_turn_output():
    live, out = play(scenario(Seq()))
    assert "strumento in uso: internet_search" in out and "«ia news»" in out and "(1.2s)" in out
    assert "subagent: pesquisador" in out and "«cercare notizie»" in out
    assert "skill in uso: busca-na-web" in out
    assert "Vediamo i risultati." in out            # texto intermediário
    assert "Fonti" in out and "example.com" in out
    assert "[token in: 1 | out: 2]" in out and live.metrics_printed


def test_answer_is_not_printed_twice():
    _, out = play(scenario(Seq()))
    assert out.count("Ecco la risposta finale.") == 1


def test_nested_tool_is_indented_under_subagent():
    _, out = play(scenario(Seq()))
    lines = out.splitlines()
    top = next(l for l in lines if "internet_search" in l and "ia news" in l)
    nested = next(l for l in lines if "angolo uno" in l)
    assert len(nested) - len(nested.lstrip()) > len(top) - len(top.lstrip())


def test_secondary_hidden_unless_on():
    s = Seq()
    file_ev = s.ev(EventKind.FILE, Phase.END, "f", name="read_file", label="Leggo /workspace/a.md", visibility=Visibility.SECONDARY)
    _, off = play([file_ev])
    _, on = play([file_ev], "on")
    assert "Leggo /workspace/a.md" not in off
    assert "Leggo /workspace/a.md" in on


def test_dynamic_subagent_lines():
    s = Seq()
    E, P = EventKind, Phase
    _, out = play([
        s.ev(E.SUBAGENT_DYNAMIC, P.START, "dyn-1", name="redator", args={"description": "scrivere post"}, parent_id="ev"),
        s.ev(E.SUBAGENT_DYNAMIC, P.END, "dyn-1", name="redator", duration_s=3.0, parent_id="ev"),
        s.ev(E.SUBAGENT_DYNAMIC, P.START, "dyn-2", name="redator"),
        s.ev(E.SUBAGENT_DYNAMIC, P.ERROR, "dyn-2", name="redator", error="boom", visibility=Visibility.PRIMARY),
    ])
    assert "subagent dinamico: redator" in out
    assert "subagent dinamico completato: redator" in out and "(3.0s)" in out
    assert "subagent dinamico in errore: redator" in out and "boom" in out


def test_answer_without_deltas_is_printed_once():
    s = Seq()
    _, out = play([s.ev(EventKind.RUN, Phase.START, "r"), s.ev(EventKind.RUN, Phase.END, "r", data={"answer": "Solo testo."})])
    assert out.count("Solo testo.") == 1


def test_run_error_draws_nothing_and_closes():
    s = Seq()
    live, out = play([
        s.ev(EventKind.RUN, Phase.START, "r"),
        s.ev(EventKind.RESPONSE, Phase.DELTA, "m", data={"text": "parziale"}),
        s.ev(EventKind.RUN, Phase.ERROR, "r", error="kaput"),
    ])
    assert "kaput" not in out and live._live is None and live._status is None


def test_exit_closes_live_on_interrupt():
    view, _ = make_view()
    s = Seq()
    try:
        with view.live_turn() as live:
            live.handle(s.ev(EventKind.RESPONSE, Phase.DELTA, "m", data={"text": "ciao"}))
            raise KeyboardInterrupt
    except KeyboardInterrupt:
        pass
    assert live._live is None


def test_format_metrics_backward_compatible_and_with_stats():
    report = SimpleNamespace(
        input_tokens=10, output_tokens=5, wall_time_s=1.5, n_calls=2, reasoning_tokens=0, cache_read_tokens=0,
        tool_runs=[{"name": "task"}, {"name": "internet_search"}], cost_usd=None, n_errors=0,
    )
    old = format_metrics(report)
    assert "strumenti: 2" in old and "subagent: 1" in old
    new = format_metrics(report, RunStats(n_tools=3, n_subagents=1, n_dynamic_subagents=2))
    assert "strumenti: 3" in new and "subagent: 3" in new
    assert "strumenti: 3" in format_metrics(report, {"n_tools": 3})

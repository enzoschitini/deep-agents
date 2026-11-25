import json

from deep_agents.streaming import EventKind, Phase, RunStats, StreamEvent, Visibility
from deep_agents.streaming.adapters import CallbackSink, JsonlSink, ListSink, encode_sse, filtered, visibility_filter


def make(**kw) -> StreamEvent:
    base = dict(seq=1, ts=1.0, run_id="r", id="i", kind=EventKind.TOOL, phase=Phase.START)
    base.update(kw)
    return StreamEvent(**base)


def test_roundtrip_json():
    ev = make(ns=("tools:a", "tools:b"), depth=2, args={"q": "x"}, data={"n": (1, 2)}, visibility=Visibility.PRIMARY,
              kind=EventKind.SUBAGENT_DYNAMIC, phase=Phase.CANCELLED)
    d = json.loads(json.dumps(ev.to_dict()))
    back = StreamEvent.from_dict(d)
    assert back.kind is EventKind.SUBAGENT_DYNAMIC and back.phase is Phase.CANCELLED
    assert back.ns == ("tools:a", "tools:b") and back.visibility is Visibility.PRIMARY
    assert back.data == {"n": [1, 2]}


def test_raw_only_on_request():
    ev = make(raw={"x": object()})
    assert "raw" not in ev.to_dict()
    assert "raw" in ev.to_dict(include_raw=True)
    json.dumps(ev.to_dict(include_raw=True))


def test_visibility_order():
    P, S, D = Visibility.PRIMARY, Visibility.SECONDARY, Visibility.DEBUG
    assert P <= S <= D and P < S < D and D > S > P and D >= D


def test_stats_dict():
    assert RunStats(n_tools=2).to_dict()["n_tools"] == 2


def test_sinks_and_sse(tmp_path):
    evs = [make(visibility=v) for v in Visibility]
    lst, got = ListSink(), []
    for sink in (lst, filtered("secondary", CallbackSink(got.append))):
        for e in evs:
            sink(e)
    assert len(lst) == 3 and len(got) == 2
    assert [e.visibility for e in got] == [Visibility.PRIMARY, Visibility.SECONDARY]
    assert visibility_filter("primary")(evs[0]) and not visibility_filter("primary")(evs[2])
    with JsonlSink(tmp_path / "o.jsonl", level="secondary") as js:
        for e in evs:
            js(e)
    assert len((tmp_path / "o.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    frame = encode_sse(make(label="città"))
    assert frame.startswith(b"data: ") and frame.endswith(b"\n\n")
    assert json.loads(frame[6:].decode())["label"] == "città"

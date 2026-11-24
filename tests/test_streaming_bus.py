import threading

from deep_agents.streaming.bus import EventBus
from deep_agents.streaming.events import EventKind, Phase


def test_concurrent_emit_unique_monotonic_seq():
    bus = EventBus("r")
    seen = []
    bus.add_sink(lambda ev: seen.append(ev.seq))

    def work():
        for _ in range(50):
            bus.emit(bus.make(EventKind.NOTICE, Phase.INFO, id="x"))

    ts = [threading.Thread(target=work) for _ in range(20)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    bus.close()
    seqs = [e.seq for e in bus]
    assert seqs == list(range(1, 1001))          # a fila preserva a ordem de numeração
    assert sorted(seen) == seqs


def test_failing_sink_does_not_break():
    bus = EventBus("r")
    good = []

    def bad(ev):
        raise RuntimeError("boom")

    bus.add_sink(bad)
    bus.add_sink(good.append)
    bus.emit(bus.make(EventKind.NOTICE, Phase.INFO, id="x"))
    bus.close()
    assert len(good) == 1 and len(list(bus)) == 1


def test_close_unblocks_and_ignores_later_emits():
    bus = EventBus("r")
    out = []
    t = threading.Thread(target=lambda: out.extend(bus))
    t.start()
    bus.close()
    t.join(2)
    assert not t.is_alive()
    bus.emit(bus.make(EventKind.NOTICE, Phase.INFO, id="x"))
    assert out == []

"""EventBus: numera (seq), enfileira e distribui os eventos de um run. Thread-safe."""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable, Iterable, Iterator

from deep_agents.streaming.events import EventKind, Phase, StreamEvent, Visibility, now

_END = object()


class EventBus:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._lock = threading.Lock()
        self._seq = 0
        self._queue: queue.Queue[Any] = queue.Queue()
        self._sinks: list[Callable[[StreamEvent], None]] = []
        self._closed = False

    def make(self, kind: EventKind, phase: Phase, *, id: str, ns: tuple[str, ...] = (), **fields: Any) -> StreamEvent:
        """Só cria o evento (seq=0 até o `emit`); preenche ts, run_id e depth."""
        fields.setdefault("visibility", Visibility.SECONDARY)
        return StreamEvent(seq=0, ts=now(), run_id=self.run_id, id=id, kind=kind, phase=phase, ns=tuple(ns), depth=len(ns), **fields)

    def emit(self, ev: StreamEvent) -> StreamEvent:
        with self._lock:
            if self._closed:
                return ev
            self._seq += 1
            ev.seq = self._seq
            sinks = list(self._sinks)
            self._queue.put(ev)
        for sink in sinks:                # fora do lock; um sink que falha nunca derruba a resposta
            try:
                sink(ev)
            except Exception:
                pass
        return ev

    def emit_many(self, events: Iterable[StreamEvent]) -> None:
        for ev in events:
            self.emit(ev)

    def add_sink(self, sink: Callable[[StreamEvent], None]) -> None:
        with self._lock:
            self._sinks.append(sink)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._queue.put(_END)

    def __iter__(self) -> Iterator[StreamEvent]:
        while True:
            item = self._queue.get()
            if item is _END:
                return
            yield item

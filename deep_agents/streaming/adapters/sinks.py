"""Sinks: callables `sink(event)` que o `EventBus` chama a cada evento (falhas deles são engolidas pelo bus)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable

from deep_agents.streaming.events import StreamEvent, Visibility

Sink = Callable[[StreamEvent], None]


def _as_visibility(level: Visibility | str) -> Visibility:
    return level if isinstance(level, Visibility) else Visibility(str(level).lower())


def visibility_filter(level: Visibility | str) -> Callable[[StreamEvent], bool]:
    """Predicado `ev -> bool`: True se o evento é visível no nível dado (PRIMARY < SECONDARY < DEBUG)."""
    limit = _as_visibility(level)
    return lambda ev: ev.visibility <= limit


def filtered(level: Visibility | str, sink: Sink) -> Sink:
    """Envolve um sink para que ele só receba eventos visíveis até `level`."""
    accepts = visibility_filter(level)

    def wrapper(ev: StreamEvent) -> None:
        if accepts(ev):
            sink(ev)

    return wrapper


class ListSink:
    """Acumula os eventos numa lista (testes, inspeção)."""

    def __init__(self) -> None:
        self.events: list[StreamEvent] = []
        self._lock = threading.Lock()

    def __call__(self, ev: StreamEvent) -> None:
        with self._lock:
            self.events.append(ev)

    def __iter__(self):
        with self._lock:
            return iter(list(self.events))

    def __len__(self) -> int:
        return len(self.events)


class CallbackSink:
    """Entrega cada evento a uma função do usuário, opcionalmente só até um nível de visibilidade."""

    def __init__(self, callback: Sink, *, level: Visibility | str = Visibility.DEBUG) -> None:
        self._callback = callback
        self._accepts = visibility_filter(level)

    def __call__(self, ev: StreamEvent) -> None:
        if self._accepts(ev):
            self._callback(ev)


class JsonlSink:
    """Grava um evento por linha (JSON UTF-8) num arquivo; `close()` ao fim (ou use como context manager)."""

    def __init__(self, path: str | Path, *, level: Visibility | str = Visibility.DEBUG, include_raw: bool = False) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.path, "w", encoding="utf-8")
        self._accepts = visibility_filter(level)
        self._include_raw = include_raw
        self._lock = threading.Lock()

    def __call__(self, ev: StreamEvent) -> None:
        if not self._accepts(ev):
            return
        line = json.dumps(ev.to_dict(include_raw=self._include_raw), ensure_ascii=False, default=str)
        with self._lock:
            if not self._file.closed:
                self._file.write(line + "\n")
                self._file.flush()

    def close(self) -> None:
        with self._lock:
            if not self._file.closed:
                self._file.close()

    def __enter__(self) -> "JsonlSink":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

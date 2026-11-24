"""Ações do agente (LLM, tools, subagents, skills, arquivos, todos…) como StreamEvents. Implementa `ActionParser`."""

from __future__ import annotations

from typing import Any

from deep_agents.streaming.actions.callbacks import ActionCallbackHandler, ActionStats
from deep_agents.streaming.actions.stream_parser import StreamParser
from deep_agents.streaming.bus import EventBus
from deep_agents.streaming.events import RunStats, StreamEvent
from deep_agents.streaming.options import StreamOptions
from deep_agents.streaming.registry import RunRegistry


class ActionTracker:
    """`handler` (callback do LangChain) emite direto no bus; `parse_update`/`parse_custom` devolvem eventos."""

    def __init__(self, bus: EventBus, registry: RunRegistry, options: StreamOptions | None = None) -> None:
        options = options or StreamOptions()
        self._stats = ActionStats()
        self.handler = ActionCallbackHandler(bus, registry, options, self._stats)
        self._parser = StreamParser(bus, registry, options, self._stats)

    def parse_update(self, ns: tuple[str, ...], data: dict) -> list[StreamEvent]:
        return self._parser.parse_update(ns, data)

    def parse_custom(self, ns: tuple[str, ...], data: Any) -> list[StreamEvent]:
        return self._parser.parse_custom(ns, data)

    def stats(self) -> RunStats:
        return self._stats.snapshot()


__all__ = ["ActionTracker", "ActionCallbackHandler"]

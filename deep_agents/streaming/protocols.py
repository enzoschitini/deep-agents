"""Contratos entre o streamer (núcleo) e os dois parsers (response/ e actions/)."""

from __future__ import annotations

from typing import Any, Protocol

from langchain_core.callbacks import BaseCallbackHandler

from deep_agents.streaming.events import RunStats, StreamEvent


class ResponseParser(Protocol):
    """Implementado por `streaming.response.ResponseStreamer(bus, registry, options)`."""

    def feed_message(self, chunk: Any, metadata: dict, ns: tuple[str, ...]) -> list[StreamEvent]: ...
    def on_model_update(self, ns: tuple[str, ...], ai_message: Any) -> list[StreamEvent]: ...   # fecha a mensagem; data.final = not tool_calls
    def flush(self) -> list[StreamEvent]: ...
    def final_text(self) -> str: ...


class ActionParser(Protocol):
    """Implementado por `streaming.actions.ActionTracker(bus, registry, options)`.

    `handler` (ActionCallbackHandler) emite direto no bus; `parse_update`/`parse_custom` devolvem eventos."""

    handler: BaseCallbackHandler

    def parse_update(self, ns: tuple[str, ...], data: dict) -> list[StreamEvent]: ...
    def parse_custom(self, ns: tuple[str, ...], data: Any) -> list[StreamEvent]: ...
    def stats(self) -> RunStats: ...

"""Streaming do agente: um fluxo único de `StreamEvent` (resposta em palavras + ações) para CLI, servidor e testes.

    handle = AgentStreamer(agent, gateway, options=StreamOptions()).start(messages)
    for ev in handle: ...
    res = handle.result   # RunResult
"""

from deep_agents.streaming.bus import EventBus
from deep_agents.streaming.events import EventKind, Phase, RunStats, StreamEvent, Visibility
from deep_agents.streaming.options import StreamOptions
from deep_agents.streaming.streamer import AgentStreamer, RunHandle, RunResult

__all__ = [
    "AgentStreamer", "EventBus", "EventKind", "Phase", "RunHandle", "RunResult", "RunStats",
    "StreamEvent", "StreamOptions", "Visibility",
]

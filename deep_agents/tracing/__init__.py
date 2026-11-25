"""Rastreamento de execuções do agente em JSONs (ver README.md): a classe `Tracer` é a única porta de entrada."""

from deep_agents.tracing.options import TraceOptions
from deep_agents.tracing.snapshot import build_config_snapshot
from deep_agents.tracing.tracer import Tracer

__all__ = ["Tracer", "TraceOptions", "build_config_snapshot"]

"""Opções do streaming (granularidade da resposta, o que capturar)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class StreamOptions:
    granularity: Literal["token", "word"] = "word"   # resposta palavra a palavra por padrão
    emit_reasoning: bool = True
    emit_tool_args_delta: bool = False               # TOOL_ARGS (debug)
    emit_subagent_tokens: bool = False               # tokens dos subagents como RESPONSE DELTA (agent≠main, DEBUG)
    emit_graph_steps: bool = False
    capture_raw: bool = False                        # guarda o resultado bruto em StreamEvent.raw
    summary_chars: int = 300
    arg_chars: int = 200
    summary_marker: str | None = "Resuma a conversa abaixo"   # início do prompt de resumo (identifica chamadas de resumo)

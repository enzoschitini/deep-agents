"""Opções do rastreamento."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "data" / "tracing"   # deep_agents/data/tracing


def _env_enabled() -> bool:
    return os.getenv("DEEP_AGENTS_TRACING", "1").strip().lower() not in {"0", "false", "off", "no"}


@dataclass(frozen=True)
class TraceOptions:
    enabled: bool = field(default_factory=_env_enabled)   # DEEP_AGENTS_TRACING=0 desliga
    base_dir: Path = DEFAULT_DIR
    max_str_chars: int = 100_000             # strings maiores são cortadas (com aviso do tamanho original)
    capture_chain_io: bool = False           # True guarda entradas/saídas completas dos chains do LangGraph (estado inteiro: pesado)
    summary_marker: str | None = "Resuma a conversa abaixo"   # início do prompt de resumo (marca as chamadas de resumo)
    pretty: bool = True                      # JSON indentado

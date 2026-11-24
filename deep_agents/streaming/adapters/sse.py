"""Codificação de um `StreamEvent` como frame de Server-Sent Events."""

from __future__ import annotations

import json

from deep_agents.streaming.events import StreamEvent


def encode_sse(event: StreamEvent, *, include_raw: bool = False) -> bytes:
    """`data: {json do evento}\n\n` em UTF-8 (uma linha só: o JSON não contém quebras de linha reais)."""
    payload = json.dumps(event.to_dict(include_raw=include_raw), ensure_ascii=False, default=str)
    return f"data: {payload}\n\n".encode("utf-8")

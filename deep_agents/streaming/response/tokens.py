"""Extração de texto/reasoning de um `AIMessageChunk` (conteúdo em str ou lista de blocos)."""

from __future__ import annotations

from typing import Any


def _reasoning_of(block: dict) -> str:
    """Texto de raciocínio de um bloco `reasoning` (padrão LangChain), `thinking` (Anthropic) ou `summary` (OpenAI)."""
    if isinstance(block.get("reasoning"), str):
        return block["reasoning"]
    if isinstance(block.get("thinking"), str):
        return block["thinking"]
    summary = block.get("summary")
    if isinstance(summary, list):
        return "".join(p.get("text", "") for p in summary if isinstance(p, dict))
    return ""


def extract(chunk: Any) -> tuple[str, str]:
    """(texto, reasoning) de um chunk. Chunks só com tool_call_chunks devolvem ("", "")."""
    try:
        blocks = chunk.content_blocks
    except Exception:
        blocks = None
    if blocks is None:
        content = getattr(chunk, "content", "")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else (content or [])
    text: list[str] = []
    reasoning: list[str] = []
    for b in blocks:
        if isinstance(b, str):
            text.append(b)
            continue
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "text":
            text.append(b.get("text") or "")
        elif t in ("reasoning", "thinking"):
            reasoning.append(_reasoning_of(b))
        elif t == "non_standard" and isinstance(b.get("value"), dict):
            v = b["value"]
            if v.get("type") in ("thinking", "reasoning"):
                reasoning.append(_reasoning_of(v))
    return "".join(text), "".join(reasoning)


def message_text(msg: Any) -> str:
    """Texto completo (sem reasoning) de um AIMessage; aceita content em str ou lista de blocos."""
    text, _ = extract(msg)
    if text:
        return text
    content = getattr(msg, "content", "")
    return content if isinstance(content, str) else ""


def tool_arg_fragments(chunk: Any) -> list[dict]:
    """Fragmentos de args das tool calls ({id, name, index, args})."""
    return [dict(c) for c in (getattr(chunk, "tool_call_chunks", None) or []) if c.get("args")]

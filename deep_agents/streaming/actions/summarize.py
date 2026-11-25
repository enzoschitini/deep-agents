"""Utilitários de resumo/serialização: encurtar texto, repr seguro e conversão para JSON (`to_jsonable`)."""

from __future__ import annotations

import dataclasses
import datetime as _dt
import math
from enum import Enum
from pathlib import PurePath
from typing import Any
from uuid import UUID

_MAX_DEPTH = 10
_ERROR_PREFIXES = ("Error:", "Error ", "We cannot invoke subagent")


def clip(text: Any, limit: int = 300) -> str:
    """Texto em uma linha, encurtado em `limit` caracteres (com «…» no fim)."""
    s = " ".join(str(text if text is not None else "").split())
    return s if len(s) <= limit else s[: max(limit - 1, 0)] + "…"


def safe_repr(obj: Any, limit: int = 300) -> str:
    """repr() que nunca levanta e é encurtado."""
    try:
        s = repr(obj)
    except Exception:
        s = f"<{type(obj).__name__}>"
    return clip(s, limit)


def to_jsonable(obj: Any, _depth: int = 0) -> Any:
    """Converte qualquer objeto em algo serializável por `json.dumps`, sem nunca levantar.

    Trata mensagens do LangChain, `Command`, exceções, UUID, dataclasses, enums, tuplas/sets, bytes e,
    por fim, objetos desconhecidos via `repr`."""
    try:
        return _convert(obj, _depth)
    except Exception:
        return safe_repr(obj)


def _is_command(obj: Any) -> bool:
    try:
        from langgraph.types import Command
    except Exception:
        return False
    return isinstance(obj, Command)


def _message_dict(obj: Any, depth: int) -> dict | None:
    try:
        from langchain_core.messages import BaseMessage
    except Exception:
        return None
    if not isinstance(obj, BaseMessage):
        return None
    out: dict[str, Any] = {"type": obj.type, "content": _convert(obj.content, depth + 1)}
    for attr in ("id", "name", "tool_call_id", "status"):
        value = getattr(obj, attr, None)
        if value is not None:
            out[attr] = _convert(value, depth + 1)
    tool_calls = getattr(obj, "tool_calls", None)
    if tool_calls:
        out["tool_calls"] = _convert(list(tool_calls), depth + 1)
    return out


def _convert(obj: Any, depth: int) -> Any:
    if depth > _MAX_DEPTH:
        return safe_repr(obj)
    if obj is None or isinstance(obj, bool):
        return obj
    if isinstance(obj, Enum):                       # antes de str/int (StrEnum é str)
        return _convert(obj.value, depth + 1)
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else str(obj)
    if isinstance(obj, str):
        return obj
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return bytes(obj).decode("utf-8", errors="replace")
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, (_dt.datetime, _dt.date, _dt.time)):
        return obj.isoformat()
    if isinstance(obj, PurePath):
        return str(obj)
    if isinstance(obj, BaseException):
        return {"type": type(obj).__name__, "message": str(obj)}
    message = _message_dict(obj, depth)
    if message is not None:
        return message
    if _is_command(obj):
        out: dict[str, Any] = {"command": True}
        for key in ("update", "goto", "resume", "graph"):
            value = getattr(obj, key, None)
            if value not in (None, ()):
                out[key] = _convert(value, depth + 1)
        return out
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _convert(getattr(obj, f.name, None), depth + 1) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {(k if isinstance(k, str) else str(k)): _convert(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_convert(v, depth + 1) for v in obj]
    dump = getattr(obj, "model_dump", None)          # pydantic
    if callable(dump):
        try:
            return _convert(dump(), depth + 1)
        except Exception:
            pass
    return safe_repr(obj, 2000)


def content_text(content: Any) -> str:
    """Texto de um `content` de mensagem (str ou lista de blocos)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type", "text") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return "" if content is None else str(content)


def tool_output(output: Any) -> tuple[str, bool]:
    """(texto, é_erro) da saída de uma tool: ToolMessage, Command (última mensagem do update), mensagem ou str.

    É erro quando o ToolMessage tem `status == "error"` ou o texto começa como as mensagens de erro das tools."""
    from langchain_core.messages import BaseMessage

    message = output
    if _is_command(output):
        update = output.update
        msgs = update.get("messages") if isinstance(update, dict) else None
        if isinstance(msgs, (list, tuple)) and msgs:
            message = msgs[-1]
        elif isinstance(msgs, BaseMessage):
            message = msgs
        else:
            return safe_repr(update, 2000), False
    if isinstance(message, BaseMessage):
        text = content_text(message.content)
        return text, getattr(message, "status", None) == "error" or text.startswith(_ERROR_PREFIXES)
    if isinstance(output, str):
        text = output
    elif isinstance(output, list):
        text = content_text(output)
    else:
        text = safe_repr(output, 2000)
    return text, text.startswith(_ERROR_PREFIXES)

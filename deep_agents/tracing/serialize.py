"""Serialização segura para JSON: corta textos enormes, esconde segredos e nunca levanta."""

from __future__ import annotations

import dataclasses
import datetime as _dt
import math
import re
from collections.abc import Mapping
from enum import Enum
from pathlib import PurePath
from typing import Any
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from deep_agents.streaming.actions.summarize import content_text, safe_repr, tool_output

REDACTED = "[redacted]"
# `max_tokens`/`max_output_tokens` NÃO casam (o `token` só conta no fim da chave e no singular).
_SECRET_KEY = re.compile(r"(api[_-]?key|secret|passw(or)?d|authorization|bearer|credential|headers?$|(^|[_-])token$)", re.I)
_MAX_DEPTH = 14


def iso(ts: float | None) -> str | None:
    """Epoch (segundos) -> ISO-8601 UTC com milissegundos."""
    if ts is None:
        return None
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).isoformat(timespec="milliseconds")


def clip_str(s: str, limit: int) -> str:
    if limit and len(s) > limit:
        return f"{s[:limit]}… [+{len(s) - limit} chars truncados]"
    return s


def is_secret_key(key: Any) -> bool:
    return isinstance(key, str) and bool(_SECRET_KEY.search(key))


def to_json_safe(obj: Any, limit: int = 100_000, _depth: int = 0) -> Any:
    """Converte qualquer objeto em estruturas JSON. Mensagens do LangChain viram dicts completos."""
    try:
        return _convert(obj, limit, _depth)
    except Exception:
        return safe_repr(obj, 500)


def _convert(obj: Any, limit: int, depth: int) -> Any:
    if depth > _MAX_DEPTH:
        return safe_repr(obj, 200)
    if obj is None or isinstance(obj, bool):
        return obj
    if isinstance(obj, Enum):
        return _convert(obj.value, limit, depth + 1)
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else str(obj)
    if isinstance(obj, str):
        return clip_str(obj, limit)
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(obj))} bytes>"
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, (_dt.datetime, _dt.date, _dt.time)):
        return obj.isoformat()
    if isinstance(obj, PurePath):
        return str(obj)
    if isinstance(obj, BaseException):
        return {"type": type(obj).__name__, "message": clip_str(str(obj), limit)}
    if isinstance(obj, BaseMessage):
        return serialize_message(obj, limit, depth + 1)
    if isinstance(obj, Mapping):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            key = k if isinstance(k, str) else str(k)
            out[key] = REDACTED if (is_secret_key(key) and isinstance(v, (str, Mapping, list, tuple))) else _convert(v, limit, depth + 1)
        return out
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_convert(v, limit, depth + 1) for v in obj]
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _convert(getattr(obj, f.name, None), limit, depth + 1) for f in dataclasses.fields(obj)}
    dump = getattr(obj, "model_dump", None)   # pydantic
    if callable(dump):
        try:
            return _convert(dump(), limit, depth + 1)
        except Exception:
            pass
    return safe_repr(obj, 2000)


def serialize_message(msg: BaseMessage, limit: int = 100_000, _depth: int = 0) -> dict[str, Any]:
    """Mensagem completa: tipo, id, nome, conteúdo (str ou blocos), tool calls, usage e metadados."""
    out: dict[str, Any] = {
        "type": msg.type,
        "id": getattr(msg, "id", None),
        "name": getattr(msg, "name", None),
        "content": _convert(msg.content, limit, _depth + 1),
    }
    if isinstance(msg, AIMessage):
        out["tool_calls"] = _convert(list(msg.tool_calls or []), limit, _depth + 1)
        if msg.invalid_tool_calls:
            out["invalid_tool_calls"] = _convert(list(msg.invalid_tool_calls), limit, _depth + 1)
        if msg.usage_metadata:
            out["usage_metadata"] = _convert(dict(msg.usage_metadata), limit, _depth + 1)
        if msg.response_metadata:
            out["response_metadata"] = _convert(dict(msg.response_metadata), limit, _depth + 1)
    if isinstance(msg, ToolMessage):
        out["tool_call_id"] = msg.tool_call_id
        out["status"] = getattr(msg, "status", None)
        if getattr(msg, "artifact", None) is not None:
            out["artifact"] = _convert(msg.artifact, limit, _depth + 1)
    if msg.additional_kwargs:
        out["additional_kwargs"] = _convert(dict(msg.additional_kwargs), limit, _depth + 1)
    return out


def serialize_tool_output(output: Any, limit: int = 100_000) -> dict[str, Any]:
    """Saída de uma tool: ToolMessage, Command (update/goto), str ou outro objeto."""
    text, is_error = tool_output(output)
    base: dict[str, Any] = {"type": type(output).__name__, "text": clip_str(text, limit), "is_error": is_error}
    if isinstance(output, BaseMessage):
        base["message"] = serialize_message(output, limit)
        return base
    update = getattr(output, "update", None)
    if update is not None or type(output).__name__ == "Command":
        base["update_keys"] = sorted(update) if isinstance(update, dict) else None
        base["update"] = to_json_safe(update, limit)
        base["goto"] = to_json_safe(getattr(output, "goto", None), limit)
        return base
    base["content"] = to_json_safe(output, limit)
    return base


def message_text(msg: Any) -> str:
    return content_text(getattr(msg, "content", msg))

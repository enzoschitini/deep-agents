"""RunRegistry: estado compartilhado (thread-safe) entre o callback de ações e o parser de tokens."""

from __future__ import annotations

import threading
from typing import Any


class RunRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._llm: dict[str, dict[str, Any]] = {}           # run_id do LLM -> {purpose, ns, agent}
        self._tools: dict[str, dict[str, Any]] = {}         # tool_call_id -> {name, ns, run_id}
        self._subagent_ns: dict[str, tuple[str, str]] = {}  # agent_ns ("tools:X") -> (tool_call_id, nome)

    def llm_started(self, run_id: str, *, purpose: str, ns: tuple[str, ...] = (), agent: str = "main") -> None:
        with self._lock:
            self._llm[str(run_id)] = {"purpose": purpose, "ns": ns, "agent": agent}

    def llm_purpose(self, run_id: str) -> str | None:
        """`agent` | `summary` | None (run desconhecido). Aceita também o id de chunk `lc_run--<run_id>`."""
        key = str(run_id)
        if key.startswith("lc_run--"):
            key = key[len("lc_run--"):]
        with self._lock:
            info = self._llm.get(key)
            return info["purpose"] if info else None

    def tool_started(self, tool_call_id: str, *, name: str, ns: tuple[str, ...] = (), run_id: str | None = None) -> None:
        with self._lock:
            self._tools[str(tool_call_id)] = {"name": name, "ns": ns, "run_id": run_id}

    def register_subagent_ns(self, agent_ns: str, *, tool_call_id: str, name: str) -> None:
        with self._lock:
            self._subagent_ns[agent_ns] = (str(tool_call_id), name)

    @staticmethod
    def _key(ns: tuple[str, ...] | str) -> str:
        return ns if isinstance(ns, str) else "|".join(ns)

    def agent_for(self, ns: tuple[str, ...] | str) -> tuple[str, str | None]:
        """(nome, agent_id) do agente dono do namespace; ("main", None) para o principal, ("subagent", None) se desconhecido."""
        key = self._key(ns)
        if not key:
            return "main", None
        with self._lock:
            found = self._subagent_ns.get(key)
        if found is None:
            return "subagent", None
        return found[1], found[0]

    def parent_for(self, ns: tuple[str, ...] | str) -> str | None:
        """tool_call_id da `task` que originou o namespace (None no principal)."""
        key = self._key(ns)
        if not key:
            return None
        with self._lock:
            found = self._subagent_ns.get(key)
        return found[0] if found else None

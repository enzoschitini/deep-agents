"""Classifica uma chamada de tool: (EventKind, Visibility, data) a partir do nome e dos argumentos."""

from __future__ import annotations

import re
from typing import Any

from deep_agents.streaming.actions.summarize import clip
from deep_agents.streaming.events import EventKind, Visibility

SKILL_PATH = re.compile(r"/skills/([^/\s'\"]+)/SKILL\.md")

FILE_TOOLS = frozenset({"ls", "read_file", "write_file", "edit_file", "glob", "grep"})
ASYNC_TOOLS = {
    "start_async_task": "start", "check_async_task": "check", "update_async_task": "update",
    "cancel_async_task": "cancel", "list_async_tasks": "list",
}


def _path(args: dict) -> str:
    for key in ("file_path", "path"):
        if isinstance(args.get(key), str):
            return args[key]
    return ""


def todo_counts(args: dict) -> tuple[list, int, int]:
    """(todos, concluídos, total) do argumento de `write_todos`."""
    todos = args.get("todos")
    todos = list(todos) if isinstance(todos, (list, tuple)) else []
    done = sum(1 for t in todos if isinstance(t, dict) and t.get("status") == "completed")
    return todos, done, len(todos)


def classify(name: str | None, args: dict | None, *, description_chars: int = 300) -> tuple[EventKind, Visibility, dict[str, Any]]:
    """Devolve (kind, visibility, data). `data` traz o que é específico do tipo (op/path, skill, done/total…)."""
    name = name or ""
    args = args if isinstance(args, dict) else {}
    if name == "task":
        return EventKind.SUBAGENT, Visibility.PRIMARY, {
            "subagent_type": args.get("subagent_type"), "description": clip(args.get("description"), description_chars)}
    if name == "eval":
        code = args.get("code")
        return EventKind.CODE_EVAL, Visibility.SECONDARY, {"code": clip(code, description_chars) if isinstance(code, str) else None}
    if name == "write_todos":
        todos, done, total = todo_counts(args)
        return EventKind.TODOS, Visibility.PRIMARY, {"todos": todos, "done": done, "total": total}
    if name == "read_file":
        match = SKILL_PATH.search(_path(args))
        if match:
            return EventKind.SKILL, Visibility.PRIMARY, {"skill": match.group(1), "path": _path(args)}
    if name in FILE_TOOLS:
        data: dict[str, Any] = {"op": name, "path": _path(args)}
        if isinstance(args.get("pattern"), str):
            data["pattern"] = args["pattern"]
        return EventKind.FILE, Visibility.SECONDARY, data
    if name in ASYNC_TOOLS:
        data = {"action": ASYNC_TOOLS[name]}
        for key in ("subagent_type", "task_id"):
            if args.get(key):
                data[key] = args[key]
        if args.get("description"):
            data["description"] = clip(args["description"], description_chars)
        return EventKind.ASYNC_TASK, Visibility.PRIMARY, data
    if name == "compact_conversation":
        return EventKind.SUMMARIZATION, Visibility.SECONDARY, {"manual": True}
    return EventKind.TOOL, Visibility.PRIMARY, {}

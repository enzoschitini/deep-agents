"""Modelo de evento do streaming: um `StreamEvent` JSON-serializável para cada passo do agente.

O módulo emite TUDO; a `visibility` é só uma sugestão para o front (CLI/web) filtrar o que mostrar."""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EventKind(StrEnum):
    RUN = "run"                       # START | END | ERROR | CANCELLED (END.data: answer, stats, metrics, sources)
    RESPONSE = "response"             # DELTA (data.text) | END (data.final, data.text, data.message_id)
    REASONING = "reasoning"           # DELTA (thinking do principal; data.text)
    MODEL_CALL = "model_call"         # START | END | ERROR (data: purpose agent|summary, model, usage, latency_s, finish_reason, decision)
    TOOL = "tool"                     # tool comum (START|END|ERROR)
    TOOL_ARGS = "tool_args"           # DELTA (fragmentos JSON dos args; DEBUG)
    SUBAGENT = "subagent"             # delegação `task` (START|END|ERROR); name = subagent_type
    SUBAGENT_DYNAMIC = "subagent_dynamic"   # evento `subagent` do QuickJS (id "dyn-<id>", parent_id = eval_id)
    CODE_EVAL = "code_eval"           # tool `eval` (REPL JS)
    ASYNC_TASK = "async_task"         # start/check/update/cancel/list_async_task(s); data.action
    TODOS = "todos"                   # write_todos; data.todos, data.done, data.total
    SKILL = "skill"                   # read_file em .../skills/<nome>/SKILL.md; data.skill
    FILE = "file"                     # ls/read_file/write_file/edit_file/glob/grep; data.op, data.path
    SUMMARIZATION = "summarization"   # resumo de contexto
    GRAPH_STEP = "graph_step"         # nó concluído (updates); data.node (DEBUG)
    SOURCES = "sources"               # canal lateral do turno, deduplicado (data.sources)
    CUSTOM = "custom"                 # get_stream_writer() de tools do usuário (data = payload)
    INTERRUPT = "interrupt"
    NOTICE = "notice"                 # avisos não fatais (data.message)


class Phase(StrEnum):
    START = "start"
    DELTA = "delta"
    END = "end"
    ERROR = "error"
    INFO = "info"
    CANCELLED = "cancelled"   # só RUN


class Visibility(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    DEBUG = "debug"

    @property
    def level(self) -> int:
        return {"primary": 0, "secondary": 1, "debug": 2}[self.value]

    def __le__(self, other: "Visibility") -> bool:   # PRIMARY <= SECONDARY <= DEBUG
        return self.level <= other.level

    def __lt__(self, other: "Visibility") -> bool:
        return self.level < other.level

    def __ge__(self, other: "Visibility") -> bool:
        return self.level >= other.level

    def __gt__(self, other: "Visibility") -> bool:
        return self.level > other.level


@dataclass(slots=True)
class StreamEvent:
    seq: int                                  # monotônico dentro do run (atribuído pelo EventBus.emit)
    ts: float                                 # time.time()
    run_id: str                               # um por AgentStreamer.start()
    id: str                                   # id do item (tool_call_id / run_id do LLM / message_id / "dyn-…"); START/END/ERROR do mesmo item compartilham
    kind: EventKind
    phase: Phase
    parent_id: str | None = None              # item que causou este (ex.: tool_call_id da `task`/`eval`)
    agent: str = "main"                       # "main" ou o nome do subagent
    agent_id: str | None = None               # tool_call_id da task do subagent; None no principal
    ns: tuple[str, ...] = ()                  # namespace do LangGraph
    depth: int = 0                            # len(ns)
    name: str | None = None                   # tool / subagent / modelo
    label: str = ""                           # texto pronto em italiano ("Consulto lo strumento internet_search «…»…")
    args: dict | None = None
    summary: str | None = None                # resultado resumido
    raw: Any = None                           # bruto, só com options.capture_raw
    error: str | None = None
    duration_s: float | None = None
    visibility: Visibility = Visibility.SECONDARY
    data: dict = field(default_factory=dict)  # específico do tipo

    def to_dict(self, *, include_raw: bool = False) -> dict:
        """Dict JSON-safe; as chaves são os nomes dos campos (enums viram str, ns vira lista)."""
        from deep_agents.streaming.actions.summarize import to_jsonable   # import tardio: evita ciclo
        out: dict[str, Any] = {}
        for f in dataclasses.fields(self):
            if f.name == "raw" and not include_raw:
                continue
            out[f.name] = to_jsonable(getattr(self, f.name))
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "StreamEvent":
        d = dict(d)
        d["kind"] = EventKind(d["kind"])
        d["phase"] = Phase(d["phase"])
        d["visibility"] = Visibility(d.get("visibility", "secondary"))
        d["ns"] = tuple(d.get("ns") or ())
        names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


@dataclass(slots=True)
class RunStats:
    """Resumo do turno (vem em RUN_END.data["stats"]); alimenta `format_metrics`."""

    n_tools: int = 0
    n_subagents: int = 0
    n_dynamic_subagents: int = 0
    n_llm_calls: int = 0
    tools: dict[str, int] = field(default_factory=dict)
    skills: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    todos_updates: int = 0
    errors: int = 0

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def now() -> float:
    return time.time()

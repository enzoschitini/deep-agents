"""Parsers dos modos `updates` e `custom` do stream do LangGraph (devolvem listas de StreamEvent)."""

from __future__ import annotations

import itertools
from typing import Any

from deep_agents.streaming.actions.callbacks import ActionStats
from deep_agents.streaming.actions.labels import label
from deep_agents.streaming.actions.summarize import clip, content_text, to_jsonable
from deep_agents.streaming.bus import EventBus
from deep_agents.streaming.events import EventKind, Phase, StreamEvent, Visibility
from deep_agents.streaming.options import StreamOptions
from deep_agents.streaming.registry import RunRegistry

SUMMARIZATION_EVENT_KEY = "_summarization_event"   # chave de estado do SummarizationMiddleware (deepagents)


class StreamParser:
    def __init__(self, bus: EventBus, registry: RunRegistry, options: StreamOptions, stats: ActionStats) -> None:
        self.bus, self.registry, self.options, self.stats = bus, registry, options, stats
        self._counter = itertools.count(1)

    def _make(self, kind: EventKind, phase: Phase, ns: tuple[str, ...], *, id: str, **fields: Any) -> StreamEvent:
        agent, agent_id = self.registry.agent_for(ns)
        fields.setdefault("parent_id", self.registry.parent_for(ns))
        return self.bus.make(kind, phase, id=id, ns=ns, agent=agent, agent_id=agent_id, **fields)

    # ------------------------------------------------------------------ custom
    def parse_custom(self, ns: tuple[str, ...], data: Any) -> list[StreamEvent]:
        ns = tuple(ns or ())
        if isinstance(data, dict) and data.get("type") == "subagent":
            return [self._dynamic(ns, data)]
        payload = to_jsonable(data)
        if not isinstance(payload, dict):
            payload = {"value": payload}
        summary = clip(payload.get("message") or payload.get("text") or payload, self.options.summary_chars)
        return [self._make(EventKind.CUSTOM, Phase.INFO, ns, id=f"custom-{next(self._counter)}", visibility=Visibility.SECONDARY,
                           name=str(payload.get("type") or "custom"), summary=summary, data=payload,
                           label=label(EventKind.CUSTOM, Phase.INFO))]

    def _dynamic(self, ns: tuple[str, ...], data: dict) -> StreamEvent:
        """Evento `subagent` do QuickJS (start/complete/error). `id` é idempotente: o replay reemite o start (upsert)."""
        raw_id = data.get("id") or f"anon-{next(self._counter)}"
        dyn_id = f"dyn-{raw_id}"
        phase_raw = str(data.get("phase") or "")
        name = data.get("subagent_type") or data.get("label") or "subagent"
        info = {"description": data.get("description"), "label": data.get("label"), "eval_id": data.get("eval_id"),
                "subagent_type": data.get("subagent_type"), "phase": phase_raw}
        fresh = self.stats.dynamic_started(dyn_id) if phase_raw in ("start", "complete", "error") else True
        if phase_raw == "start" and not fresh:
            info["replay"] = True   # reemissão do start (replay do grafo): o consumidor faz upsert
        common = {"parent_id": data.get("eval_id") or self.registry.parent_for(ns), "name": name}
        if phase_raw == "start":
            return self._make(EventKind.SUBAGENT_DYNAMIC, Phase.START, ns, id=dyn_id, visibility=Visibility.PRIMARY,
                              data={k: v for k, v in info.items() if v is not None},
                              label=label(EventKind.SUBAGENT_DYNAMIC, Phase.START, name, data=info), **common)
        duration = data.get("duration_ms")
        duration_s = duration / 1000 if isinstance(duration, (int, float)) else None
        if phase_raw == "complete":
            return self._make(EventKind.SUBAGENT_DYNAMIC, Phase.END, ns, id=dyn_id, visibility=Visibility.PRIMARY,
                              duration_s=duration_s, data={k: v for k, v in info.items() if v is not None},
                              label=label(EventKind.SUBAGENT_DYNAMIC, Phase.END, name, data=info), **common)
        if phase_raw == "error":
            self.stats.error()
            return self._make(EventKind.SUBAGENT_DYNAMIC, Phase.ERROR, ns, id=dyn_id, visibility=Visibility.PRIMARY,
                              duration_s=duration_s, error=str(data.get("error") or "errore"),
                              data={k: v for k, v in info.items() if v is not None},
                              label=label(EventKind.SUBAGENT_DYNAMIC, Phase.ERROR, name, data=info), **common)
        # fase desconhecida: informa sem quebrar
        return self._make(EventKind.SUBAGENT_DYNAMIC, Phase.INFO, ns, id=dyn_id, visibility=Visibility.SECONDARY,
                          data={"payload": to_jsonable(data), **{k: v for k, v in info.items() if v is not None}},
                          label=label(EventKind.SUBAGENT_DYNAMIC, Phase.INFO, name, data=info), **common)

    # ------------------------------------------------------------------ updates
    def parse_update(self, ns: tuple[str, ...], data: dict) -> list[StreamEvent]:
        ns = tuple(ns or ())
        events: list[StreamEvent] = []
        if not isinstance(data, dict):
            return events
        for node, update in data.items():
            if node == "__interrupt__":
                events.extend(self._interrupts(ns, update))
                continue
            if isinstance(update, dict) and update.get(SUMMARIZATION_EVENT_KEY):
                events.append(self._summarization(ns, update[SUMMARIZATION_EVENT_KEY]))
            if self.options.emit_graph_steps:
                keys = list(update.keys()) if isinstance(update, dict) else []
                events.append(self._make(EventKind.GRAPH_STEP, Phase.END, ns, id=f"step-{next(self._counter)}", name=str(node),
                                         visibility=Visibility.DEBUG, data={"node": str(node), "keys": keys},
                                         label=label(EventKind.GRAPH_STEP, Phase.END, str(node), data={"node": str(node)})))
        return events

    def _interrupts(self, ns: tuple[str, ...], update: Any) -> list[StreamEvent]:
        items = update if isinstance(update, (list, tuple)) else [update]
        out = []
        for item in items:
            value = getattr(item, "value", item)
            iid = getattr(item, "id", None) or f"interrupt-{next(self._counter)}"
            out.append(self._make(EventKind.INTERRUPT, Phase.INFO, ns, id=str(iid), visibility=Visibility.PRIMARY,
                                  summary=clip(value, self.options.summary_chars), data={"interrupt_id": str(iid), "value": to_jsonable(value)},
                                  label=label(EventKind.INTERRUPT, Phase.INFO)))
        return out

    def _summarization(self, ns: tuple[str, ...], event: Any) -> StreamEvent:
        cutoff = event.get("cutoff_index") if isinstance(event, dict) else None
        msg = event.get("summary_message") if isinstance(event, dict) else None
        text = content_text(getattr(msg, "content", msg)) if msg is not None else ""
        return self._make(EventKind.SUMMARIZATION, Phase.INFO, ns, id=f"sum-event-{cutoff}-{next(self._counter)}",
                          visibility=Visibility.SECONDARY, summary=clip(text, self.options.summary_chars),
                          data={"cutoff_index": cutoff, "chars": len(text)}, label=label(EventKind.SUMMARIZATION, Phase.INFO))

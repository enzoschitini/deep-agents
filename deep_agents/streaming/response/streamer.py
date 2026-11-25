"""ResponseStreamer: transforma chunks de `messages` em eventos RESPONSE/REASONING/TOOL_ARGS."""

from __future__ import annotations

from typing import Any

from deep_agents.streaming.events import EventKind, Phase, StreamEvent, Visibility
from deep_agents.streaming.options import StreamOptions
from deep_agents.streaming.response.accumulator import ResponseAccumulator
from deep_agents.streaming.response.chunker import WordCoalescer
from deep_agents.streaming.response.tokens import extract, message_text, tool_arg_fragments


class _MsgState:
    """Estado de uma mensagem em andamento (coalescers, índice de delta, contexto)."""

    def __init__(self, granularity: str, ns: tuple[str, ...], agent: str, agent_id: str | None, main: bool) -> None:
        self.text = WordCoalescer(granularity)
        self.reasoning = WordCoalescer(granularity)
        self.index = 0
        self.ns, self.agent, self.agent_id, self.main = ns, agent, agent_id, main


class ResponseStreamer:
    def __init__(self, bus: Any, registry: Any, options: StreamOptions) -> None:
        self.bus, self.registry, self.options = bus, registry, options
        self._acc = ResponseAccumulator()
        self._msgs: dict[str, _MsgState] = {}

    # --- eventos ---------------------------------------------------------
    def _delta(self, mid: str, st: _MsgState, text: str, reasoning: bool = False) -> StreamEvent:
        kind = EventKind.REASONING if reasoning else EventKind.RESPONSE
        if st.main:
            vis = Visibility.SECONDARY if reasoning else Visibility.PRIMARY
        else:
            vis = Visibility.DEBUG
        data: dict[str, Any] = {"text": text, "message_id": mid}
        if not reasoning:
            data["index"] = st.index
            st.index += 1
        return self.bus.make(kind, Phase.DELTA, id=mid, ns=st.ns, agent=st.agent, agent_id=st.agent_id,
                             visibility=vis, data=data)

    def _drain(self, mid: str, st: _MsgState) -> list[StreamEvent]:
        out: list[StreamEvent] = []
        if (r := st.reasoning.flush()):
            out.append(self._delta(mid, st, r, reasoning=True))
        if (t := st.text.flush()):
            if st.main:
                self._acc.add(mid, t)
            out.append(self._delta(mid, st, t))
        return out

    # --- ResponseParser --------------------------------------------------
    def feed_message(self, chunk: Any, metadata: dict, ns: tuple[str, ...]) -> list[StreamEvent]:
        ns = tuple(ns)
        if ns and not self.options.emit_subagent_tokens:
            return []
        mid = getattr(chunk, "id", None) or ""
        if self.registry.llm_purpose(mid) == "summary":
            return []
        events: list[StreamEvent] = []
        st = self._msgs.get(mid)
        if st is None:
            if ns:
                name, aid = self.registry.agent_for(ns)
                agent = (metadata or {}).get("lc_agent_name") or name
            else:
                agent, aid = "main", None
            st = self._msgs[mid] = _MsgState(self.options.granularity, ns, agent, aid, main=not ns)
        text, reasoning = extract(chunk)
        if reasoning and self.options.emit_reasoning:
            events += [self._delta(mid, st, p, reasoning=True) for p in st.reasoning.push(reasoning)]
        for piece in st.text.push(text):
            if st.main:
                self._acc.add(mid, piece)
            events.append(self._delta(mid, st, piece))
        if self.options.emit_tool_args_delta:
            for frag in tool_arg_fragments(chunk):
                events.append(self.bus.make(
                    EventKind.TOOL_ARGS, Phase.DELTA, id=str(frag.get("id") or f"{mid}:{frag.get('index', 0)}"),
                    ns=ns, agent=st.agent, agent_id=st.agent_id, name=frag.get("name"),
                    visibility=Visibility.DEBUG,
                    data={"args_delta": frag["args"], "message_id": mid, "index": frag.get("index")}))
        return events

    def on_model_update(self, ns: tuple[str, ...], ai_message: Any) -> list[StreamEvent]:
        if tuple(ns):
            return []
        mid = getattr(ai_message, "id", None) or ""
        events: list[StreamEvent] = []
        st = self._msgs.pop(mid, None)
        if st is not None:
            events += self._drain(mid, st)
        text = message_text(ai_message) or self._acc.text_of(mid)
        final = not getattr(ai_message, "tool_calls", None)
        self._acc.close(mid, text, final)
        events.append(self.bus.make(EventKind.RESPONSE, Phase.END, id=mid, visibility=Visibility.PRIMARY,
                                    data={"message_id": mid, "final": final, "text": text}))
        return events

    def flush(self) -> list[StreamEvent]:
        events: list[StreamEvent] = []
        for mid, st in list(self._msgs.items()):
            events += self._drain(mid, st)
        self._msgs.clear()
        return events

    def final_text(self) -> str:
        return self._acc.final_text()

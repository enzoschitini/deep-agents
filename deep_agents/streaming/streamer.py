"""AgentStreamer: roda o agente numa thread de trabalho e entrega um fluxo único de `StreamEvent`.

Fluxo: `start()` cria o run (bus, registry, parsers), emite RUN/START e dispara UMA thread que consome
`agent.stream(..., version="v2")` com os modos messages/updates/custom/values. Os eventos de resposta (tokens)
vêm do `ResponseStreamer`; os de ações (tools, subagents, modelo) do `ActionTracker` (callback + updates/custom).
O iterador do `RunHandle` NUNCA levanta: erro, cancelamento e fim viram eventos RUN/ERROR, RUN/CANCELLED, RUN/END."""

from __future__ import annotations

import asyncio
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Iterator

from langchain_core.messages import AIMessageChunk

from deep_agents.streaming.bus import EventBus
from deep_agents.streaming.events import EventKind, Phase, RunStats, StreamEvent, Visibility
from deep_agents.streaming.options import StreamOptions
from deep_agents.streaming.registry import RunRegistry

STREAM_MODES = ["messages", "updates", "custom", "values"]
_STOP = object()


@dataclass
class RunResult:
    """Resultado de um run; os campos são preenchidos durante a execução e ficam definitivos após o iterador esgotar."""

    state: dict | None = None
    answer: str = ""
    report: Any = None                  # RunReport (None se não há gateway)
    stats: RunStats | None = None
    error: BaseException | None = None
    cancelled: bool = False
    sources: list[dict] = field(default_factory=list)


class RunHandle:
    """Controle de um run em andamento: iterar (eventos), cancelar, esperar."""

    def __init__(self, run_id: str, bus: EventBus, result: RunResult, cancel_event: threading.Event,
                 on_cancel: Callable[[], None], done: threading.Event) -> None:
        self.run_id = run_id
        self._bus = bus
        self._result = result
        self._cancel_event = cancel_event
        self._on_cancel = on_cancel
        self._done = done                 # a thread de trabalho terminou
        self._thread: threading.Thread | None = None

    def __iter__(self) -> Iterator[StreamEvent]:
        """Eventos em ordem, até RUN END/ERROR/CANCELLED. Nunca levanta."""
        return iter(self._bus)

    def cancel(self) -> None:
        """Interrompe o run: emite RUN/CANCELLED na hora e fecha o fluxo (a thread encerra no próximo chunk)."""
        self._cancel_event.set()
        self._on_cancel()

    def join(self, timeout: float | None = None) -> RunResult:
        if self._thread is not None:
            self._thread.join(timeout)
        return self._result

    @property
    def result(self) -> RunResult:
        return self._result

    @property
    def done(self) -> bool:
        return self._done.is_set()


class AgentStreamer:
    def __init__(self, agent: Any, gateway: Any = None, *, options: StreamOptions | None = None,
                 channel: Any = None, sinks: tuple | list = (), tracer: Any = None, origin: str | None = None) -> None:
        """`tracer` (um `tracing.Tracer`) grava o rastreamento detalhado de cada run em JSON; `origin` ("cli", "web"…) vai junto."""
        self.agent = agent
        self.gateway = gateway
        self.options = options or StreamOptions()
        self.channel = channel
        self.sinks = list(sinks)
        self.tracer = tracer
        self.origin = origin

    # -- API pública --
    def start(self, messages: list[dict], *, label: str | None = None, config: dict | None = None) -> RunHandle:
        from deep_agents.streaming.actions import ActionTracker      # import tardio: evita ciclos e custo no import do pacote
        from deep_agents.streaming.response import ResponseStreamer

        run_id = uuid.uuid4().hex
        bus = EventBus(run_id)
        for sink in self.sinks:
            bus.add_sink(sink)
        registry = RunRegistry()
        run = _Run(
            agent=self.agent, gateway=self.gateway, options=self.options, channel=self.channel,
            run_id=run_id, bus=bus, label=label, config=dict(config or {}), messages=list(messages),
            tracer=self.tracer,
            response=ResponseStreamer(bus, registry, self.options),
            actions=ActionTracker(bus, registry, self.options),
        )
        run.turn = self.channel.begin_turn() if self.channel is not None else None
        if self.tracer is not None:   # antes do RUN/START: o sink já recebe o primeiro evento
            self.tracer.begin_run(run_id, messages=list(messages), label=label, origin=self.origin,
                                  model_config=getattr(self.gateway, "config", None), turn=run.turn)
            bus.add_sink(self.tracer.sink(run_id))
        handle = RunHandle(run_id, bus, run.result, run.cancel_event, run.on_cancel, run.done)
        bus.emit(bus.make(
            EventKind.RUN, Phase.START, id=run_id, label="Avvio la richiesta…", visibility=Visibility.PRIMARY,
            data={"n_messages": len(messages), "label": label},
        ))
        handle._thread = threading.Thread(target=run.work, name=f"agent-run-{run_id[:8]}", daemon=True)
        handle._thread.start()
        return handle

    def stream(self, messages: list[dict], **kw) -> Iterator[StreamEvent]:
        """Gerador síncrono de eventos; se o consumidor para antes do fim, o run é cancelado."""
        handle = self.start(messages, **kw)
        try:
            yield from handle
        finally:
            if not handle.done:
                handle.cancel()

    async def astream(self, messages: list[dict], **kw) -> AsyncIterator[StreamEvent]:
        handle = self.start(messages, **kw)
        iterator = iter(handle)
        try:
            while True:
                ev = await asyncio.to_thread(next, iterator, _STOP)
                if ev is _STOP:
                    break
                yield ev
        finally:
            if not handle.done:
                handle.cancel()


class _Run:
    """Estado e corpo de UM run (executa na thread de trabalho)."""

    def __init__(self, *, agent, gateway, options, channel, run_id, bus, label, config, messages,
                 response, actions, tracer=None) -> None:
        self.tracer = tracer
        self.agent, self.gateway, self.options, self.channel = agent, gateway, options, channel
        self.run_id, self.bus = run_id, bus
        self.label, self.config, self.messages = label, config, messages
        self.response, self.actions = response, actions
        self.turn: int | None = None
        self.result = RunResult()
        self.cancel_event = threading.Event()
        self.done = threading.Event()
        self._terminal_lock = threading.Lock()
        self._terminal = False

    @staticmethod
    def _safe(fn, default):
        try:
            return fn()
        except Exception:
            return default

    # -- terminal único: só um entre END/ERROR/CANCELLED é emitido --
    def _claim_terminal(self) -> bool:
        with self._terminal_lock:
            if self._terminal:
                return False
            self._terminal = True
            return True

    def on_cancel(self) -> None:
        if not self._claim_terminal():
            return
        self.result.cancelled = True
        self.result.answer = self._safe(self.response.final_text, "")
        self.result.stats = self._safe(self.actions.stats, None)
        self.bus.emit(self.bus.make(
            EventKind.RUN, Phase.CANCELLED, id=self.run_id, label="Risposta interrotta.",
            visibility=Visibility.PRIMARY, data={"answer": self.result.answer},
        ))
        self.bus.close()

    @contextmanager
    def _tracked(self):
        """(report, callbacks de métricas). Usa `gateway.tracked_run` se existir; senão monta o equivalente."""
        gw = self.gateway
        if gw is None:
            yield None, []
            return
        tracked = getattr(gw, "tracked_run", None)
        if tracked is not None:
            with tracked(self.label) as (report, handlers):
                if isinstance(handlers, dict):
                    handlers = handlers.get("callbacks", [])
                yield report, list(handlers)
            return
        report, cfg = gw._new_run(self.label)
        t0 = time.perf_counter()
        try:
            yield report, list(cfg["callbacks"])
        finally:
            report.wall_time_s = time.perf_counter() - t0
            gw.history.append(report)

    # -- corpo --
    def work(self) -> None:
        state: dict | None = None
        error: BaseException | None = None
        try:
            with self._tracked() as (report, handlers):
                self.result.report = report
                state = self._consume(handlers)
        except BaseException as e:   # noqa: BLE001 - nada pode escapar da thread; vira RUN/ERROR
            error = e
        try:
            self._finish(state, error)
        except BaseException as e:   # noqa: BLE001 - falha ao montar o fim: ainda assim fecha o fluxo com erro
            if self._claim_terminal():
                self.result.error = e
                self.bus.emit(self.bus.make(
                    EventKind.RUN, Phase.ERROR, id=self.run_id, label="Errore durante la risposta.",
                    error=str(e) or type(e).__name__, visibility=Visibility.PRIMARY, data={"type": type(e).__name__},
                ))
        finally:
            try:
                self._trace_end()   # grava os JSONs antes de fechar o fluxo: quem acabou de iterar já os encontra
            except BaseException:   # noqa: BLE001 - o rastreamento nunca derruba o run
                pass
            self.bus.close()
            self.done.set()

    def _consume(self, handlers: list) -> dict | None:
        bus, response, actions = self.bus, self.response, self.actions
        extra = [h for h in [self.tracer.callback(self.run_id) if self.tracer is not None else None] if h is not None]
        cfg = {**self.config, "callbacks": [*self.config.get("callbacks", []), *handlers, actions.handler, *extra]}
        state: dict | None = None
        stream = self.agent.stream(
            {"messages": self.messages}, config=cfg, stream_mode=STREAM_MODES, subgraphs=True, version="v2",
        )
        try:
            for ch in stream:
                if self.cancel_event.is_set():
                    break
                ns = tuple(ch.get("ns") or ())
                kind, data = ch["type"], ch["data"]
                if kind == "messages":
                    chunk, md = data
                    if isinstance(chunk, AIMessageChunk):   # ToolMessage é ignorado (o callback cobre as tools)
                        bus.emit_many(response.feed_message(chunk, md or {}, ns))
                elif kind == "updates":
                    if isinstance(data, dict):
                        node, upd = next(iter(data.items()), (None, None))
                        if node == "model" and ns == () and isinstance(upd, dict) and upd.get("messages"):
                            bus.emit_many(response.on_model_update(ns, upd["messages"][-1]))
                        bus.emit_many(actions.parse_update(ns, data))
                elif kind == "custom":
                    bus.emit_many(actions.parse_custom(ns, data))
                elif kind == "values" and ns == ():   # values de subagent não é o estado final
                    state = data
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:
                    pass
        return state

    def _collect_sources(self) -> list[dict]:
        """Fontes do canal lateral neste turno, sem repetir a mesma URL."""
        if self.channel is None or self.turn is None:
            return []
        sources, seen = [], set()
        for pub in self.channel.query(turn=self.turn, kind="sources"):
            payload = pub.payload if isinstance(pub.payload, (list, tuple)) else [pub.payload]
            for item in payload:
                if not isinstance(item, dict):
                    continue
                key = item.get("url") or repr(sorted(item.items()))
                if key not in seen:
                    seen.add(key)
                    sources.append(item)
        return sources

    def _finish(self, state: dict | None, error: BaseException | None) -> None:
        res, bus = self.result, self.bus
        if self.cancel_event.is_set() and error is None:
            self.on_cancel()
            return
        res.state = state
        if error is None:
            for ev in self._safe(self.response.flush, []):
                bus.emit(ev)
        res.stats = self._safe(self.actions.stats, None)
        if not self._claim_terminal():
            return
        if error is not None:
            res.error = error
            res.answer = self._safe(self.response.final_text, "")
            if res.stats is not None:
                res.stats.errors += 1
            bus.emit(bus.make(
                EventKind.RUN, Phase.ERROR, id=self.run_id, label="Errore durante la risposta.",
                error=str(error) or type(error).__name__, visibility=Visibility.PRIMARY,
                data={"type": type(error).__name__, "traceback": "".join(
                    traceback.format_exception(type(error), error, error.__traceback__))},
            ))
            return
        res.answer = self._final_answer(state)
        res.sources = self._safe(self._collect_sources, [])
        if res.sources:
            bus.emit(bus.make(
                EventKind.SOURCES, Phase.INFO, id=f"sources-{self.run_id}", label="Fonti consultate",
                visibility=Visibility.PRIMARY, data={"sources": res.sources},
            ))
        data: dict[str, Any] = {
            "answer": res.answer, "stats": res.stats.to_dict() if res.stats else None, "sources": res.sources,
        }
        if res.report is not None:
            data["metrics"] = self._safe(res.report.summary, None)
        bus.emit(bus.make(EventKind.RUN, Phase.END, id=self.run_id, label="Risposta completata.",
                          visibility=Visibility.PRIMARY, data=data))

    def _trace_end(self) -> None:
        """Fecha o rastreamento (grava os JSONs). Roda na thread de trabalho, ANTES de o fluxo de eventos fechar."""
        if self.tracer is None:
            return
        res = self.result
        status = "cancelled" if (res.cancelled or self.cancel_event.is_set()) else ("error" if res.error is not None else "completed")
        publications = []
        if self.channel is not None and self.turn is not None:
            publications = self._safe(lambda: self.channel.query(turn=self.turn), [])
        self.tracer.end_run(
            self.run_id, status=status, answer=res.answer, state=res.state, report=res.report, stats=res.stats,
            sources=res.sources, publications=publications, error=res.error,
        )

    def _final_answer(self, state: dict | None) -> str:
        """O texto da última mensagem do estado é a verdade; os deltas são provisórios."""
        from deep_agents.utils.json_manager import extract_response_text
        if state and state.get("messages"):
            try:
                text = extract_response_text(state)
                if text.strip():
                    return text
            except Exception:
                pass
        return self._safe(self.response.final_text, "")

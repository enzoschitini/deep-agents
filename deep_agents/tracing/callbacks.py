"""TraceCallbackHandler: callback do LangChain que alimenta o `RunCollector` (um por run).

O LangChain propaga os callbacks do agente principal para os subagents; cada execução traz `run_id` e
`parent_run_id`, e é isso que monta a árvore de spans. Nunca levanta (o rastreamento não derruba a resposta)."""

from __future__ import annotations

import functools
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from deep_agents.tracing.collector import RunCollector


def _guard(fn):
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except Exception as e:
            try:
                self.collector.note_error(fn.__name__, e)
            except Exception:
                pass
            return None
    return wrapper


class TraceCallbackHandler(BaseCallbackHandler):
    raise_error = False
    run_inline = True   # ordem estável dos callbacks (o pai é registrado antes dos filhos)

    def __init__(self, collector: RunCollector) -> None:
        self.collector = collector

    # chains (nós do LangGraph, middlewares)
    @_guard
    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):
        name = kwargs.get("name") or (serialized or {}).get("name") or (serialized or {}).get("id", [None])[-1]
        self.collector.chain_start(run_id, parent_run_id, name, inputs, tags, metadata)

    @_guard
    def on_chain_end(self, outputs, *, run_id, **kwargs):
        self.collector.chain_end(run_id, outputs)

    @_guard
    def on_chain_error(self, error, *, run_id, **kwargs):
        self.collector.span_close(run_id, error)

    # modelo
    @_guard
    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):
        self.collector.llm_start(run_id, parent_run_id, serialized, messages, tags, metadata, kwargs.get("invocation_params"))

    @_guard
    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):
        from langchain_core.messages import HumanMessage
        self.collector.llm_start(run_id, parent_run_id, serialized, [[HumanMessage(content=p) for p in prompts]], tags, metadata,
                                 kwargs.get("invocation_params"))

    @_guard
    def on_llm_new_token(self, token, *, run_id, **kwargs):
        self.collector.llm_token(run_id)

    @_guard
    def on_llm_end(self, response, *, run_id, **kwargs):
        self.collector.llm_end(run_id, response)

    @_guard
    def on_llm_error(self, error, *, run_id, **kwargs):
        self.collector.llm_error(run_id, error)

    @_guard
    def on_retry(self, retry_state, *, run_id, **kwargs):
        self.collector.llm_retry(run_id, retry_state)

    # tools
    @_guard
    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):
        name = (serialized or {}).get("name") or kwargs.get("name")
        self.collector.tool_start(run_id, parent_run_id, name, input_str, kwargs.get("inputs"), kwargs.get("tool_call_id"),
                                  tags, metadata)

    @_guard
    def on_tool_end(self, output, *, run_id, **kwargs):
        self.collector.tool_end(run_id, output)

    @_guard
    def on_tool_error(self, error, *, run_id, **kwargs):
        self.collector.tool_error(run_id, error)


def make_handler(collector: RunCollector) -> BaseCallbackHandler:
    return TraceCallbackHandler(collector)


__all__: list[Any] = ["TraceCallbackHandler", "make_handler"]

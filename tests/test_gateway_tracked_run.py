"""LLMGateway.tracked_run / run_agent e o MetricsCallbackHandler (sem árvore, tool_runs plano)."""

from __future__ import annotations

import uuid

import pytest

from deep_agents.model.llm_gateway import LLMGateway
from deep_agents.model.metrics_callback import MetricsCallbackHandler
from deep_agents.model.model_config import ModelConfig


def make_gateway():
    return LLMGateway(ModelConfig.from_spec("openai:fake"), model=object())


def test_tracked_run_yields_report_and_handlers_and_records_history():
    gw = make_gateway()
    with gw.tracked_run("meu-run") as (report, handlers):
        assert report.run_label == "meu-run"
        assert any(isinstance(h, MetricsCallbackHandler) for h in handlers)
        assert gw.history == []   # só entra no fim
    assert gw.history == [report]
    assert report.wall_time_s is not None and report.wall_time_s >= 0


def test_tracked_run_records_even_on_error():
    gw = make_gateway()
    with pytest.raises(RuntimeError):
        with gw.tracked_run() as (report, _):
            raise RuntimeError("falhou")
    assert gw.history == [report] and report.wall_time_s is not None


def test_handlers_include_extra_callbacks():
    gw = make_gateway()
    marker = object()
    gw.extra_callbacks = [marker]
    with gw.tracked_run() as (_, handlers):
        assert marker in handlers


def test_run_agent_is_invoke_only_and_merges_callbacks():
    gw = make_gateway()
    seen = {}

    class Agent:
        def invoke(self, payload, config=None, **kw):
            seen["config"], seen["kw"] = config, kw
            return {"messages": [payload]}

    mine = object()
    result, report = gw.run_agent(Agent(), {"x": 1}, config={"callbacks": [mine], "tags": ["t"]})
    assert result == {"messages": [{"x": 1}]}
    cbs = seen["config"]["callbacks"]
    assert cbs[0] is mine and any(isinstance(c, MetricsCallbackHandler) for c in cbs)
    assert seen["config"]["tags"] == ["t"]
    assert gw.history == [report]
    # `on_event` não existe mais: não é um parâmetro do gateway (sobraria como kwarg do invoke)
    gw.run_agent(Agent(), {})
    assert seen["kw"] == {}


def test_tool_runs_are_flat():
    gw = make_gateway()
    with gw.tracked_run() as (report, handlers):
        h = next(x for x in handlers if isinstance(x, MetricsCallbackHandler))
        rid, parent = uuid.uuid4(), uuid.uuid4()
        h.on_tool_start({"name": "internet_search"}, "q", run_id=rid, parent_run_id=parent, inputs={"query": "x" * 200})
        h.on_tool_end("ok", run_id=rid)
        rid2 = uuid.uuid4()
        h.on_tool_start({"name": "task"}, "", run_id=rid2, inputs={"description": "d", "subagent_type": "pesquisador"})
        h.on_tool_error(ValueError("ruim"), run_id=rid2)
    first, second = report.tool_runs
    assert set(first) == {"id", "name", "input", "duration_s", "error"}   # sem `subagent_run`
    assert first["name"] == "internet_search" and first["error"] is None and "…" in first["input"]
    assert second["error"].startswith("ValueError") and "pesquisador" in second["input"]
    assert not hasattr(h, "_parents") and "on_chain_start" not in MetricsCallbackHandler.__dict__

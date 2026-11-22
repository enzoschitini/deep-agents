"""O histórico que a CLI reenvia ao agente: só o texto da conversa, nunca as mensagens das tools.

Reenviar `result["messages"]` carregava os resultados brutos das buscas em todo turno seguinte e, junto com o
resumo de contexto (que não persiste entre chamadas sem checkpointer), refazia o resumo do histórico inteiro
a cada pergunta, até para um "valeu".
"""

from __future__ import annotations

import io

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from rich.console import Console

from deep_agents.cli import app as cli_app
from deep_agents.cli.app import ChatCLI
from deep_agents.model.metrics import RunReport
from deep_agents.model.model_config import ModelConfig


class FakeGateway:
    """Devolve sempre o mesmo resultado e guarda o que a CLI mandou ao agente em cada turno."""

    def __init__(self, result: dict) -> None:
        self.config = ModelConfig.from_spec("openai:fake")
        self.result = result
        self.payloads: list[list] = []

    def run_agent(self, agent, payload, **kwargs):
        self.payloads.append(list(payload["messages"]))   # cópia: a CLI continua mexendo na lista dela
        return self.result, RunReport(run_label="t")

    def totals(self) -> dict:
        return {}


def _result_with_tools(answer: str) -> dict:
    """O que o agente devolve num turno de pesquisa: pergunta, chamada da tool, resultado bruto e resposta."""
    return {"messages": [
        HumanMessage("pergunta"),
        AIMessage("", tool_calls=[{"name": "internet_search", "args": {"query": "x"}, "id": "c1", "type": "tool_call"}]),
        ToolMessage("resultado bruto enorme da busca", tool_call_id="c1"),
        AIMessage(answer),
    ]}


@pytest.fixture
def make_cli(monkeypatch):
    monkeypatch.setattr(cli_app, "manage_result_json", lambda result: "")   # não escreve data/agent_result.json

    def make(result: dict) -> tuple[ChatCLI, FakeGateway]:
        gateway = FakeGateway(result)
        return ChatCLI(None, gateway, console=Console(file=io.StringIO(), width=80)), gateway

    return make


def test_history_keeps_only_the_conversation_text(make_cli):
    cli, _ = make_cli(_result_with_tools("resposta final"))

    cli._send("pergunta")

    assert cli.messages == [
        {"role": "user", "content": "pergunta"},
        {"role": "assistant", "content": "resposta final"},
    ]


def test_next_turn_does_not_resend_tool_messages(make_cli):
    cli, gateway = make_cli(_result_with_tools("resposta final"))

    cli._send("pergunta")
    cli._send("e agora?")

    assert gateway.payloads[1] == [
        {"role": "user", "content": "pergunta"},
        {"role": "assistant", "content": "resposta final"},
        {"role": "user", "content": "e agora?"},
    ]


def test_blank_answer_leaves_no_dangling_question(make_cli):
    cli, _ = make_cli({"messages": [HumanMessage("pergunta"), AIMessage("   ")]})

    cli._send("pergunta")

    assert cli.messages == []

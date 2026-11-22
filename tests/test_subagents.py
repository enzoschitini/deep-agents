"""Subagent `pesquisador` no agente REAL (create_deep_agent + middlewares do projeto) com modelo falso:
a delegação funciona, as buscas do subagent não vazam para o contexto do principal e a CLI mostra o subagent."""

from __future__ import annotations

import io

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from rich.console import Console

from deep_agents.agent import AgentBuilder
from deep_agents.cli import app as cli_app
from deep_agents.cli.app import ChatCLI
from deep_agents.cli.renderer import subagents_used, tools_used
from deep_agents.memory.build_memory import MemoryBuilder
from deep_agents.model.llm_gateway import LLMGateway
from deep_agents.model.model_config import ModelConfig
from deep_agents.subagents.build_subagents import SubagentBuilder
from deep_agents.toolkit.build_toolkit import ToolkitBuilder
from tests.fakes import FakeTavily, ScriptedChat, search, tool_call, tool_round

LONG_TASK = "Levantar o estado atual do campeonato e os números principais do time. " * 4


def task(subagent: str, description: str) -> dict:
    return tool_call("task", {"description": description, "subagent_type": subagent})


class DelegatingChat(ScriptedChat):
    """Modelo falso que decide pela situação, não pela ordem das chamadas (os dois pesquisadores rodam em paralelo
    e disputariam um roteiro único): o principal delega 2 ângulos e depois responde; cada pesquisador busca uma
    vez o ângulo que recebeu e depois responde."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        system = str(messages[0].content) if messages and messages[0].type == "system" else ""
        is_researcher = "Você é um pesquisador" in system
        done = any(m.type == "tool" for m in messages)
        if is_researcher and not done:
            angle = "angulo a" if "estado atual" in str(messages[1].content) else "angulo b"
            reply = tool_round(search(angle))
        elif is_researcher:
            reply = AIMessage("- achado (https://exemplo.com/1)\nLacunas: nenhuma")
        elif not done:
            reply = tool_round(task("pesquisador", LONG_TASK), task("pesquisador", "Ângulo B: críticas."))
        else:
            reply = AIMessage("Relatório final.")
        self.log.append(("main", len(messages), 0, system))   # sem estado compartilhado: as threads rodam em paralelo
        return ChatResult(generations=[ChatGeneration(message=reply)])


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setattr(cli_app, "manage_result_json", lambda result: "")
    fake = DelegatingChat()
    config = ModelConfig.from_spec("openai:gpt-6.1-sol")
    memory = MemoryBuilder(database="fake_vectorial")
    builder = AgentBuilder(config, memory=memory)
    builder.gateway = LLMGateway(config, model=fake)
    builder.toolkit = ToolkitBuilder(groups={"tavily": FakeTavily})
    agent, gateway = builder.build()
    output = io.StringIO()
    cli = ChatCLI(agent, gateway, console=Console(file=output, width=140), memory=memory)
    cli.tool_names = {"internet_search"}
    return cli, fake, output


FAKE_TOOLKIT = ToolkitBuilder(groups={"tavily": FakeTavily})


def test_builder_makes_a_researcher_with_its_own_tavily_tool():
    spec = SubagentBuilder().build(DelegatingChat(), FAKE_TOOLKIT)[0]

    assert spec["name"] == "pesquisador"
    assert "runnable" in spec and spec["description"]


def test_researcher_keeps_tavily_even_if_the_main_agent_has_no_tools():
    main_without_tools = ToolkitBuilder({"tavily": {"enabled": False}}, groups={"tavily": FakeTavily})

    assert main_without_tools.build() == []
    assert len(SubagentBuilder().build(DelegatingChat(), main_without_tools)) == 1


def test_builder_rejects_unknown_subagent_and_skips_disabled():
    with pytest.raises(ValueError, match="desconhecido"):
        SubagentBuilder({"fantasma": {"enabled": True}}).build(None, FAKE_TOOLKIT)
    assert SubagentBuilder({"pesquisador": {"enabled": False}}).build(None, FAKE_TOOLKIT) == []


def test_task_tool_exists_only_with_a_subagent(session):
    cli, fake, _ = session

    cli._send("compare A e B")

    first_call_system = fake.log[0][3]
    assert "pesquisador" in first_call_system   # a tool `task` lista os subagents disponíveis


def test_delegation_reaches_the_final_answer(session):
    cli, fake, _ = session

    cli._send("compare A e B")

    assert cli.messages[-1] == {"role": "assistant", "content": "Relatório final."}
    assert len(fake.calls("main")) == 6   # principal (2) + cada pesquisador (2)


def test_cli_shows_the_subagents_called_and_their_tools(session):
    cli, _, output = session

    cli._send("compare A e B")

    text = output.getvalue()
    assert text.count("subagent chiamato: pesquisador") == 2
    assert "Ângulo B: críticas." in text
    assert "«angulo a»" in text and "«angulo b»" in text
    assert "subagent: 2" in text   # contagem na linha de métricas


def test_report_attributes_each_search_to_its_subagent(session):
    cli, _, _ = session

    cli._send("compare A e B")

    report = cli.gateway.history[-1]
    delegations = subagents_used(report, {"internet_search"})
    assert [d["subagent"] for d in delegations] == ["pesquisador", "pesquisador"]
    assert sorted(len(d["tools"]) for d in delegations) == [1, 1]
    assert tools_used(report, {"internet_search"}) == []   # nenhuma busca solta: todas vieram dos subagents
    assert len(delegations[0]["task"]) <= 110   # `description` longa é encurtada na exibição

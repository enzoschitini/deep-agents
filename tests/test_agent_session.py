"""Sessão de várias perguntas pelo agente REAL (create_deep_agent + middlewares do projeto) e a CLI real,
com modelo falso: confere o custo estrutural (chamadas escondidas) sem gastar API.

O roteiro reproduz uma sessão medida de verdade: 4 perguntas de pesquisa (leitura da skill + buscas, algumas
em várias rodadas) entre conversa simples. Antes da correção, o resumo de contexto rodava a cada turno e a
sessão fazia 21 chamadas ao modelo (5 de resumo escondidas); o "valeu" final custava 2 chamadas.
"""

from __future__ import annotations

import io

import pytest
from langchain_core.messages import AIMessage
from rich.console import Console

from deep_agents.agent import AgentBuilder
from deep_agents.cli import app as cli_app
from deep_agents.cli.app import ChatCLI
from deep_agents.memory.build_memory import MemoryBuilder
from deep_agents.model.llm_gateway import LLMGateway
from deep_agents.model.model_config import ModelConfig
from deep_agents.prompts.agent_prompts import format_today
from tests.fakes import ScriptedChat, internet_search, read_skill, search, tool_round

ANSWER = "Resposta com fatos e números importantes sobre o campeonato. " * 6

TURNS = [
    ("oi", [AIMessage("Oi! Sou a Laura, como posso ajudar?")]),
    ("quem é o craque da laliga?", [AIMessage("Você quer saber quem é o principal craque hoje?")]),
    ("Atualmente", [tool_round(read_skill()), tool_round(search("a"), search("b"), search("c")), AIMessage(ANSWER)]),
    ("tabela top 5", [
        tool_round(read_skill()), tool_round(search("a"), search("b"), search("c")),
        tool_round(search("d")), tool_round(search("e")), tool_round(search("f"), search("g")), AIMessage(ANSWER),
    ]),
    ("qual a posição do Betis?", [tool_round(read_skill()), tool_round(search("a")), tool_round(search("b")), AIMessage(ANSWER)]),
    ("valeu", [AIMessage("De nada!")]),
]


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setattr(cli_app, "manage_result_json", lambda result: "")   # não escreve data/agent_result.json
    fake = ScriptedChat(script=[message for _, replies in TURNS for message in replies])
    config = ModelConfig.from_spec("openai:gpt-6.1-sol")
    memory = MemoryBuilder(database="fake_vectorial")   # em RAM: não toca no local_database.csv de verdade
    builder = AgentBuilder(config, memory=memory)
    builder.gateway = LLMGateway(config, model=fake)
    builder.build_tools = lambda: [internet_search]
    agent, gateway = builder.build()
    cli = ChatCLI(agent, gateway, console=Console(file=io.StringIO(), width=100), memory=memory)
    return cli, fake


def test_session_makes_no_hidden_summary_calls(session):
    cli, fake = session

    for text, _ in TURNS:
        cli._send(text)

    assert fake.calls("summary") == []
    assert len(fake.calls("main")) == sum(len(replies) for _, replies in TURNS)


def test_simple_turn_after_research_is_a_single_small_call(session):
    cli, fake = session
    for text, _ in TURNS[:-1]:
        cli._send(text)
    before = len(fake.log)

    cli._send("valeu")

    new_calls = fake.log[before:]
    assert [kind for kind, *_ in new_calls] == ["main"]
    # A chamada leva o system prompt (o tamanho da primeira chamada da sessão) + o texto da conversa, e nada dos
    # resultados das buscas (que somavam dezenas de milhares de caracteres).
    first_call_chars = fake.log[0][2]
    assert new_calls[0][2] < first_call_chars + 5_000


def test_history_after_the_session_is_plain_text(session):
    cli, _ = session

    for text, _ in TURNS:
        cli._send(text)

    assert [m["role"] for m in cli.messages] == ["user", "assistant"] * len(TURNS)
    assert all(isinstance(m["content"], str) for m in cli.messages)


def test_system_prompt_tells_the_model_today_s_date(session):
    cli, fake = session

    cli._send("oi")

    first_system_prompt = fake.log[0][3]
    assert format_today() in first_system_prompt

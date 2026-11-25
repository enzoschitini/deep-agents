"""Configuração e montagem do agente, compartilhadas pela CLI (`cli/__main__.py`) e pelo servidor web (`server/`).

Aqui vivem o modelo inicial, a toolkit e os subagents. Os dois entry points só decidem COMO falar com o agente."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from deep_agents.agent import AgentBuilder
from deep_agents.memory.build_memory import MemoryBuilder
from deep_agents.model.model_config import ModelConfig
from deep_agents.prompts.system import SUMMARY_PROMPT
from deep_agents.streaming.options import StreamOptions
from deep_agents.subagents.build_subagents import SubagentBuilder
from deep_agents.toolkit.build_toolkit import ToolkitBuilder
from deep_agents.toolkit.side_channel import SideChannel
from deep_agents.tracing import TraceOptions, Tracer, build_config_snapshot

# Modelo inicial, no formato "provider:modelo". Na CLI: "/" lista os comandos e "/modello" troca de modelo.
#   openai:gpt-5.4 · openai:gpt-5-mini · anthropic:claude-sonnet-5-5 · google_genai:...
MODEL_SPEC = "openai:gpt-6.1-sol"

MODEL = ModelConfig.from_spec(
    MODEL_SPEC,
    temperature=None,   # None = padrão do modelo (ou 0.0–2.0). Na CLI: /temperatura
    thinking=None,      # None = padrão | "off" | "low" | "medium" | "high". Na CLI: /thinking
    timeout=120,
    max_retries=2,
    # max_tokens=..., extra={...}  # controles opcionais
)

# Toolkit: {grupo: {"enabled": bool, "tools": [nomes] | None (= todas do grupo)}}
TOOLKIT = {
    "tavily": {"enabled": True, "tools": None},
}

# Subagents que o agente principal pode chamar (tool `task`): {subagent: {"enabled": bool}}
SUBAGENTS = {
    "pesquisador": {"enabled": True},
    "redator": {"enabled": True},
}

# Subagents dinâmicos: o principal ganha a tool `eval` (REPL JavaScript) e despacha os subagents acima com `task()`
# em loops/Promise.all (lotes, votação, torneio). Só é usado quando o pedido contém "workflow" (ver rules/09_workflow.md).
# "max_concurrency": None = padrão de `config.DYNAMIC_MAX_CONCURRENCY`.
DYNAMIC_SUBAGENTS = {"enabled": True, "max_concurrency": None}

# Streaming da resposta (CLI e servidor): palavra a palavra. `summary_marker` é o início real do prompt do
# `SummarizationMiddleware` (memory/build_memory.py usa `SUMMARY_PROMPT`): identifica as chamadas de resumo para
# que os tokens delas não vazem como resposta.
STREAMING = StreamOptions(granularity="word", summary_marker=SUMMARY_PROMPT[:40])

# Rastreamento (o "LangSmith" local): cada resposta grava uma pasta de JSONs em `data/tracing/` (ver tracing/README.md).
# `enabled=False` (ou DEEP_AGENTS_TRACING=0) desliga. `summary_marker` marca as chamadas de resumo de contexto.
TRACING = TraceOptions(summary_marker=SUMMARY_PROMPT[:40])


@dataclass
class Backend:
    """Tudo o que um entry point precisa para conversar com o agente."""

    agent: Any
    gateway: Any
    memory: MemoryBuilder
    toolkit: ToolkitBuilder
    create_agent: Callable[[ModelConfig], tuple[Any, Any]]   # refaz (agent, gateway) com outro modelo/temperatura/thinking
    tracer: Tracer | None = None                              # rastreamento em JSON (passe ao AgentStreamer)


def build_backend(model: ModelConfig = MODEL, *, memory: MemoryBuilder | None = None) -> Backend:
    """Monta memória, canal lateral, toolkit, subagents e o agente. Levanta a exceção original se o agente não subir."""
    memory = memory or MemoryBuilder()   # sessão nova e vazia; compartilhada entre as reconstruções do agente
    channel = SideChannel(session_provider=lambda: memory.session_id)   # canal lateral das tools (fontes etc.)
    toolkit = ToolkitBuilder(TOOLKIT, channel=channel)   # criado uma vez: sobrevive às reconstruções do agente
    subagents = SubagentBuilder(SUBAGENTS)

    def create_agent(config: ModelConfig):
        return AgentBuilder(config, memory=memory, toolkit=toolkit, subagents=subagents, dynamic=DYNAMIC_SUBAGENTS).build()

    tracer = Tracer(
        TRACING,
        config_snapshot=lambda cfg: build_config_snapshot(
            cfg, toolkit=TOOLKIT, subagents=SUBAGENTS, dynamic=DYNAMIC_SUBAGENTS, streaming=STREAMING),
        session_provider=lambda: memory.session_id,
    )
    agent, gateway = create_agent(model)
    return Backend(agent, gateway, memory, toolkit, create_agent, tracer)
